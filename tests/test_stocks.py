"""ST01〜09、HX01/02、EX01の仕様と実SQLiteでの原子性を確認する。"""

from datetime import date

import pytest

from app import create_app, db
from app.services import stocks


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "stocks.sqlite3"})
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO operators VALUES(1,'試験担当')")
            c.execute("INSERT INTO warehouses(warehouse_id,name,facility_type,address) VALUES(1,'試験倉庫','試験','架空住所')")
            c.execute("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(1,'試験品目','試験','個',0,7)")
            c.execute("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(2,'試験水','試験','L',1,7)")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def stock_input(**changes):
    return {"warehouse_id": "1", "item_id": "1", "location": "棚A", "initial_quantity": "0",
            "expiry_state": "none", "expiry_date": None, **changes}


def create(client, **changes):
    response = client.post("/api/v1/stocks", json=stock_input(**changes))
    assert response.status_code in (200, 201), response.json
    return response.json["data"]["stock"]["stock"]["stock_id"]


def snapshot(app):
    with app.app_context():
        c = db.get_db()
        return {table: [tuple(row) for row in c.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("stocks", "stock_movements", "stock_state_events", "stock_expiry_changes", "stock_allocations")}


def test_create_reuse_zero_and_movement(app, client):
    sid = create(client)
    assert client.get(f"/api/v1/stocks/{sid}").json["data"]["stock"]["quantity"] == "0.0"
    response = client.post("/api/v1/stocks", json=stock_input(initial_quantity="3", operator_id="1"))
    assert response.status_code == 200
    data = response.json["data"]
    assert data["reused_existing"] is True
    assert data["stock"]["stock"]["stock_id"] == sid
    assert data["movement"]["operator_name"] == "試験担当"
    assert data["movement"]["merge_generation"] == 0
    assert response.headers["Location"] == f"/api/v1/stocks/{sid}"
    before = snapshot(app)
    create(client)
    assert snapshot(app) == before


def test_unconfirmed_always_separate(client):
    assert create(client, expiry_state="unconfirmed") != create(client, expiry_state="unconfirmed")


@pytest.mark.parametrize("changes,code", [
    ({"initial_quantity": "1"}, "VALIDATION_ERROR"),
    ({"initial_quantity": "1.1", "operator_id": "1"}, "INTEGER_REQUIRED"),
    ({"initial_quantity": "1.001", "operator_id": "1"}, "DECIMAL_PRECISION"),
    ({"initial_quantity": 1}, "VALIDATION_ERROR"),
    ({"initial_quantity": "-1"}, "VALIDATION_ERROR"),
    ({"initial_quantity": "9007199254740993", "operator_id": "1"}, "NUMBER_NOT_REPRESENTABLE"),
    ({"operator_id": "99"}, "REFERENCE_NOT_FOUND"),
    ({"item_id": "99"}, "REFERENCE_NOT_FOUND"),
    ({"warehouse_id": "99"}, "REFERENCE_NOT_FOUND"),
    ({"warehouse_id": "01"}, "VALIDATION_ERROR"),
    ({"reason": "数量0"}, "VALIDATION_ERROR"),
    ({"expiry_state": "dated", "expiry_date": "2026-02-29"}, "VALIDATION_ERROR"),
    ({"expiry_state": "none", "expiry_date": "2026-11-12"}, "VALIDATION_ERROR"),
    ({"location": " "}, "VALIDATION_ERROR"),
    ({"quantity": "3"}, "READ_ONLY_FIELD"),
])
def test_create_rejection_unchanged(app, client, changes, code):
    before = snapshot(app)
    response = client.post("/api/v1/stocks", json=stock_input(**changes))
    assert response.status_code == 422
    assert response.json["error"]["code"] == code
    assert snapshot(app) == before


def test_decimal_addition_and_ambiguous_candidates(app, client):
    sid = create(client, item_id="2", initial_quantity="0.1", operator_id="1")
    create(client, item_id="2", initial_quantity="0.2", operator_id="1")
    assert client.get(f"/api/v1/stocks/{sid}").json["data"]["stock"]["quantity"] == "0.3"
    other = create(client, item_id="2", location="棚B")
    assert client.patch(f"/api/v1/stocks/{other}", json={"location": "棚A"}).status_code == 200
    before = snapshot(app)
    response = client.post("/api/v1/stocks", json=stock_input(item_id="2", initial_quantity="1", operator_id="1"))
    assert response.status_code == 409
    assert response.json["error"]["details"]["candidate_stock_ids"] == [sid, other]
    assert snapshot(app) == before


def test_date_boundary_filter_and_alerts(client, monkeypatch):
    monkeypatch.setattr(stocks, "today", lambda: date(2026, 11, 12))
    for index, day in enumerate(("2026-11-11", "2026-11-12", "2026-11-19", "2026-11-20")):
        create(client, expiry_state="dated", expiry_date=day, location=str(index))
    create(client, expiry_state="unconfirmed")
    assert client.get("/api/v1/stocks?expiry_status=near").json["page"]["total"] == 2
    assert client.get("/api/v1/stocks?expiry_status=valid").json["page"]["total"] == 1
    data = client.get("/api/v1/stock-alerts").json["data"]
    assert (data["expired_count"], data["near_expiry_count"], data["unconfirmed_count"]) == (1, 2, 1)
    assert client.get("/api/v1/stocks?limit=1&offset=2").json["page"] == {"limit": 1, "offset": 2, "total": 5}


def test_expiry_state_history_and_closed_item(app, client):
    sid = create(client)
    root = f"/api/v1/stocks/{sid}"
    values = {"expiry_state": "dated", "expiry_date": "2026-12-01", "operator_id": "1"}
    assert client.put(root + "/expiry", json=values).status_code == 200
    before = snapshot(app)
    assert client.put(root + "/expiry", json=values).json["error"]["code"] == "NO_CHANGE"
    assert snapshot(app) == before
    actor = {"operator_id": "1", "confirmed": True}
    assert client.post(root + "/logical-deletion", json=actor).status_code == 200
    assert client.get("/api/v1/stocks").json["data"] == []
    assert client.get("/api/v1/stocks?state=deleted").json["page"]["total"] == 1
    assert client.patch(root, json={"location": "棚C"}).json["error"]["code"] == "STOCK_NOT_ACTIVE"
    assert client.post(root + "/restoration", json=actor).status_code == 200
    assert client.get(root + "/state-events").json["page"]["total"] == 2
    assert client.get(root + "/expiry-changes").json["page"]["total"] == 1
    assert client.post(root + "/logical-deletion", json=actor).status_code == 200
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE items SET registration_state='closed' WHERE item_id=1")
    before = snapshot(app)
    assert client.post(root + "/restoration", json=actor).json["error"]["code"] == "ITEM_CLOSED"
    assert client.post("/api/v1/stocks", json=stock_input()).json["error"]["code"] == "ITEM_CLOSED"
    assert snapshot(app) == before


def duplicate_pair(client):
    left = create(client, initial_quantity="3", operator_id="1")
    right = create(client, location="棚B", initial_quantity="4", operator_id="1")
    client.patch(f"/api/v1/stocks/{right}", json={"location": "棚A"})
    return left, right


def preview(client, left, right):
    return client.post("/api/v1/stock-merges/preview", json={"source_stock_id": left, "target_stock_id": right})


def test_merge_preserves_history_replay_and_generation(app, client):
    left, right = duplicate_pair(client)
    before_movements = snapshot(app)["stock_movements"]
    response = preview(client, left, right)
    assert response.status_code == 200
    values = {"preview_token": response.json["data"]["preview_token"], "operator_id": "1", "confirmed": True}
    response = client.post("/api/v1/stock-merges", json=values)
    assert response.status_code == 200
    assert response.json["data"]["source"]["stock"]["state"] == "merged"
    target = response.json["data"]["target"]["stock"]
    assert target["quantity"] == "7.0" and target["merge_generation"] == 1
    assert snapshot(app)["stock_movements"] == before_movements
    assert client.post("/api/v1/stock-merges", json=values).status_code == 200
    assert snapshot(app)["stocks"][1][4] == 7
    with app.app_context():
        assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_changed_preview_no_partial_write(app, client):
    left, right = duplicate_pair(client)
    token = preview(client, left, right).json["data"]["preview_token"]
    client.patch(f"/api/v1/stocks/{right}", json={"location": "変更後"})
    before = snapshot(app)
    response = client.post("/api/v1/stock-merges", json={"preview_token": token, "operator_id": "1", "confirmed": True})
    assert response.json["error"]["code"] == "PREVIEW_CHANGED"
    assert snapshot(app) == before


def test_allocated_stock_cannot_delete_or_merge(app, client):
    left, right = duplicate_pair(client)
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO shelters(shelter_id,name,address) VALUES(1,'避難所','架空住所')")
        c.execute("INSERT INTO stock_allocations(stock_id,shelter_id,quantity) VALUES(?,1,2)", (left,))
    before = snapshot(app)
    assert client.post(f"/api/v1/stocks/{left}/logical-deletion", json={"operator_id": "1", "confirmed": True}).json["error"]["code"] == "ALLOCATIONS_EXIST"
    assert preview(client, left, right).json["error"]["code"] == "ALLOCATIONS_EXIST"
    assert snapshot(app) == before


def test_registration_failure_rolls_back_stock(app, client):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("CREATE TRIGGER test_movement_failure BEFORE INSERT ON stock_movements BEGIN SELECT RAISE(ABORT,'test'); END")
    before = snapshot(app)
    assert client.post("/api/v1/stocks", json=stock_input(initial_quantity="2", operator_id="1")).status_code == 500
    assert snapshot(app) == before


def test_merge_failure_rolls_back_target_and_token_retry(app, client):
    left, right = duplicate_pair(client)
    token = preview(client, left, right).json["data"]["preview_token"]
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("CREATE TRIGGER test_merge_failure BEFORE UPDATE ON stocks WHEN NEW.state='merged' BEGIN SELECT RAISE(ABORT,'test'); END")
    before = snapshot(app)
    values = {"preview_token": token, "operator_id": "1", "confirmed": True}
    assert client.post("/api/v1/stock-merges", json=values).status_code == 500
    assert snapshot(app) == before
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("DROP TRIGGER test_merge_failure")
    assert client.post("/api/v1/stock-merges", json=values).status_code == 200


@pytest.mark.parametrize("method,path,body,status,code", [
    ("post", "/api/v1/stocks", '{"location":"a","location":"b"}', 400, "INVALID_JSON"),
    ("post", "/api/v1/stocks", '[]', 400, "INVALID_JSON"),
    ("post", "/api/v1/stocks", '{', 400, "INVALID_JSON"),
    ("get", "/api/v1/stocks?limit=0", None, 422, "VALIDATION_ERROR"),
    ("get", "/api/v1/stocks?limit=1&limit=2", None, 422, "VALIDATION_ERROR"),
    ("get", "/api/v1/stocks?unknown=x", None, 422, "UNKNOWN_FIELD"),
    ("get", "/api/v1/stocks/01", None, 422, "VALIDATION_ERROR"),
    ("get", "/api/v1/stocks/999", None, 404, "RESOURCE_NOT_FOUND"),
    ("delete", "/api/v1/stocks/1", None, 405, "METHOD_NOT_ALLOWED"),
    ("get", "/api/v1/stocks/1/unknown", None, 404, "RESOURCE_NOT_FOUND"),
])
def test_http_contract(client, method, path, body, status, code):
    response = getattr(client, method)(path, data=body, content_type="application/json")
    assert response.status_code == status
    assert response.json["error"]["code"] == code
    assert response.json["error"]["retryable"] is False
    if status == 405:
        assert "GET" in response.headers["Allow"]


def test_storage_lock(app, client):
    with app.app_context():
        c = db.get_db()
        c.execute("PRAGMA busy_timeout=1")
        other = db.connect_db(app.config["DATABASE"])
        try:
            other.execute("BEGIN IMMEDIATE")
            response = client.post("/api/v1/stocks", json=stock_input())
            assert response.status_code == 503
            assert response.json["error"]["retryable"] is True
        finally:
            other.rollback()
            other.close()


def test_pages_and_restoration_context(client):
    sid = create(client)
    for path in ("/stocks", "/stocks/new", f"/stocks/{sid}", f"/stocks/{sid}?restore=1"):
        response = client.get(path)
        assert response.status_code == 200
        assert "/static/js/stocks.js" in response.text
    assert "未設定" in client.get(f"/stocks/{sid}?restore=1").text
    assert client.get("/stocks/999").status_code == 404


@pytest.mark.parametrize("table,action,payload", [
    ("stock_state_events", "logical-deletion", {"operator_id": "1", "confirmed": True}),
    ("stock_expiry_changes", "expiry", {"operator_id": "1", "expiry_state": "dated", "expiry_date": "2026-12-31"}),
])
def test_history_insert_failure_rolls_back_current_state(app, client, table, action, payload):
    sid = create(client)
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute(f"CREATE TRIGGER test_history_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'test'); END")
    before = snapshot(app)
    method = client.put if action == "expiry" else client.post
    assert method(f"/api/v1/stocks/{sid}/{action}", json=payload).status_code == 500
    assert snapshot(app) == before


@pytest.mark.parametrize("changes,code", [
    ({"target_stock_id": "999"}, "REFERENCE_NOT_FOUND"),
    ({"target_stock_id": "1"}, "MERGE_CONDITION_MISMATCH"),
])
def test_invalid_merge_reference(client, changes, code):
    sid = create(client)
    response = client.post("/api/v1/stock-merges/preview", json={"source_stock_id": sid, **changes})
    assert response.json["error"]["code"] == code


def test_unconfirmed_merge_and_missing_token(app, client):
    left = create(client, expiry_state="unconfirmed")
    right = create(client, expiry_state="unconfirmed")
    before = snapshot(app)
    assert preview(client, left, right).json["error"]["code"] == "MERGE_EXPIRY_UNCONFIRMED"
    assert client.post("/api/v1/stock-merges", json={"preview_token": "missing", "operator_id": "1", "confirmed": True}).json["error"]["code"] == "PREVIEW_UNAVAILABLE"
    assert snapshot(app) == before


def test_closed_item_expiry_edit_and_confirmed_flag(app, client):
    sid = create(client)
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE items SET registration_state='closed' WHERE item_id=1")
    assert client.put(f"/api/v1/stocks/{sid}/expiry", json={"expiry_state": "unconfirmed", "expiry_date": None, "operator_id": "1"}).status_code == 200
    before = snapshot(app)
    assert client.post(f"/api/v1/stocks/{sid}/logical-deletion", json={"operator_id": "1", "confirmed": 1}).status_code == 422
    assert snapshot(app) == before


def test_search_literal_and_history_retained_after_merge(client):
    left, right = duplicate_pair(client)
    assert client.get("/api/v1/stocks?q=%25").json["data"] == []
    assert client.get("/api/v1/stocks?q=棚A&warehouse_id=1&item_id=1").json["page"]["total"] == 2
    actor = {"operator_id": "1", "confirmed": True}
    client.post(f"/api/v1/stocks/{left}/logical-deletion", json=actor)
    client.post(f"/api/v1/stocks/{left}/restoration", json=actor)
    token = preview(client, left, right).json["data"]["preview_token"]
    client.post("/api/v1/stock-merges", json={"preview_token": token, **actor})
    assert client.get(f"/api/v1/stocks/{left}/state-events").json["page"]["total"] == 2
    assert client.post(f"/api/v1/stocks/{left}/restoration", json=actor).json["error"]["code"] == "INVALID_STOCK_STATE"


def test_service_quantity_validation_without_http(app):
    from decimal import Decimal
    with app.app_context():
        values = stock_input(initial_quantity=Decimal("0.5"))
        values.update(warehouse_id=1, item_id=1, operator_id=1)
        with pytest.raises(stocks.StockError, match="整数"):
            stocks.create_stock(db.get_db(), values)
        assert db.get_db().execute("SELECT count(*) FROM stocks").fetchone()[0] == 0
