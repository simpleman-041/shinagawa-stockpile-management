"""DG01〜04・IC01、Q54〜58・73、TX10の契約と永続化を隔離DBで確認する。"""

import json
import sqlite3
from decimal import Decimal

import pytest

from app import create_app, db
from app.services import demand_groups as service


ROOT = "/api/v1/demand-groups"
CONDITIONS = f"{ROOT}/1/conditions"
CONVERSION = "/api/v1/items/1/conversion"
CURRENT_TABLES = ("demand_groups", "item_conversions", "items", "stocks")
SAVED_TABLES = (
    "calculation_runs", "calculation_group_results", "calculation_item_snapshots",
    "calculation_warehouse_snapshots", "calculation_warehouse_links", "calculation_stock_snapshots",
)


def group_input(**changes):
    """運用値と区別した需要入力を作り、指定項目だけを上書きする。"""
    return {
        "name": "テスト用需要", "calculation_unit": "L", "is_divisible": True,
        "daily_usage": "3.00", "source_text": "試験用仮定", "version_or_date": "test-v1",
        "conditions": "単体試験専用", **changes,
    }


def conversion_input(**changes):
    """換算係数と根拠を含む試験用入力を作る。"""
    return {"factor": "1.00", "source_text": "試験用換算", "version_or_date": "test-v1",
            "conditions": "単体試験専用", **changes}


def conditions_input(**group_changes):
    """登録終了品目を含む全所属2品目の一括更新入力を作る。"""
    return {"group": group_input(**group_changes), "conversions": [
        conversion_input(item_id="1"), conversion_input(item_id="2", factor="2.00"),
    ]}


@pytest.fixture
def app(tmp_path):
    """開発DBから分離した一時DBを、承認DDLで初期化したアプリを用意する。"""
    database = tmp_path / "demand-tests.sqlite3"
    application = create_app({"TESTING": True, "DATABASE": database})
    assert application.config["DATABASE"].parent == tmp_path
    with application.app_context():
        db.init_db()
    return application


@pytest.fixture
def client(app):
    """隔離アプリへHTTP要求を送るFlaskテストクライアントを返す。"""
    return app.test_client()


@pytest.fixture
def seeded(app):
    """需要・所属済み／未所属品目・在庫を持つ最小限の架空データを登録する。"""
    with app.app_context(), db.transaction(db.get_db()) as connection:
        connection.execute(
            "INSERT INTO shelters (shelter_id, name, address) VALUES (1, '試験避難所', '架空住所')"
        )
        connection.execute(
            "INSERT INTO warehouses (warehouse_id, name, facility_type, address, allocation_mode) "
            "VALUES (1, '試験倉庫', '避難所倉庫', '架空住所', 'dedicated')"
        )
        connection.execute("INSERT INTO shelter_warehouses VALUES (1, 1)")
        connection.executemany(
            "INSERT INTO items (item_id, name, category, quantity_unit, is_divisible, "
            "near_expiry_days, registration_state) VALUES (?, ?, '試験分類', '箱', 0, 30, ?)",
            [(1, "試験品目", "active"), (2, "登録終了品目", "closed"), (3, "未所属品目", "active")],
        )
        connection.executemany(
            "INSERT INTO demand_groups VALUES (?, ?, 'L', 1, 3.0, '試験出典', 'test-v1', '試験条件')",
            [(1, "試験需要1"), (2, "試験需要2")],
        )
        connection.executemany(
            "INSERT INTO item_conversions VALUES (?, 1, ?, '試験換算', 'test-v1', '試験条件')",
            [(1, 100), (2, 200)],
        )
        connection.execute(
            "INSERT INTO stocks (stock_id, warehouse_id, item_id, location, quantity, expiry_state) "
            "VALUES (1, 1, 1, '試験棚', 10, 'none')"
        )
    return app


def stored(app, tables=CURRENT_TABLES):
    """指定テーブルの全行を読み、操作前後の永続データ比較に使う。"""
    with app.app_context(), db.transaction(db.get_db(), write=False) as connection:
        return {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
                for table in tables}


def assert_error(response, status, code, path=None):
    """エラーのHTTP状態・共通JSON形式・再試行可否と、必要なら入力位置を確認する。"""
    assert response.status_code == status
    assert response.mimetype == "application/json"
    error = response.json["error"]
    assert set(error) == {"code", "message", "fields", "details", "retryable"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["fields"], list)
    assert isinstance(error["details"], dict)
    assert error["retryable"] is (code == "STORAGE_BUSY")
    if path is not None:
        assert error["fields"][0]["path"] == path


def test_empty_list_and_draft_group_persist(client, app):
    """空一覧とnullを含む下書き登録、Location、再取得による永続化を確認する。"""
    assert client.get(ROOT).json == {"data": [], "page": {"limit": 50, "offset": 0, "total": 0}}
    draft = {key: None for key in group_input()}
    draft["name"] = "  下書き需要  "
    response = client.post(ROOT, json=draft)
    assert response.status_code == 201
    assert response.mimetype == "application/json"
    assert response.headers["Location"] == CONDITIONS
    assert response.json == {"data": {"group_id": "1", **draft}}
    assert client.get(CONDITIONS).json == {"data": {"group": {"group_id": "1", **draft}, "conversions": []}}
    with app.app_context():
        assert db.get_db().execute("SELECT name, daily_usage FROM demand_groups").fetchone()[:] == ("  下書き需要  ", None)


def test_list_paging_and_complete_group_dto(client, seeded):
    """ページ件数・総件数・数値表現・主キー順と、同名需要の登録を確認する。"""
    response = client.get(f"{ROOT}?limit=1&offset=1")
    assert response.status_code == 200
    assert response.json["page"] == {"limit": 1, "offset": 1, "total": 2}
    assert response.json["data"] == [{
        "group_id": "2", "name": "試験需要2", "calculation_unit": "L", "is_divisible": True,
        "daily_usage": "3.00", "source_text": "試験出典", "version_or_date": "test-v1", "conditions": "試験条件",
    }]
    assert client.get(f"{ROOT}?offset=2").json["data"] == []
    # 同じ名前の需要も契約上は作成可能。独自のUNIQUE制約を設けない。
    assert client.post(ROOT, json=group_input(name="試験需要1")).status_code == 201
    assert [row["group_id"] for row in client.get(ROOT).json["data"]] == ["1", "2", "3"]


def test_conversion_create_update_move_and_closed_item(client, seeded):
    """換算の初回登録・更新・所属移動と、登録終了品目も設定できることを確認する。"""
    assert [c["item_id"] for c in client.get(CONDITIONS).json["data"]["conversions"]] == ["1", "2"]
    response = client.put("/api/v1/items/3/conversion", json=conversion_input(group_id="1", factor="1.23"))
    assert response.status_code == 201
    assert response.json["data"] == {"item_id": "3", "group_id": "1", "factor_x100": "123", **conversion_input(factor="1.23")}
    response = client.put("/api/v1/items/3/conversion", json=conversion_input(group_id="2", factor="0.01"))
    assert response.status_code == 200
    assert response.json["data"]["factor_x100"] == "1"
    assert response.json["data"]["factor"] == "0.01"
    assert [row["item_id"] for row in client.get(CONDITIONS).json["data"]["conversions"]] == ["1", "2"]
    assert [row["item_id"] for row in client.get(f"{ROOT}/2/conditions").json["data"]["conversions"]] == ["3"]
    response = client.put("/api/v1/items/2/conversion", json=conversion_input(group_id="2", factor="2.50"))
    assert response.status_code == 200
    assert response.json["data"]["factor_x100"] == "250"
    with seeded.app_context():
        assert db.get_db().execute("SELECT registration_state FROM items WHERE item_id=2").fetchone()[0] == "closed"


def test_atomic_conditions_replace_adds_unassigned_and_retains_null(client, seeded):
    """単位変更・未所属追加・未確認係数のnullを一括保存し、在庫不変を確認する。"""
    body = conditions_input(name="改訂需要", calculation_unit="mL", is_divisible=False, daily_usage="3000.00")
    body["conversions"][0] = conversion_input(item_id="1", factor="1000.00")
    body["conversions"][1] = conversion_input(item_id="2", factor=None, source_text=None, version_or_date=None, conditions=None)
    body["conversions"].append(conversion_input(item_id="3", factor="2000.00"))
    before = stored(seeded, ("items", "stocks"))
    response = client.put(CONDITIONS, json=body)
    assert response.status_code == 200
    assert response.json == client.get(CONDITIONS).json
    assert response.json["data"]["group"] == {"group_id": "1", **body["group"]}
    conversions = response.json["data"]["conversions"]
    assert [entry["factor_x100"] for entry in conversions] == ["100000", None, "200000"]
    assert conversions[1] == {"item_id": "2", "group_id": "1", "factor_x100": None,
                              "factor": None, "source_text": None, "version_or_date": None, "conditions": None}
    assert stored(seeded, ("items", "stocks")) == before


def test_conditions_can_explicitly_clear_all_nullable_values(client, seeded):
    """保存済みの需要条件と換算根拠を、明示したnullで下書きへ戻せることを確認する。"""
    body = conditions_input()
    body["group"] = {key: None for key in group_input()}
    body["group"]["name"] = "下書きへ戻す"
    body["conversions"] = [dict(item_id=str(item), factor=None, source_text=None, version_or_date=None, conditions=None)
                           for item in (1, 2)]
    response = client.put(CONDITIONS, json=body)
    assert response.status_code == 200
    assert response.json["data"]["group"] == {"group_id": "1", **body["group"]}
    assert client.get(CONDITIONS).json == response.json
    assert [row["factor_x100"] for row in response.json["data"]["conversions"]] == [None, None]


@pytest.mark.parametrize("factor,expected", [("92233720368547758.07", "9223372036854775807"), ("1", "100"), (None, None)])
def test_factor_exact_boundaries(client, seeded, factor, expected):
    """係数の整数入力・null・64-bit上限が丸めず保存・応答されることを確認する。"""
    response = client.put(CONVERSION, json=conversion_input(group_id="1", factor=factor))
    assert response.status_code == 200
    assert response.json["data"]["factor_x100"] == expected
    if expected == "9223372036854775807":
        assert response.json["data"]["factor"] == "92233720368547758.07"


@pytest.mark.parametrize("factor,code", [
    ("0", "VALIDATION_ERROR"), ("0.00", "VALIDATION_ERROR"), ("-1", "VALIDATION_ERROR"),
    ("1.001", "DECIMAL_PRECISION"), ("1.000", "DECIMAL_PRECISION"),
    ("92233720368547758.08", "NUMBER_NOT_REPRESENTABLE"),
    ("9" * 5000, "NUMBER_NOT_REPRESENTABLE"), (1.23, "VALIDATION_ERROR"), (True, "VALIDATION_ERROR"),
    ("1e2", "VALIDATION_ERROR"), (" 1", "VALIDATION_ERROR"), ("01", "VALIDATION_ERROR"),
    ("1.", "VALIDATION_ERROR"), ("+1", "VALIDATION_ERROR"), ("NaN", "VALIDATION_ERROR"),
    ("Infinity", "VALIDATION_ERROR"), ("１", "VALIDATION_ERROR"),
])
def test_factor_rejection_preserves_database(client, seeded, factor, code):
    """係数の型・構文・精度・範囲違反を拒否し、DBが変わらないことを確認する。"""
    before = stored(seeded)
    assert_error(client.put(CONVERSION, json=conversion_input(group_id="1", factor=factor)), 422, code, "/factor")
    assert stored(seeded) == before


@pytest.mark.parametrize("usage,divisible,status,code", [
    ("1.50", True, 201, None), ("1.50", None, 201, None), ("1.00", False, 201, None),
    ("1.50", False, 422, "INTEGER_REQUIRED"), ("0", True, 422, "VALIDATION_ERROR"),
    ("0.001", True, 422, "DECIMAL_PRECISION"), (False, True, 422, "VALIDATION_ERROR"),
    ("9007199254740993", True, 422, "NUMBER_NOT_REPRESENTABLE"),
    ("9" * 310, True, 422, "NUMBER_NOT_REPRESENTABLE"),
])
def test_usage_precision_divisibility_and_real_representation(client, app, usage, divisible, status, code):
    """使用量の正値・精度・分割可否・REALでの表現可能性に従うことを確認する。"""
    response = client.post(ROOT, json=group_input(daily_usage=usage, is_divisible=divisible))
    if code:
        assert_error(response, status, code, "/daily_usage")
        assert stored(app, ("demand_groups",))["demand_groups"] == []
    else:
        assert response.status_code == status
        assert response.json["data"]["daily_usage"] == usage
        assert response.json["data"]["is_divisible"] is divisible


@pytest.mark.parametrize("kind", ["missing", "duplicate", "other-group", "nonexistent"])
def test_invalid_conversion_set_is_not_partial_update(client, seeded, kind):
    """所属の欠落・重複・暗黙移動・不在参照を拒否し、部分保存がないことを確認する。"""
    if kind == "other-group":
        client.put("/api/v1/items/3/conversion", json=conversion_input(group_id="2"))
    before = stored(seeded)
    body = conditions_input(name="保存されてはいけない名称")
    if kind == "missing":
        body["conversions"].pop()
    elif kind == "duplicate":
        body["conversions"].append(conversion_input(item_id="1"))
    else:
        body["conversions"].append(conversion_input(item_id="3" if kind == "other-group" else "999"))
    code = "REFERENCE_NOT_FOUND" if kind == "nonexistent" else "INCOMPLETE_CONVERSION_SET"
    assert_error(client.put(CONDITIONS, json=body), 422, code)
    assert stored(seeded) == before


@pytest.mark.parametrize("body", [
    '{', '[]', 'null', '"text"', '1', '{"name":"a","name":"b"}',
    '{"group":{"name":"a","name":"b"},"conversions":[]}',
    '{"name":NaN}', '{"name":Infinity}',
])
def test_invalid_json_rejected_before_write(client, seeded, body):
    """不正構文・重複キー・不正な本文ルート・非有限定数を保存前に拒否する。"""
    before = stored(seeded)
    assert_error(client.post(ROOT, data=body, content_type="application/json"), 400, "INVALID_JSON")
    assert stored(seeded) == before


def test_truncated_http_body_is_invalid_json_not_internal_error(client, seeded):
    """宣言された長さに満たない本文を400とし、DBを更新しないことを確認する。"""
    before = stored(seeded)
    response = client.post(ROOT, data="{", content_type="application/json",
                           environ_overrides={"CONTENT_LENGTH": "10"})
    assert_error(response, 400, "INVALID_JSON")
    assert stored(seeded) == before


@pytest.mark.parametrize("field,value", [
    ("name", " "), ("name", None), ("name", "\x00"), ("source_text", ""),
    ("conditions", "\t\n"), ("version_or_date", 2026), ("is_divisible", 0),
])
def test_group_types_and_empty_text(client, app, field, value):
    """需要項目の型違いと空白・空文字等を、該当する入力位置付きで拒否する。"""
    response = client.post(ROOT, json=group_input(**{field: value}))
    assert_error(response, 422, "VALIDATION_ERROR", f"/{field}")
    assert stored(app, ("demand_groups",))["demand_groups"] == []


@pytest.mark.parametrize("method,url,body,path,code", [
    ("post", ROOT, {}, "/calculation_unit", "VALIDATION_ERROR"),
    ("post", ROOT, {**group_input(), "group_id": "1"}, "/group_id", "READ_ONLY_FIELD"),
    ("post", ROOT, {**group_input(), "extra": 1}, "/extra", "UNKNOWN_FIELD"),
    ("put", CONVERSION, {"group_id": "1"}, "/conditions", "VALIDATION_ERROR"),
    ("put", CONVERSION, conversion_input(group_id="1", factor_x100="100"), "/factor_x100", "READ_ONLY_FIELD"),
    ("put", CONDITIONS, {"group": group_input(), "conversions": None}, "/conversions", "VALIDATION_ERROR"),
    ("put", CONDITIONS, {"group": [], "conversions": []}, "/group", "VALIDATION_ERROR"),
    ("put", CONDITIONS, {"group": group_input(), "conversions": [None]}, "/conversions/0", "VALIDATION_ERROR"),
    ("put", CONDITIONS, {"group": group_input(), "conversions": [{"item_id": "1"}]}, "/conversions/0/conditions", "VALIDATION_ERROR"),
])
def test_body_shape_required_unknown_and_readonly_fields(client, seeded, method, url, body, path, code):
    """必須キー・入れ子の構造・未知項目・読取専用項目の検証とDB不変を確認する。"""
    before = stored(seeded)
    assert_error(getattr(client, method)(url, json=body), 422, code, path)
    assert stored(seeded) == before


@pytest.mark.parametrize("value", [0, True, None, "0", "01", "+1", "-1", "1.0", "１", "9223372036854775808"])
def test_reference_id_syntax_and_bound(client, seeded, value):
    """本文の参照IDに対する文字列・正整数・先頭0・64-bit範囲の制限を確認する。"""
    code = "NUMBER_NOT_REPRESENTABLE" if value == "9223372036854775808" else "VALIDATION_ERROR"
    before = stored(seeded)
    assert_error(client.put(CONVERSION, json=conversion_input(group_id=value)), 422, code, "/group_id")
    assert stored(seeded) == before


@pytest.mark.parametrize("path", [f"{ROOT}/01/conditions", f"{ROOT}/-1/conditions", "/api/v1/items/01/conversion"])
def test_path_ids_are_not_normalized(client, path):
    """URLの先頭0や負数を自動補正せず、不正IDとして拒否することを確認する。"""
    response = client.put(path, json=conversion_input(group_id="1")) if "/items/" in path else client.get(path)
    assert_error(response, 422, "VALIDATION_ERROR")


def test_ids_above_javascript_safe_range_are_preserved(client, app):
    """JavaScriptの安全整数範囲を超える有効IDも、文字列で正確に受け渡すことを確認する。"""
    large_id = 9007199254740993
    with app.app_context(), db.transaction(db.get_db()) as connection:
        connection.execute("INSERT INTO demand_groups (group_id, name) VALUES (?, '試験需要')", (large_id,))
        connection.execute(
            "INSERT INTO items (item_id, name, category, quantity_unit, is_divisible, near_expiry_days) "
            "VALUES (?, '試験品目', '試験分類', '箱', 0, 30)", (large_id,),
        )
    response = client.put(f"/api/v1/items/{large_id}/conversion", json=conversion_input(group_id=str(large_id)))
    assert response.status_code == 201
    assert response.json["data"]["item_id"] == str(large_id)
    assert client.get(f"{ROOT}/{large_id}/conditions").json["data"]["group"]["group_id"] == str(large_id)


def test_missing_path_and_body_references_are_distinct(client, seeded):
    """パス対象の不存在は404、本文内の参照先不存在は422となることを確認する。"""
    before = stored(seeded)
    assert_error(client.get(f"{ROOT}/999/conditions"), 404, "RESOURCE_NOT_FOUND")
    assert_error(client.put(f"{ROOT}/999/conditions", json=conditions_input()), 404, "RESOURCE_NOT_FOUND")
    assert_error(client.put("/api/v1/items/999/conversion", json=conversion_input(group_id="1")), 404, "RESOURCE_NOT_FOUND")
    assert_error(client.put(CONVERSION, json=conversion_input(group_id="999")), 422, "REFERENCE_NOT_FOUND", "/group_id")
    assert stored(seeded) == before


@pytest.mark.parametrize("query,code", [
    ("q=water", "UNKNOWN_FIELD"), ("limit=1&limit=2", "VALIDATION_ERROR"),
    ("offset=0&offset=1", "VALIDATION_ERROR"), ("limit=0", "VALIDATION_ERROR"),
    ("limit=201", "VALIDATION_ERROR"), ("offset=-1", "VALIDATION_ERROR"),
    ("offset=1.0", "VALIDATION_ERROR"), ("limit=", "VALIDATION_ERROR"),
    ("offset=9007199254740992", "NUMBER_NOT_REPRESENTABLE"),
])
def test_list_query_contract(client, query, code):
    """一覧クエリーの未知項目・重複・型・範囲違反を拒否することを確認する。"""
    assert_error(client.get(f"{ROOT}?{query}"), 422, code)


def test_nonlist_queries_get_body_encoding_and_media_type(client, seeded):
    """不要なクエリーやGET本文、誤ったContent-Type・UTF-8を拒否することを確認する。"""
    assert_error(client.get(f"{CONDITIONS}?limit=1"), 422, "UNKNOWN_FIELD", "/query/limit")
    assert_error(client.put(f"{CONVERSION}?extra=1", json=conversion_input(group_id="1")), 422, "UNKNOWN_FIELD")
    assert_error(client.get(ROOT, data="{}"), 400, "INVALID_JSON")
    assert_error(client.post(ROOT, data=json.dumps(group_input()), content_type="text/plain"), 415, "UNSUPPORTED_MEDIA_TYPE")
    assert_error(client.post(ROOT, data=b'\xff', content_type="application/json"), 400, "INVALID_JSON")


def test_error_field_locations_escape_json_pointer_tokens(client, seeded):
    """項目名にスラッシュやチルダがある場合も、エラー位置が正しいJSON Pointerになる。"""
    assert_error(client.post(ROOT, json={**group_input(), "extra/name~": 1}),
                 422, "UNKNOWN_FIELD", "/extra~1name~0")
    body = conditions_input()
    body["conversions"][0]["extra/name~"] = 1
    assert_error(client.put(CONDITIONS, json=body), 422, "UNKNOWN_FIELD", "/conversions/0/extra~1name~0")
    assert_error(client.get(ROOT, query_string={"extra/name~": "x"}),
                 422, "UNKNOWN_FIELD", "/query/extra~1name~0")


@pytest.mark.parametrize("method,path,allowed", [
    ("delete", ROOT, "POST"), ("post", CONDITIONS, "PUT"), ("get", CONVERSION, "PUT"),
])
def test_unsupported_methods_are_json_with_allow(client, method, path, allowed):
    """未提供メソッドが405のJSON応答となり、Allowに許可メソッドが載ることを確認する。"""
    response = getattr(client, method)(path)
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert allowed in response.headers["Allow"].split(", ")
    assert method.upper() not in response.headers["Allow"].split(", ")


def test_unknown_paths_are_scoped_and_existing_pages_preserve_html(client):
    """新APIの404だけをJSON化し、既存画面のHTMLエラー・表示と品目APIを維持する。"""
    assert_error(client.get(f"{ROOT}/unsupported"), 404, "RESOURCE_NOT_FOUND")
    assert_error(client.get(f"{CONVERSION}/unsupported"), 404, "RESOURCE_NOT_FOUND")
    assert client.get("/missing-page").mimetype == "text/html"
    assert client.delete("/items").mimetype == "text/html"
    assert client.get("/items").status_code == 200
    assert client.get("/api/v1/items").status_code == 200


def test_conversion_write_failure_rolls_back_group_and_previous_conversion(client, seeded):
    """2件目の換算更新をトリガーで失敗させ、先行する需要・換算更新も取り消す。"""
    before = stored(seeded)
    with seeded.app_context():
        db.get_db().execute(
            "CREATE TRIGGER test_fail_second_conversion BEFORE UPDATE ON item_conversions "
            "WHEN NEW.item_id=2 BEGIN SELECT RAISE(ABORT, 'test-only failure'); END"
        )
    body = conditions_input(name="保存されない名称")
    body["conversions"][0]["factor"] = "9.00"
    assert_error(client.put(CONDITIONS, json=body), 500, "DATA_INTEGRITY_ERROR")
    assert stored(seeded) == before


def test_commit_failure_rolls_back_every_related_write(client, seeded, monkeypatch):
    """遅延FK違反をCOMMIT時に発生させ、全関連更新のロールバックを確認する。"""
    before = stored(seeded, (*CURRENT_TABLES, "calculation_warehouse_snapshots"))
    write_conversion = service._write_conversion

    def write_with_deferred_fk(connection, *args, **kwargs):
        """実際の換算更新後に不正な遅延参照を追加し、COMMIT失敗を再現する。"""
        write_conversion(connection, *args, **kwargs)
        if args[0] == 1:
            connection.execute(
                "INSERT INTO calculation_warehouse_snapshots VALUES (999, 1, '試験倉庫', 'dedicated')"
            )

    monkeypatch.setattr(service, "_write_conversion", write_with_deferred_fk)
    assert_error(client.put(CONDITIONS, json=conditions_input(name="COMMIT失敗")), 500, "DATA_INTEGRITY_ERROR")
    assert stored(seeded, (*CURRENT_TABLES, "calculation_warehouse_snapshots")) == before


def test_separate_writer_lock_returns_retryable_busy_without_partial_write(client, seeded, monkeypatch):
    """独立接続の書込ロック中は再試行可能な503を返し、部分更新を残さない。"""
    before = stored(seeded)
    connect = db.connect_db
    monkeypatch.setattr(db, "connect_db", lambda path: connect(path, timeout=0.01))
    locker = connect(seeded.config["DATABASE"], timeout=0.01)
    try:
        with db.transaction(locker):
            response = client.put(CONDITIONS, json=conditions_input(name="ロック中"))
            assert_error(response, 503, "STORAGE_BUSY")
    finally:
        locker.close()
    assert stored(seeded) == before


def test_connection_failure_does_not_create_a_database(tmp_path):
    """不存在の接続先を503で通知し、誤って空のDBを新規作成しないことを確認する。"""
    missing = tmp_path / "missing.sqlite3"
    application = create_app({"TESTING": True, "DATABASE": missing})
    assert_error(application.test_client().get(ROOT), 503, "STORAGE_UNAVAILABLE")
    assert not missing.exists()


@pytest.mark.parametrize("error,code,status", [
    (PermissionError("private path"), "STORAGE_UNAVAILABLE", 503),
    (RuntimeError("private SQL and details"), "INTERNAL_ERROR", 500),
])
def test_internal_failures_do_not_expose_exception_text(client, monkeypatch, error, code, status):
    """保存先障害や予期しない例外を分類し、内部情報を応答に漏らさないことを確認する。"""
    def fail():
        """検証対象の例外を接続取得時に発生させる。"""
        raise error

    monkeypatch.setattr(db, "get_db", fail)
    response = client.get(ROOT)
    assert_error(response, status, code)
    assert "private" not in response.get_data(as_text=True)


def test_foreign_keys_reject_invalid_conversion_and_rollback(app):
    """外部キーの有効化・不正参照の拒否と、同じトランザクションの取り消しを確認する。"""
    before = stored(app)
    with app.app_context():
        connection = db.get_db()
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError), db.transaction(connection):
            connection.execute("INSERT INTO demand_groups (group_id, name) VALUES (1, '試験')")
            connection.execute("INSERT INTO item_conversions (item_id, group_id) VALUES (999, 1)")
        assert not connection.in_transaction
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert stored(app) == before


def test_service_business_validation_is_atomic_without_http(seeded):
    """HTTPを介さず分割不可の小数使用量を拒否し、例外後もDBが不変であることを確認する。"""
    before = stored(seeded)
    with seeded.app_context():
        group = group_input(is_divisible=False)
        group["daily_usage"] = Decimal("1.50")
        conversions = [dict(item_id=item, factor_x100=100, source_text=None, version_or_date=None, conditions=None)
                       for item in (1, 2)]
        with pytest.raises(service.DemandGroupError) as error:
            service.replace_conditions(db.get_db(), 1, group, conversions)
        assert error.value.code == "INTEGER_REQUIRED"
        assert error.value.fields[0]["path"] == "/group/daily_usage"
        assert not db.get_db().in_transaction
    assert stored(seeded) == before


def test_condition_changes_preserve_all_six_saved_tables_and_inventory(client, seeded):
    """保存済み計算6表を用意し、条件変更・所属移動後も当時の写しと在庫を保つ。"""
    with seeded.app_context(), db.transaction(db.get_db()) as connection:
        connection.execute(
            "INSERT INTO calculation_group_results "
            "(run_id, group_id, group_name, calculation_unit, is_divisible, daily_usage, "
            "source_text, version_or_date, conditions, result_state, unavailable_reason, reference_quantity, "
            "has_unknown_expiry, limits_people, limits_days) "
            "VALUES (1, 1, '当時の需要', 'L', 1, 3, '試験出典', 'test-v1', '試験条件', "
            "'unavailable', 'WAREHOUSE_SETUP_EDITING', 10, 0, 0, 0)"
        )
        connection.executemany(
            "INSERT INTO calculation_item_snapshots VALUES (1, ?, 1, ?, '箱', 0, ?, ?, '試験換算', 'test-v1', '試験条件')",
            [(1, "当時の品目1", "active", 100), (2, "当時の品目2", "closed", 200)],
        )
        connection.execute("INSERT INTO calculation_warehouse_snapshots VALUES (1, 1, '当時の倉庫', 'dedicated')")
        connection.execute("INSERT INTO calculation_warehouse_links VALUES (1, 1, 1, '当時の避難所')")
        connection.execute(
            "INSERT INTO calculation_stock_snapshots VALUES (1, 1, 1, 1, 10, 0, 0, 'none', NULL, 10, 10, 'dedicated', 0, 0)"
        )
        connection.execute(
            "INSERT INTO calculation_runs (run_id, shelter_id, shelter_name, target_people, target_days, "
            "base_date, calculated_at, saved_at, formula_version, setup_state, result_state, "
            "has_unknown_expiry, unavailable_reason) "
            "VALUES (1, 1, '当時の避難所', 10, 1, '2026-11-11', '2026-11-11T00:00:00.000Z', "
            "'2026-11-11T00:00:00.000Z', 'unfire-20261101-r1', 'editing', 'unavailable', 0, 'WAREHOUSE_SETUP_EDITING')"
        )
    preserved = (*SAVED_TABLES, "items", "stocks")
    before = stored(seeded, preserved)
    body = conditions_input(name="現在の需要", daily_usage="4.00")
    body["conversions"][0]["factor"] = "1.50"
    assert client.put(CONDITIONS, json=body).status_code == 200
    assert client.put(CONVERSION, json=conversion_input(group_id="2", factor="2.50")).status_code == 200
    assert stored(seeded, preserved) == before
    with seeded.app_context():
        assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []
