"""要件F04・F05、Q04/08〜10/15/17/52、API MV01〜04・TX01/02。"""

from decimal import Decimal

import pytest

from app import create_app, db
from app.services import movements, stocks


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "movements.sqlite3"})
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO operators VALUES(1,'登録時担当'),(2,'取消時担当')")
            c.execute("INSERT INTO warehouses(warehouse_id,name,facility_type,address,allocation_mode) VALUES(1,'架空倉庫','試験','架空住所','shared')")
            c.execute("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(1,'架空物品','試験','個',0,7),(2,'架空飲料','試験','L',1,7)")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def create_stock(client, **changes):
    response = client.post("/api/v1/stocks", json={"warehouse_id": "1", "item_id": "1", "location": "棚A",
        "initial_quantity": "10", "operator_id": "1", "expiry_state": "none", "expiry_date": None, **changes})
    assert response.status_code == 201, response.json
    return response.json["data"]["stock"]["stock"]["stock_id"]


def post(client, sid, **changes):
    return client.post(f"/api/v1/stocks/{sid}/movements", json={"kind": "out", "quantity": "2", "operator_id": "1", **changes})


def cancel(client, mid, **changes):
    return client.post(f"/api/v1/stock-movements/{mid}/cancellation", json={"operator_id": "2", **changes})


def snapshot(app):
    with app.app_context():
        c = db.get_db()
        # 全業務テーブルを比較し、割当・保存済み計算も変更しないことを確認する。
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: [tuple(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY 1')] for t in tables}


def allocate(app, sid, quantity=8):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO shelters(shelter_id,name,address) VALUES(1,'架空避難所','架空住所')")
        c.execute("INSERT INTO shelter_warehouses VALUES(1,1)")
        c.execute("INSERT INTO stock_allocations(stock_id,shelter_id,quantity) VALUES(?,1,?)", (sid, quantity))


def test_create_cancel_preserves_original_and_name_snapshots(app, client, monkeypatch):
    sid = create_stock(client)
    monkeypatch.setattr(stocks, "timestamp", lambda: "2026-11-12T01:02:03.004Z")
    response = post(client, sid, kind="in", quantity="3.00", reason="補充")
    assert response.status_code == 201
    assert response.content_type == "application/json"
    data = response.json["data"]
    assert Decimal(data["stock"]["stock"]["quantity"]) == 13
    original = data["movement"]
    mid = original["movement_id"]
    assert response.headers["Location"] == f"/api/v1/stock-movements/{mid}"
    assert set(original) == {"movement_id", "stock_id", "operator_id", "operator_name", "kind", "quantity", "registered_at",
                             "reason", "merge_generation", "state", "cancelled_at", "cancel_operator_id", "cancel_operator_name"}
    assert original["registered_at"] == "2026-11-12T01:02:03.004Z"
    assert original["operator_name"] == "登録時担当" and original["operator_id"] == "1"
    assert original["cancelled_at"] is None and original["reason"] == "補充"
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE operators SET name='登録担当の新名称' WHERE operator_id=1")
    monkeypatch.setattr(stocks, "timestamp", lambda: "2026-11-12T02:00:00.000Z")
    result = cancel(client, mid)
    assert result.status_code == 200
    assert Decimal(result.json["data"]["stock"]["stock"]["quantity"]) == 10
    cancelled = result.json["data"]["movement"]
    assert {k: v for k, v in cancelled.items() if k not in {"state", "cancelled_at", "cancel_operator_id", "cancel_operator_name"}} == {
        k: v for k, v in original.items() if k not in {"state", "cancelled_at", "cancel_operator_id", "cancel_operator_name"}}
    assert (cancelled["state"], cancelled["cancel_operator_id"], cancelled["cancel_operator_name"], cancelled["cancelled_at"]) == (
        "cancelled", "2", "取消時担当", "2026-11-12T02:00:00.000Z")
    assert client.get(f"/api/v1/stock-movements/{mid}").json["data"] == cancelled
    before = snapshot(app)
    assert cancel(client, mid).json["error"]["code"] == "MOVEMENT_ALREADY_CANCELLED"
    assert snapshot(app) == before
    assert client.get(f"/api/v1/stock-movements?stock_id={sid}").json["page"]["total"] == 2
    with app.app_context():
        assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_allocated_boundary_and_inbound_cancellation(app, client):
    sid = create_stock(client)
    allocate(app, sid)
    before = snapshot(app)
    response = post(client, sid, quantity="3")
    assert response.status_code == 409 and response.json["error"]["code"] == "ALLOCATION_EXCEEDS_STOCK"
    assert Decimal(response.json["error"]["details"]["allocated_total"]) == 8
    assert snapshot(app) == before
    assert post(client, sid).status_code == 201  # 10 - 2 = 割当8
    inbound = post(client, sid, kind="in", quantity="3").json["data"]["movement"]["movement_id"]
    assert post(client, sid, quantity="1").status_code == 201
    before = snapshot(app)
    assert cancel(client, inbound).json["error"]["code"] == "ALLOCATION_EXCEEDS_STOCK"
    assert snapshot(app) == before


def test_negative_outbound_and_inbound_cancel_unchanged(app, client):
    sid = create_stock(client)
    initial = client.get(f"/api/v1/stock-movements?stock_id={sid}").json["data"][0]["movement_id"]
    assert post(client, sid, quantity="2").status_code == 201
    for operation in (lambda: post(client, sid, quantity="9"), lambda: cancel(client, initial)):
        before = snapshot(app)
        response = operation()
        assert response.status_code == 409 and response.json["error"]["code"] == "NEGATIVE_STOCK"
        assert snapshot(app) == before


@pytest.mark.parametrize("changes,code", [
    ({"quantity": "0"}, "VALIDATION_ERROR"), ({"quantity": "0.00"}, "VALIDATION_ERROR"),
    ({"quantity": "-1"}, "VALIDATION_ERROR"), ({"quantity": "1e2"}, "VALIDATION_ERROR"),
    ({"quantity": "01"}, "VALIDATION_ERROR"), ({"quantity": " 2"}, "VALIDATION_ERROR"),
    ({"quantity": True}, "VALIDATION_ERROR"), ({"quantity": 2}, "VALIDATION_ERROR"),
    ({"quantity": None}, "VALIDATION_ERROR"), ({"quantity": "1.001"}, "DECIMAL_PRECISION"),
    ({"quantity": "0.5"}, "INTEGER_REQUIRED"),
    ({"quantity": "9007199254740993"}, "NUMBER_NOT_REPRESENTABLE"),
    ({"quantity": "1" + "0" * 309}, "NUMBER_NOT_REPRESENTABLE"),
    ({"operator_id": "99"}, "REFERENCE_NOT_FOUND"), ({"operator_id": 1}, "VALIDATION_ERROR"),
    ({"operator_id": "01"}, "VALIDATION_ERROR"), ({"kind": "transfer"}, "VALIDATION_ERROR"),
    ({"kind": {}}, "VALIDATION_ERROR"), ({"reason": " "}, "VALIDATION_ERROR"),
    ({"registered_at": "2026-11-12T00:00:00.000Z"}, "UNKNOWN_FIELD"),
    ({"operator_name": "任意名"}, "UNKNOWN_FIELD"), ({"merge_generation": 0}, "READ_ONLY_FIELD"),
])
def test_rejected_inputs_do_not_change_database(app, client, changes, code):
    sid = create_stock(client)
    before = snapshot(app)
    response = post(client, sid, **changes)
    assert response.status_code == 422, response.json
    assert response.json["error"]["code"] == code
    assert snapshot(app) == before


def test_decimal_operations_and_result_precision(app, client):
    sid = create_stock(client, item_id="2", initial_quantity="0.1")
    result = post(client, sid, kind="in", quantity="0.2")
    assert result.status_code == 201
    assert result.json["data"]["stock"]["stock"]["quantity"] == "0.3"
    mid = result.json["data"]["movement"]["movement_id"]
    assert cancel(client, mid).json["data"]["stock"]["stock"]["quantity"] == "0.1"
    other = create_stock(client, location="棚B", initial_quantity="9007199254740992")
    before = snapshot(app)
    response = post(client, other, kind="in", quantity="1")
    assert response.status_code == 422 and response.json["error"]["code"] == "NUMBER_NOT_REPRESENTABLE"
    assert snapshot(app) == before


def test_closed_item_allows_outbound_and_both_cancellations(app, client):
    sid = create_stock(client)
    inbound = post(client, sid, kind="in", quantity="3").json["data"]["movement"]["movement_id"]
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE items SET registration_state='closed' WHERE item_id=1")
    before = snapshot(app)
    assert post(client, sid, kind="in").json["error"]["code"] == "ITEM_CLOSED"
    assert snapshot(app) == before
    outbound = post(client, sid).json["data"]["movement"]["movement_id"]
    assert cancel(client, outbound).status_code == 200
    assert cancel(client, inbound).status_code == 200


def test_merge_generations_and_deleted_stock(app, client):
    left = create_stock(client)
    right = create_stock(client, location="棚B")
    old = {sid: client.get(f"/api/v1/stock-movements?stock_id={sid}").json["data"][0]["movement_id"] for sid in (left, right)}
    client.patch(f"/api/v1/stocks/{right}", json={"location": "棚A"})
    token = client.post("/api/v1/stock-merges/preview", json={"source_stock_id": left, "target_stock_id": right}).json["data"]["preview_token"]
    assert client.post("/api/v1/stock-merges", json={"preview_token": token, "operator_id": "1", "confirmed": True}).status_code == 200
    for sid, code in ((left, "STOCK_NOT_ACTIVE"), (right, "MERGE_GENERATION_MISMATCH")):
        before = snapshot(app)
        response = cancel(client, old[sid])
        assert response.status_code == 409 and response.json["error"]["code"] == code
        assert snapshot(app) == before
        assert client.get(f"/api/v1/stock-movements/{old[sid]}").status_code == 200
    before = snapshot(app)
    assert post(client, left).json["error"]["code"] == "STOCK_NOT_ACTIVE"
    assert snapshot(app) == before
    new = post(client, right).json["data"]["movement"]
    assert new["merge_generation"] == 1 and cancel(client, new["movement_id"]).status_code == 200
    assert client.post(f"/api/v1/stocks/{right}/logical-deletion", json={"operator_id": "1", "confirmed": True}).status_code == 200
    before = snapshot(app)
    assert post(client, right).json["error"]["code"] == "STOCK_NOT_ACTIVE"
    assert cancel(client, old[right]).json["error"]["code"] == "STOCK_NOT_ACTIVE"
    assert snapshot(app) == before
    assert client.get(f"/api/v1/stock-movements/{old[right]}").status_code == 200


def test_history_filters_half_open_period_and_pagination(client, monkeypatch):
    monkeypatch.setattr(stocks, "timestamp", lambda: "2026-11-12T00:00:00.000Z")
    sid = create_stock(client)
    first = post(client, sid).json["data"]["movement"]["movement_id"]
    second = post(client, sid).json["data"]["movement"]["movement_id"]
    monkeypatch.setattr(stocks, "timestamp", lambda: "2026-11-13T00:00:00.000Z")
    last = post(client, sid, kind="in").json["data"]["movement"]["movement_id"]
    cancel(client, first)
    root = f"/api/v1/stock-movements?stock_id={sid}"
    values = client.get(root).json["data"]
    assert [v["movement_id"] for v in values[:3]] == [last, second, first]
    assert client.get(root + "&kind=out&state=active").json["page"]["total"] == 1
    result = client.get(root + "&from=2026-11-12T00:00:00.000Z&to=2026-11-13T00:00:00.000Z&limit=1&offset=1").json
    assert result["page"] == {"limit": 1, "offset": 1, "total": 3}
    assert result["data"][0]["movement_id"] == first
    assert client.get(root + "&from=2026-11-13T00:00:00.000Z").json["page"]["total"] == 1
    assert client.get(root + "&to=2026-11-12T00:00:00.000Z").json["data"] == []
    assert client.get("/api/v1/stock-movements?stock_id=999").json["data"] == []


@pytest.mark.parametrize("query", ["kind=other", "state=deleted", "stock_id=01", "stock_id=1&stock_id=2", "warehouse_id=1",
    "from=2026-02-29T00:00:00.000Z", "from=2026-11-12T24:00:00.000Z", "from=2026-11-12", "to=2026-11-12T00:00:00Z",
    "from=2026-11-12T00:00:00.000Z&to=2026-11-12T00:00:00.000Z", "limit=201", "offset=-1"])
def test_invalid_history_queries(client, query):
    response = client.get("/api/v1/stock-movements?" + query)
    assert response.status_code == 422 and response.is_json


@pytest.mark.parametrize("method,path,payload,status", [
    ("post", "/stocks/1/movements", "[]", 400),
    ("post", "/stocks/1/movements", '{"kind":"in","kind":"out"}', 400),
    ("post", "/stocks/1/movements", '{', 400),
    ("post", "/stocks/1/movements", '{}', 422),
    ("post", "/stocks/99/movements", '{"kind":"in","quantity":"1","operator_id":"1"}', 404),
    ("get", "/stock-movements/99", None, 404),
    ("get", "/stock-movements/01", None, 422),
    ("post", "/stock-movements/99/cancellation", '{"operator_id":"1"}', 404),
    ("post", "/stock-movements/1/cancellation", '{"operator_id":"99"}', 422),
    ("post", "/stock-movements/1/cancellation", '{"operator_id":"1","confirmed":true}', 422),
    ("get", "/stock-movements", '{}', 400),
    ("get", "/stock-movements/1?unknown=x", None, 422),
    ("delete", "/stock-movements/1", None, 405),
    ("get", "/stock-movements/1/cancellation", None, 405),
    ("get", "/stock-movements/1/unknown", None, 404),
])
def test_http_contract_and_unchanged_state(app, client, method, path, payload, status):
    create_stock(client)
    before = snapshot(app)
    response = client.open("/api/v1" + path, method=method, data=payload, content_type="application/json")
    assert response.status_code == status, response.json
    assert set(response.json["error"]) == {"code", "message", "fields", "details", "retryable"}
    assert response.json["error"]["retryable"] is False
    if status == 405:
        assert response.headers["Allow"]
    assert snapshot(app) == before


@pytest.mark.parametrize("cancellation", [False, True])
def test_mid_write_failure_rolls_back_every_table(app, client, cancellation):
    sid = create_stock(client)
    with app.app_context(), db.transaction(db.get_db()) as c:
        operation = "UPDATE" if cancellation else "INSERT"
        c.execute(f"CREATE TRIGGER test_failure BEFORE {operation} ON stock_movements BEGIN SELECT RAISE(ABORT,'test failure'); END")
    before = snapshot(app)
    response = cancel(client, "1") if cancellation else post(client, sid)
    assert response.status_code == 500
    assert snapshot(app) == before


@pytest.mark.parametrize("cancellation", [False, True])
def test_independent_connection_lock_rollback_and_retry(app, client, cancellation):
    sid = create_stock(client)
    before = snapshot(app)
    with app.app_context():
        db.get_db().execute("PRAGMA busy_timeout=1")
        other = db.connect_db(app.config["DATABASE"])
        try:
            other.execute("BEGIN IMMEDIATE")
            response = cancel(client, "1") if cancellation else post(client, sid)
            assert response.status_code == 503
            assert response.json["error"]["code"] == "STORAGE_BUSY" and response.json["error"]["retryable"] is True
        finally:
            other.rollback()
            other.close()
    assert snapshot(app) == before
    assert (cancel(client, "1") if cancellation else post(client, sid)).status_code == (200 if cancellation else 201)


def test_service_direct_calls_and_page(client, app):
    sid = create_stock(client)
    with app.app_context():
        c = db.get_db()
        with pytest.raises(stocks.StockError, match="整数"):
            movements.create_movement(c, int(sid), {"kind": "out", "quantity": Decimal("0.5"), "operator_id": 1})
        result = movements.create_movement(c, int(sid), {"kind": "out", "quantity": Decimal("10"), "operator_id": 1})
        assert Decimal(result["stock"]["stock"]["quantity"]) == 0
        movements.cancel_movement(c, int(result["movement"]["movement_id"]), 2)
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    response = client.get(f"/stocks/{sid}")
    assert response.status_code == 200
    for element in ("movement-form", "movement-search", "cancellation-dialog", "refresh-stock"):
        assert f'id="{element}"' in response.text
    assert client.post(f"/api/v1/stocks/{sid}/movements", data="{}", content_type="text/plain").status_code == 415


@pytest.mark.parametrize("cancellation", [False, True])
def test_deferred_commit_failure_rolls_back_quantity_and_history(app, client, cancellation):
    sid = create_stock(client)
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("CREATE TABLE test_commit_failure(operator_id INTEGER REFERENCES operators(operator_id) DEFERRABLE INITIALLY DEFERRED)")
        operation = "UPDATE" if cancellation else "INSERT"
        c.execute(f"CREATE TRIGGER test_commit_trigger AFTER {operation} ON stock_movements BEGIN INSERT INTO test_commit_failure VALUES(999); END")
    before = snapshot(app)
    response = cancel(client, "1") if cancellation else post(client, sid)
    assert response.status_code == 500
    assert snapshot(app) == before
    with app.app_context():
        assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_cancellation_result_precision_and_multiple_allocations(app, client):
    sid = create_stock(client, initial_quantity="1")
    outbound = post(client, sid, quantity="1").json["data"]["movement"]["movement_id"]
    assert post(client, sid, kind="in", quantity="9007199254740992").status_code == 201
    before = snapshot(app)
    response = cancel(client, outbound)
    assert response.status_code == 422 and response.json["error"]["code"] == "NUMBER_NOT_REPRESENTABLE"
    assert snapshot(app) == before
    other = create_stock(client, location="棚B")
    allocate(app, other, quantity=3)
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO shelters(shelter_id,name,address) VALUES(2,'架空避難所2','架空住所')")
        c.execute("INSERT INTO shelter_warehouses VALUES(2,1)")
        c.execute("INSERT INTO stock_allocations(stock_id,shelter_id,quantity) VALUES(?,2,5)", (other,))
    before = snapshot(app)
    assert post(client, other, quantity="3").json["error"]["code"] == "ALLOCATION_EXCEEDS_STOCK"
    assert snapshot(app) == before
    assert post(client, other, quantity="2").status_code == 201


def test_unavailable_database_is_not_created(app, client, tmp_path):
    missing = tmp_path / "missing.sqlite3"
    app.config["DATABASE"] = missing
    response = post(client, "1")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert response.json["error"]["retryable"] is False
    assert not missing.exists()
