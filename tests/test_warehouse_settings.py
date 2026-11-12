"""SH06〜08・AL01/02、Q14〜16・65〜69・U01/02/07を実SQLiteで確認する。"""

from decimal import Decimal

import pytest

from app import create_app, db
from app.services import warehouse_settings as service


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "settings.sqlite3"})
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO operators VALUES(1,'架空担当者')")
            c.executemany("INSERT INTO shelters(shelter_id,name,address,setup_state) VALUES(?,?,?,'complete')",
                          [(n, f"架空避難所{n}", "架空住所") for n in (1, 2, 3)])
            c.executemany("INSERT INTO warehouses(warehouse_id,name,facility_type,address,allocation_mode) VALUES(?,?,'試験','架空住所',?)",
                          [(1, "未設定倉庫", None), (2, "共有倉庫", "shared"), (3, "専用倉庫", "dedicated")])
            c.execute("INSERT INTO shelter_warehouses VALUES(1,2),(2,2),(1,3)")
            c.execute("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(1,'架空物品','試験','個',0,7),(2,'架空飲料','試験','L',1,7)")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def stock(app, *, sid=1, wid=2, item=1, quantity=10, state="active", expiry="none"):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state,expiry_date,state) VALUES(?,?,?,'棚A',?,?,?,?)",
                  (sid, wid, item, quantity, expiry, "2000-01-01" if expiry == "dated" else None, state))
    return sid


def stored(app):
    with app.app_context():
        c = db.get_db()
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        return {name: [tuple(row) for row in c.execute(f'SELECT * FROM "{name}" ORDER BY 1')] for name in names}


def settings(client, *, shelter=1, warehouse=1, mode="shared", targets=None):
    return client.put(f"/api/v1/shelters/{shelter}/warehouse-settings/warehouses/{warehouse}",
                      json={"allocation_mode": mode, "shelter_ids": ["1", "2"] if targets is None else targets})


def allocate(client, amount, *, shelter=1, sid=1):
    return client.put(f"/api/v1/shelters/{shelter}/allocations/{sid}", json={"quantity": amount})


def complete(client, shelter=1):
    return client.put(f"/api/v1/shelters/{shelter}/warehouse-setup", json={"setup_state": "complete"})


def test_setting_replaces_all_links_and_marks_old_new_union(app, client):
    response = settings(client, warehouse=2, targets=["2", "3"])
    assert response.status_code == 200
    data = response.json["data"]
    assert set(data) == {"warehouse", "links", "affected_shelters"}
    assert data["links"] == [{"shelter_id": "2", "warehouse_id": "2"}, {"shelter_id": "3", "warehouse_id": "2"}]
    assert [s["shelter_id"] for s in data["affected_shelters"]] == ["1", "2", "3"]
    assert {s["setup_state"] for s in data["affected_shelters"]} == {"editing"}
    result = client.get("/api/v1/shelters/2/warehouse-settings").json["data"]
    assert result["shelter"]["shelter_id"] == "2" and len(result["warehouses"]) == 1
    assert result["links"] == data["links"]
    assert result["issues"][0]["code"] == "SETUP_EDITING"
    assert client.get("/api/v1/shelters/1/warehouse-settings").json["data"]["warehouses"][0]["warehouse_id"] == "3"


def test_dedicated_single_and_shared_empty_and_mode_only(app, client):
    assert settings(client, mode="dedicated", targets=["2"]).status_code == 200
    assert complete(client, 2).status_code == 200
    response = settings(client, mode="shared", targets=["2"])
    assert response.status_code == 200
    assert response.json["data"]["affected_shelters"][0]["setup_state"] == "editing"
    assert settings(client, targets=[]).status_code == 200
    assert complete(client, 3).status_code == 200  # 対応0件を完了できる。
    assert client.get("/api/v1/shelters/3/allocations").json["data"] == []


@pytest.mark.parametrize("targets", [[], ["1", "2"]])
def test_dedicated_cardinality_rejected(app, client, targets):
    before = stored(app)
    response = settings(client, mode="dedicated", targets=targets)
    assert response.status_code == 409 and response.json["error"]["code"] == "INVALID_WAREHOUSE_LINKS"
    assert stored(app) == before


@pytest.mark.parametrize("quantity", [0, 5])
def test_active_inventory_blocks_change_but_noop_keeps_complete(app, client, quantity):
    stock(app, quantity=quantity)
    before = stored(app)
    response = settings(client, warehouse=2, targets=["3"])
    assert response.status_code == 409 and response.json["error"]["code"] == "WAREHOUSE_IN_USE"
    assert stored(app) == before
    assert settings(client, warehouse=2, targets=["2", "1"]).status_code == 200
    assert stored(app) == before
    renamed = client.patch("/api/v1/shelters/1", json={"name": "改名した架空避難所"})
    assert renamed.json["data"]["setup_state"] == "complete"


def test_deleted_inventory_allows_change_but_invalid_allocation_is_500(app, client):
    stock(app, state="deleted")
    assert settings(client, warehouse=2, targets=["3"]).status_code == 200
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO stock_allocations VALUES(1,3,1)")
    before = stored(app)
    response = settings(client, warehouse=2, targets=["2"])
    assert response.status_code == 500 and response.json["error"]["code"] == "DATA_INTEGRITY_ERROR"
    assert stored(app) == before


def test_allocation_total_replacement_zero_and_stock_guards(app, client):
    stock(app)
    assert allocate(client, "6").status_code == 200
    response = allocate(client, "4", shelter=2)
    assert response.status_code == 200
    assert {k: Decimal(response.json["data"][k]) for k in ("quantity", "allocated_total", "unallocated_quantity")} == {
        "quantity": 4, "allocated_total": 10, "unallocated_quantity": 0}
    before = stored(app)
    assert allocate(client, "5", shelter=2).json["error"]["code"] == "ALLOCATION_EXCEEDS_STOCK"
    assert stored(app) == before
    assert allocate(client, "2").status_code == 200  # 既存6を置換、加算しない。
    assert allocate(client, "2").status_code == 200
    assert allocate(client, "0").status_code == 200
    before = stored(app)
    assert allocate(client, "0").status_code == 200
    assert stored(app) == before
    with app.app_context():
        c = db.get_db()
        assert c.execute("SELECT count(*) FROM stock_allocations WHERE shelter_id=1").fetchone()[0] == 0
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    response = client.post("/api/v1/stocks/1/movements", json={"kind": "out", "quantity": "7", "operator_id": "1"})
    assert response.status_code == 409 and response.json["error"]["code"] == "ALLOCATION_EXCEEDS_STOCK"
    assert stored(app) == before
    response = client.post("/api/v1/stocks/1/logical-deletion", json={"operator_id": "1", "confirmed": True})
    assert response.status_code == 409 and response.json["error"]["code"] == "ALLOCATIONS_EXIST"
    assert stored(app) == before


def test_decimal_allocations_and_candidate_pages_include_expiry_and_closed(app, client):
    stock(app, item=2, quantity=0.3, expiry="dated")
    stock(app, sid=2, expiry="unconfirmed")
    stock(app, sid=3, state="deleted")
    stock(app, sid=4, wid=3)
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE items SET registration_state='closed' WHERE item_id=2")
    assert allocate(client, "0.1").status_code == 200
    assert allocate(client, "0.2", shelter=2).status_code == 200
    before = stored(app)
    assert allocate(client, "0.21", shelter=2).status_code == 409
    assert stored(app) == before
    result = client.get("/api/v1/shelters/1/allocations?limit=1&offset=0&warehouse_id=2").json
    assert result["page"] == {"limit": 1, "offset": 0, "total": 2}
    assert result["data"][0]["stock"]["expiry_status"] == "expired"
    assert Decimal(result["data"][0]["stock"]["unallocated_quantity"]) == 0
    assert Decimal(result["data"][0]["selected_allocation"]) == Decimal("0.1")
    other = client.get("/api/v1/shelters/1/allocations?offset=1").json["data"][0]
    assert other["stock"]["stock"]["stock_id"] == "2" and other["selected_allocation"] == "0"
    assert client.get("/api/v1/shelters/1/allocations?warehouse_id=3").json["data"] == []


@pytest.mark.parametrize("shelter,wid,state", [(3, 2, "active"), (1, 3, "active"), (1, 1, "active"), (1, 2, "deleted")])
@pytest.mark.parametrize("amount", ["0", "1"])
def test_assignment_and_zero_require_active_shared_link(app, client, shelter, wid, state, amount):
    stock(app, wid=wid, state=state)
    before = stored(app)
    response = allocate(client, amount, shelter=shelter)
    assert response.status_code == 409
    assert stored(app) == before


@pytest.mark.parametrize("amount,code", [
    ("-1", "VALIDATION_ERROR"), (True, "VALIDATION_ERROR"), (1, "VALIDATION_ERROR"), (None, "VALIDATION_ERROR"),
    ("01", "VALIDATION_ERROR"), ("1e2", "VALIDATION_ERROR"), ("0.1", "INTEGER_REQUIRED"),
    ("1.001", "DECIMAL_PRECISION"), ("9007199254740993", "NUMBER_NOT_REPRESENTABLE"),
    ("9" * 5000, "NUMBER_NOT_REPRESENTABLE"),
])
def test_invalid_quantity_keeps_database(app, client, amount, code):
    stock(app)
    before = stored(app)
    response = allocate(client, amount)
    assert response.status_code == 422 and response.json["error"]["code"] == code
    assert stored(app) == before


@pytest.mark.parametrize("corruption", ["mode", "dedicated_count", "orphan", "inactive", "overallocated", "precision"])
def test_setup_rejects_corrupt_links_or_allocations(app, client, corruption):
    stock(app)
    with app.app_context(), db.transaction(db.get_db()) as c:
        if corruption == "mode":
            c.execute("UPDATE warehouses SET allocation_mode=NULL WHERE warehouse_id=2")
        elif corruption == "dedicated_count":
            c.execute("INSERT INTO shelter_warehouses VALUES(2,3)")
        else:
            c.execute("INSERT INTO stock_allocations VALUES(1,1,?)", (11 if corruption == "overallocated" else .5 if corruption == "precision" else 2,))
            if corruption == "orphan":
                c.execute("DELETE FROM shelter_warehouses WHERE warehouse_id=2 AND shelter_id=1")
            if corruption == "inactive":
                c.execute("UPDATE stocks SET state='deleted' WHERE stock_id=1")
    before = stored(app)
    response = complete(client)
    assert response.status_code == 409 and response.json["error"]["code"] == "INVALID_WAREHOUSE_LINKS"
    assert response.json["error"]["details"]["issues"]
    assert stored(app) == before


def test_missing_criteria_warn_but_do_not_block_complete(app, client):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO demand_groups(group_id,name) VALUES(1,'試験需要')")
    data = client.get("/api/v1/shelters/1/warehouse-settings").json["data"]
    assert {i["code"] for i in data["issues"]} >= {"DAILY_USAGE_MISSING", "ITEM_CONVERSION_MISSING", "STOCK_UNREGISTERED"}
    assert complete(client).status_code == 200
    with app.app_context():
        assert db.get_db().execute("SELECT count(*) FROM stocks").fetchone()[0] == 0


@pytest.mark.parametrize("payload", [
    {"allocation_mode": None, "shelter_ids": []}, {"allocation_mode": "shared", "shelter_ids": ["1", "1"]},
    {"allocation_mode": "shared", "shelter_ids": [1]}, {"allocation_mode": "shared", "shelter_ids": ["01"]},
    {"allocation_mode": "shared", "shelter_ids": ["99"]}, {"allocation_mode": "shared", "shelter_ids": None},
    {"allocation_mode": "shared", "shelter_ids": [], "confirmed": True},
])
def test_setting_input_rejections(app, client, payload):
    before = stored(app)
    response = client.put("/api/v1/shelters/1/warehouse-settings/warehouses/1", json=payload)
    assert response.status_code == 422
    assert stored(app) == before


@pytest.mark.parametrize("method,path,payload,status", [
    ("GET", "/shelters/99/warehouse-settings", None, 404),
    ("GET", "/shelters/01/warehouse-settings", None, 422),
    ("GET", "/shelters/1/warehouse-settings?limit=1", None, 422),
    ("GET", "/shelters/1/allocations?warehouse_id=01", None, 422),
    ("GET", "/shelters/1/allocations?limit=201", None, 422),
    ("GET", "/shelters/1/allocations?offset=1&offset=2", None, 422),
    ("GET", "/shelters/1/allocations", "{}", 400),
    ("PUT", "/shelters/1/allocations/99", '{"quantity":"0"}', 404),
    ("PUT", "/shelters/1/allocations/1", '{"quantity":"1","quantity":"2"}', 400),
    ("PUT", "/shelters/1/warehouse-setup", '{"setup_state":true}', 422),
    ("PUT", "/shelters/1/warehouse-setup", '{"setup_state":"complete","setup_state":"editing"}', 400),
    ("DELETE", "/shelters/1/allocations/1", None, 405),
    ("GET", "/shelters/1/warehouse-settings/unknown", None, 404),
])
def test_http_contract(app, client, method, path, payload, status):
    before = stored(app)
    response = client.open("/api/v1" + path, method=method, data=payload, content_type="application/json")
    assert response.status_code == status, response.json
    assert set(response.json["error"]) == {"code", "message", "fields", "details", "retryable"}
    assert response.json["error"]["retryable"] is False
    if status == 405:
        assert "PUT" in response.headers["Allow"]
    assert stored(app) == before


@pytest.mark.parametrize("operation", ["warehouse", "allocation", "allocation_update", "allocation_zero", "setup"])
@pytest.mark.parametrize("deferred", [False, True])
def test_partial_and_commit_failures_roll_back(app, client, operation, deferred):
    stock(app)
    with app.app_context(), db.transaction(db.get_db()) as c:
        if operation in ("allocation_update", "allocation_zero"):
            c.execute("INSERT INTO stock_allocations VALUES(1,1,2)")
        if deferred:
            c.execute("CREATE TABLE test_deferred(id INTEGER REFERENCES shelters(shelter_id) DEFERRABLE INITIALLY DEFERRED)")
        table, event = {"warehouse": ("shelter_warehouses", "INSERT"), "allocation": ("stock_allocations", "INSERT"),
                        "allocation_update": ("stock_allocations", "UPDATE"), "allocation_zero": ("stock_allocations", "DELETE"),
                        "setup": ("shelters", "UPDATE")}[operation]
        action = "INSERT INTO test_deferred VALUES(99);" if deferred else "SELECT RAISE(ABORT,'test failure');"
        c.execute(f"CREATE TRIGGER test_fail AFTER {event} ON {table} BEGIN {action} END")
    before = stored(app)
    if operation == "warehouse":
        response = settings(client)
    elif operation.startswith("allocation"):
        response = allocate(client, "0" if operation == "allocation_zero" else "1")
    else:
        response = complete(client)
    assert response.status_code == 500
    assert stored(app) == before


@pytest.mark.parametrize("operation", ["warehouse", "allocation", "setup"])
def test_independent_connection_lock(app, client, operation):
    stock(app)
    before = stored(app)
    with app.app_context():
        db.get_db().execute("PRAGMA busy_timeout=1")
        other = db.connect_db(app.config["DATABASE"])
        try:
            other.execute("BEGIN IMMEDIATE")
            response = settings(client) if operation == "warehouse" else allocate(client, "1") if operation == "allocation" else complete(client)
            assert response.status_code == 503 and response.json["error"]["code"] == "STORAGE_BUSY"
            assert response.json["error"]["retryable"] is True
        finally:
            other.rollback()
            other.close()
    assert stored(app) == before


def test_service_and_page_entry_points(app, client):
    stock(app)
    with app.app_context():
        result = service.put_allocation(db.get_db(), 1, 1, Decimal("2"))
        assert Decimal(result["allocated_total"]) == 2
        assert db.get_db().execute("PRAGMA foreign_keys").fetchone()[0] == 1
    response = client.get("/shelters/1/warehouse-settings")
    assert response.status_code == 200 and "js/warehouse-settings.js" in response.text
    assert "target-shelters" in response.text
    assert client.get("/shelters/99/warehouse-settings").status_code == 404
    assert "warehouse-settings" in client.get("/shelters/1/edit").text
    assert client.put("/api/v1/shelters/1/allocations/1", data="{}", content_type="text/plain").status_code == 415
