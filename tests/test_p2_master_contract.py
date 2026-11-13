"""2026-11-13に採用されたAPI1.0共通契約とU03・Q06の回帰検証。"""

import pytest

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "p2.sqlite3"})
    with app.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO warehouses(warehouse_id,name,facility_type,address,capacity_m3,latitude,longitude) VALUES(1,'W','test','fictional',100,35,139)")
            c.execute("INSERT INTO shelters(shelter_id,name,address) VALUES(1,'S','fictional')")
            c.executemany("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days,unit_volume_m3) VALUES(?,?,'test','L',?,1,0.01)", [(1, 'I', 1), (2, 'J', 0)])
            c.execute("INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state) VALUES(1,1,1,'shelf',10,'none')")
    return app


def snapshot(app):
    with app.app_context():
        c = db.get_db()
        return {r[0]: [tuple(row) for row in c.execute(f'SELECT * FROM "{r[0]}" ORDER BY 1,2')]
                for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def error(response, status, code):
    assert response.status_code == status
    assert response.mimetype == "application/json"
    e = response.json["error"]
    assert set(e) == {"code", "message", "fields", "details", "retryable"}
    assert e["code"] == code
    assert type(e["fields"]) is list and type(e["details"]) is dict
    assert e["retryable"] is (code == "STORAGE_BUSY")
    assert "Traceback" not in response.get_data(as_text=True)


@pytest.mark.parametrize("resource", ["warehouses", "items", "shelters"])
def test_ids_are_exact_strings_and_coordinates_are_numbers(app, resource):
    big = 9007199254740993
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute(f"UPDATE {resource} SET {resource[:-1]}_id=? WHERE {resource[:-1]}_id=2" if resource == "items" else
                  f"INSERT INTO {resource} SELECT ?," + ("'Big','test','fictional',NULL,NULL,NULL,NULL" if resource == "warehouses" else "'Big','fictional',NULL,NULL,'editing'"), (big,))
    client = app.test_client()
    rows = client.get(f"/api/v1/{resource}").json["data"]
    assert str(big) in [row[f"{resource[:-1]}_id"] for row in rows]
    result = client.get(f"/api/v1/{resource}/{big}")
    assert result.json["data"][f"{resource[:-1]}_id"] == str(big)
    if resource == "warehouses":
        row = client.get("/api/v1/warehouses/1").json["data"]
        assert row["capacity_m3"] == "100.00" and type(row["latitude"]) is float


@pytest.mark.parametrize("resource", ["warehouses", "items", "shelters"])
@pytest.mark.parametrize("raw", ['{"name":"one","name":"two"}', '[]', 'null', '{', '{"nested":{"x":1,"x":2}}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejected_without_writes(app, resource, raw):
    before = snapshot(app)
    error(app.test_client().post(f"/api/v1/{resource}", data=raw, content_type="application/json"), 400, "INVALID_JSON")
    assert snapshot(app) == before


@pytest.mark.parametrize("resource", ["warehouses", "items", "shelters"])
@pytest.mark.parametrize("identifier", ["01", "0", "-1", "9223372036854775808", "9" * 100])
def test_path_id_is_validated_before_sql(app, resource, identifier):
    response = app.test_client().get(f"/api/v1/{resource}/{identifier}")
    error(response, 422, "NUMBER_NOT_REPRESENTABLE" if len(identifier) >= 19 and identifier[0] != "0" else "VALIDATION_ERROR")


@pytest.mark.parametrize("path", ["warehouses", "items", "shelters", "warehouses/1/thresholds"])
def test_read_contract_and_http_errors(app, path):
    client = app.test_client()
    error(client.get(f"/api/v1/{path}", data="{}"), 400, "INVALID_JSON")
    error(client.get(f"/api/v1/{path}?unknown=1"), 422, "UNKNOWN_FIELD")
    error(client.get(f"/api/v1/{path}?limit=1&limit=2"), 422, "VALIDATION_ERROR")
    for query in ["offset=" + "9" * 100, "limit=201", "offset=-1", "limit=１"]:
        error(client.get(f"/api/v1/{path}?{query}"), 422, "VALIDATION_ERROR")
    response = client.delete(f"/api/v1/{path}")
    error(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["Allow"]


@pytest.mark.parametrize("method,path,field", [("patch", "warehouses/1", "capacity_m3"), ("patch", "items/1", "unit_volume_m3"), ("put", "warehouses/1/thresholds/1", "minimum_quantity")])
@pytest.mark.parametrize("value,code", [("1.234", "DECIMAL_PRECISION"), ("1.230", "DECIMAL_PRECISION"), ("9007199254740993.01", "NUMBER_NOT_REPRESENTABLE"), ("9007199254740993", "NUMBER_NOT_REPRESENTABLE"), ("1" + "0" * 309, "NUMBER_NOT_REPRESENTABLE"), (True, "VALIDATION_ERROR"), (1.23, "VALIDATION_ERROR"), ("-1", "VALIDATION_ERROR"), ("1e2", "VALIDATION_ERROR"), ("NaN", "VALIDATION_ERROR"), (" 1", "VALIDATION_ERROR")])
def test_decimal_rejections_are_atomic(app, method, path, field, value, code):
    before = snapshot(app)
    response = getattr(app.test_client(), method)(f"/api/v1/{path}", json={field: value})
    error(response, 422, code)
    assert response.json["error"]["fields"][0]["path"] == f"/{field}"
    assert snapshot(app) == before


@pytest.mark.parametrize("value,expected", [("0", "0.00"), ("1.00", "1.00"), ("1.23", "1.23"), ("9007199254740992", "9007199254740992.00")])
def test_decimal_round_trips_and_threshold_warning_do_not_change_stock(app, value, expected):
    before = snapshot(app)
    client = app.test_client()
    for _ in range(3):
        assert client.patch("/api/v1/warehouses/1", json={"capacity_m3": value}).json["data"]["capacity_m3"] == expected
        assert client.patch("/api/v1/items/1", json={"unit_volume_m3": value}).json["data"]["unit_volume_m3"] == expected
        r = client.put("/api/v1/warehouses/1/thresholds/1", json={"minimum_quantity": value})
        assert r.status_code in (200, 201) and r.json["data"]["minimum_quantity"] == expected
        assert client.get("/api/v1/warehouses/1/thresholds").json["data"][0] == {"warehouse_id": "1", "item_id": "1", "minimum_quantity": expected}
        value = expected
    after = snapshot(app)
    for table in before.keys() - {"warehouses", "items", "stock_thresholds"}:
        assert after[table] == before[table]


def test_null_omission_partial_coordinates_and_threshold_units(app):
    client = app.test_client()
    assert client.post("/api/v1/shelters", json={"name": "new", "address": "x", "target_people": None, "target_days": None}).status_code == 201
    assert client.patch("/api/v1/warehouses/1", json={"latitude": 35.123456}).status_code == 200
    assert client.get("/api/v1/warehouses/1").json["data"]["longitude"] == 139
    before = snapshot(app)
    error(client.patch("/api/v1/warehouses/1", json={"latitude": None}), 422, "VALIDATION_ERROR")
    error(client.put("/api/v1/warehouses/1/thresholds/2", json={"minimum_quantity": "1.50"}), 422, "INTEGER_REQUIRED")
    error(client.put("/api/v1/warehouses/1/thresholds/1", json={"minimum_quantity": None}), 422, "VALIDATION_ERROR")
    assert snapshot(app) == before
    assert client.put("/api/v1/warehouses/1/thresholds/2", json={"minimum_quantity": "1.00"}).status_code == 201
    assert client.patch("/api/v1/warehouses/1", json={"capacity_m3": None}).json["data"]["capacity_m3"] is None


def seed_saved_result(app, client):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE warehouses SET allocation_mode='dedicated' WHERE warehouse_id=1")
        c.execute("INSERT INTO shelter_warehouses VALUES(1,1)")
        c.execute("INSERT INTO operators VALUES(1,'Fictional operator')")
    for kind in ("in", "out"):
        assert client.post("/api/v1/stocks/1/movements", json={"kind": kind, "quantity": "1", "operator_id": "1"}).status_code == 201
    group = client.post("/api/v1/demand-groups", json={"name": "Water", "calculation_unit": "L", "is_divisible": True, "daily_usage": "3", "source_text": "Fictional", "version_or_date": "test", "conditions": "Test only"}).json["data"]
    assert client.put("/api/v1/items/1/conversion", json={"group_id": group["group_id"], "factor": "1", "source_text": "Fictional", "version_or_date": "test", "conditions": "Test only"}).status_code == 201
    calculation = client.post("/api/v1/calculations", json={"shelter_id": "1", "target_people": 100, "target_days": 2})
    assert calculation.status_code == 200
    assert client.post("/api/v1/calculation-runs", json={"calculation_token": calculation.json["data"]["calculation_token"]}).status_code == 201


def test_thresholds_drive_existing_summary_and_preserve_saved_results(app):
    client = app.test_client()
    seed_saved_result(app, client)
    assert client.get("/api/v1/warehouses/1/thresholds").json["data"] == []
    before = snapshot(app)
    for value, warning in [("11", True), ("10", False), ("0", False)]:
        r = client.put("/api/v1/warehouses/1/thresholds/1", json={"minimum_quantity": value})
        assert r.status_code in (200, 201)
        result = client.get("/api/v1/warehouses/1/summary").json["data"]["items"][0]
        assert result["daily_usable_quantity"] == "10.00" and result["below_minimum"] is warning
        assert client.get("/api/v1/gis/warehouses").json["data"]["located"][0]["warehouse_id"] == "1"
    after = snapshot(app)
    for table in before.keys() - {"stock_thresholds"}:
        assert after[table] == before[table]
    with app.app_context():
        assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.get_db().execute("SELECT count(*) FROM calculation_stock_snapshots").fetchone()[0] > 0


@pytest.mark.parametrize("resource", ["warehouses", "items", "shelters"])
def test_busy_is_retryable_without_changes(app, resource, monkeypatch):
    before = snapshot(app)
    connect = db.connect_db
    holder = connect(app.config["DATABASE"], timeout=0)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(db, "connect_db", lambda path: connect(path, timeout=0))
        error(app.test_client().get(f"/api/v1/{resource}"), 503, "STORAGE_BUSY")
    finally:
        holder.rollback()
        holder.close()
    assert snapshot(app) == before


@pytest.mark.parametrize("resource,field", [("warehouses", "allocation_mode"), ("items", "registration_state"), ("shelters", "setup_state")])
def test_readonly_missing_and_empty_patch(app, resource, field):
    client = app.test_client()
    before = snapshot(app)
    error(client.patch(f"/api/v1/{resource}/1", json={field: "x"}), 422, "READ_ONLY_FIELD")
    error(client.patch(f"/api/v1/{resource}/1", json={}), 422, "VALIDATION_ERROR")
    error(client.post(f"/api/v1/{resource}", json={}), 422, "VALIDATION_ERROR")
    error(client.post(f"/api/v1/{resource}", data="{}", content_type="text/plain"), 415, "UNSUPPORTED_MEDIA_TYPE")
    error(client.get(f"/api/v1/{resource}/999"), 404, "RESOURCE_NOT_FOUND")
    assert snapshot(app) == before


@pytest.mark.parametrize("resource", ["warehouses", "items", "shelters"])
def test_storage_unavailable_and_html_pages_are_separate(tmp_path, resource):
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "missing.sqlite3"}).test_client()
    error(client.get(f"/api/v1/{resource}"), 503, "STORAGE_UNAVAILABLE")
    error(client.get(f"/api/v1/{resource}/1"), 503, "STORAGE_UNAVAILABLE")
    error(client.get("/api/v1/not-a-resource"), 404, "RESOURCE_NOT_FOUND")
    assert client.get("/not-a-page").mimetype == "text/html"


@pytest.mark.parametrize("table,column,resource", [("warehouses", "capacity_m3", "warehouses"), ("items", "unit_volume_m3", "items")])
def test_existing_excess_precision_is_not_silently_rounded(app, table, column, resource):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute(f"UPDATE {table} SET {column}=1.234 WHERE {resource[:-1]}_id=1")
    before = snapshot(app)
    error(app.test_client().get(f"/api/v1/{resource}/1"), 500, "DATA_INTEGRITY_ERROR")
    assert snapshot(app) == before


def test_real_javascript_api_flow_and_preserved_history(app):
    import shutil
    import subprocess
    from pathlib import Path
    from threading import Thread
    from werkzeug.serving import make_server

    seed_saved_result(app, app.test_client())
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.executemany("INSERT INTO warehouses(warehouse_id,name,facility_type,address) VALUES(?,?,'test','fictional')", [(i, f"W{i}") for i in range(2, 207)])
        c.executemany("INSERT INTO shelters(shelter_id,name,address) VALUES(?,?,'fictional')", [(i, f"S{i}") for i in range(2, 207)])
        c.executemany("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(?,?,'test','L',1,1)", [(i, f"I{i}") for i in range(3, 207)])
        c.executemany("INSERT INTO stock_thresholds VALUES(1,?,0)", [(i,) for i in range(2, 207)])
    before = snapshot(app)
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("p2-ui-api-flow.cjs")), f"http://127.0.0.1:{server.server_port}"], capture_output=True, text=True, encoding="utf-8", timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    after = snapshot(app)
    for table in before.keys() - {"warehouses", "stock_thresholds"}:
        assert after[table] == before[table]
    with app.app_context():
        c = db.get_db()
        assert c.execute("SELECT minimum_quantity FROM stock_thresholds WHERE warehouse_id=1 AND item_id=1").fetchone()[0] == 0
        assert db.check_database(c)["tables"] == 19


def test_invalid_existing_capacity_cannot_partially_commit_other_edits(app):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute("UPDATE warehouses SET capacity_m3=1.234 WHERE warehouse_id=1")
    before = snapshot(app)
    client = app.test_client()
    error(client.patch("/api/v1/warehouses/1", json={"name": "should roll back"}), 500, "DATA_INTEGRITY_ERROR")
    assert snapshot(app) == before
    # 所有者による明示訂正は可能。黙示的な丸めではない。
    assert client.patch("/api/v1/warehouses/1", json={"capacity_m3": "1.23"}).status_code == 200
