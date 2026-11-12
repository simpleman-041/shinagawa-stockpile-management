"""API 1.0 T09/11/12/16〜22、要件V07〜09。値はすべて架空の試験条件。"""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app import create_app, db
from app.services import calculations as service


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "calculation.sqlite3"})
    monkeypatch.setattr(service, "now", lambda: datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc))
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO operators VALUES(1,'架空担当者')")
            c.execute("INSERT INTO shelters(shelter_id,name,address,target_people,target_days,setup_state) VALUES(1,'架空避難所','架空住所',100,2,'complete'),(2,'別避難所','架空住所',100,2,'complete')")
            c.execute("INSERT INTO demand_groups VALUES(1,'試験用飲料水','L',1,3,'架空の試験基準','test-v1','試験専用')")
            c.execute("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(1,'試験飲料','水','L',1,7)")
            c.execute("INSERT INTO item_conversions VALUES(1,1,100,'架空換算','test-v1','試験専用')")
            c.execute("INSERT INTO warehouses(warehouse_id,name,facility_type,address,allocation_mode) VALUES(1,'試験専用倉庫','試験','架空住所','dedicated')")
            c.execute("INSERT INTO shelter_warehouses VALUES(1,1)")
            c.execute("INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state) VALUES(1,1,1,'棚',600,'none')")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def change(app, sql, args=()):
    with app.app_context(), db.transaction(db.get_db()) as c:
        c.execute(sql, args)


def stored(app):
    with app.app_context():
        c = db.get_db()
        return {r[0]: [tuple(v) for v in c.execute(f'SELECT * FROM "{r[0]}" ORDER BY 1')] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def calculate(client, **values):
    return client.post("/api/v1/calculations", json={"shelter_id": "1", **values})


def save(client, token, **values):
    return client.post("/api/v1/calculation-runs", json={"calculation_token": token, **values})


@pytest.mark.parametrize("quantity,shortage,rate,people,days", [(600,"0.00","100.0",100,2), (300,"300.00","50.0",50,1), (450,"150.00","75.0",75,1), (900,"0.00","150.0",150,3), (0,"600.00","0.0",0,0)])
def test_requirement_examples_and_no_implicit_save(app, client, quantity, shortage, rate, people, days):
    change(app, "UPDATE stocks SET quantity=?", (quantity,))
    before = stored(app)
    response = calculate(client)
    assert response.status_code == 200, response.json
    p = response.json["data"]
    g = p["groups"][0]
    assert g["required_quantity"] == "600.00"
    assert (g["shortage_quantity"],g["coverage_rate"],g["people"],g["days"]) == (shortage,rate,people,days)
    assert g["limits_people"] and g["limits_days"]
    assert p["header"]["base_date"] == "2026-11-12"
    assert p["header"]["formula_version"] == "unfire-20261101-r1"
    assert client.get("/api/v1/calculations/" + p["calculation_token"]).json["data"] == p
    assert stored(app) == before


def test_temporary_target_does_not_change_formal_target(app, client):
    p = calculate(client, target_people=50, target_days=3).json["data"]
    assert p["groups"][0]["required_quantity"] == "450.00"
    assert p["header"]["target_people"] == 50
    assert stored(app)["shelters"][0][3:5] == (100, 2)


@pytest.mark.parametrize("state,date_value,reason,amount,warning,period", [
    ("dated","2026-11-11","expired","0.00",False,False),
    ("dated","2026-11-12","dedicated","600.00",False,True),
    ("dated","2026-11-13","dedicated","600.00",False,True),
    ("dated","2026-11-14","dedicated","600.00",False,False),
    ("unconfirmed",None,"dedicated","600.00",True,False),
    ("none",None,"dedicated","600.00",False,False),
])
def test_jst_expiry_and_period_inclusive(app, client, state, date_value, reason, amount, warning, period):
    change(app, "UPDATE stocks SET expiry_state=?,expiry_date=?", (state,date_value))
    p = calculate(client).json["data"]
    s = p["stocks"][0]
    assert (s["selection_reason"], s["included_quantity"], s["unknown_expiry_warning"], s["expires_in_period"]) == (reason,amount,warning,period)
    assert p["header"]["has_unknown_expiry"] is warning
    assert p["header"]["result_state"] == "computed"


def test_shared_only_explicit_selected_allocation_and_zero(app, client):
    change(app, "UPDATE warehouses SET allocation_mode='shared'")
    change(app, "INSERT INTO shelter_warehouses VALUES(2,1)")
    change(app, "INSERT INTO stock_allocations VALUES(1,2,100)")
    p = calculate(client).json["data"]
    assert p["stocks"][0]["selection_reason"] == "unallocated"
    assert p["groups"][0]["included_quantity"] == "0.00"
    change(app, "INSERT INTO stock_allocations VALUES(1,1,450)")
    p = calculate(client).json["data"]
    assert p["groups"][0]["included_quantity"] == "450.00"
    assert p["stocks"][0]["allocated_total"] == "550.00"
    assert len(p["warehouse_links"]) == 2
    assert calculate(client, shelter_id="2").json["data"]["groups"][0]["included_quantity"] == "100.00"


def test_closed_items_and_old_new_explicit_conversion_no_duplicate_join(app, client):
    change(app, "UPDATE items SET registration_state='closed'")
    change(app, "INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(2,'試験旧箱','水','箱',0,7)")
    change(app, "INSERT INTO item_conversions VALUES(2,1,125,'試験','v1','試験')")
    change(app, "INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state) VALUES(10,1,2,'棚2',2,'none')")
    p = calculate(client).json["data"]
    assert p["groups"][0]["included_quantity"] == "602.50"
    assert p["items"][0]["registration_state"] == "closed"
    assert p["items"][1]["factor_x100"] == "125"
    assert [s["stock_id"] for s in p["stocks"]] == ["1","10"]


def test_deleted_merged_and_unrelated_not_in_snapshot(app, client):
    change(app, "INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state,state) VALUES(2,1,1,'削除棚',100,'none','deleted')")
    change(app, "UPDATE stocks SET quantity=0,state='merged',merged_into_stock_id=1,merged_at='2026-11-11T00:00:00.000Z',merged_by=1 WHERE stock_id=2")
    p = calculate(client).json["data"]
    assert len(p["stocks"]) == 1
    assert p["groups"][0]["included_quantity"] == "600.00"


@pytest.mark.parametrize("sql,code", [
    ("UPDATE shelters SET setup_state='editing' WHERE shelter_id=1", "SETUP_EDITING"),
    ("UPDATE demand_groups SET daily_usage=NULL", "DAILY_USAGE_MISSING"),
    ("UPDATE demand_groups SET calculation_unit=NULL", "GROUP_UNIT_MISSING"),
    ("UPDATE demand_groups SET is_divisible=NULL", "GROUP_DIVISIBILITY_MISSING"),
    ("UPDATE demand_groups SET source_text=NULL", "USAGE_SOURCE_MISSING"),
    ("UPDATE item_conversions SET factor_x100=NULL", "CONVERSION_FACTOR_MISSING"),
    ("UPDATE item_conversions SET version_or_date=NULL", "CONVERSION_SOURCE_MISSING"),
    ("DELETE FROM item_conversions", "ITEM_CONVERSION_MISSING"),
    ("UPDATE warehouses SET allocation_mode=NULL", "WAREHOUSE_MODE_MISSING"),
    ("INSERT INTO shelter_warehouses VALUES(2,1)", "DEDICATED_LINK_COUNT_INVALID"),
    ("UPDATE stocks SET state='deleted'", "STOCK_UNREGISTERED"),
])
def test_missing_information_200_null_metrics_and_save_reasons(app, client, sql, code):
    change(app, sql)
    response = calculate(client)
    assert response.status_code == 200, response.json
    p = response.json["data"]
    assert p["header"]["result_state"] == "unavailable"
    assert any(i["code"] == code for i in p["issues"])
    g = p["groups"][0]
    assert all(g[k] is None for k in service.METRICS)
    assert not g["limits_people"] and not g["limits_days"]
    r = save(client, p["calculation_token"])
    assert r.status_code == 201, r.json
    assert code in r.json["data"]["run"]["unavailable_reason"]


def test_no_link_is_normal_zero_but_dedicated_unregistered_is_not(app, client):
    change(app, "DELETE FROM shelter_warehouses")
    p = calculate(client).json["data"]
    assert p["header"]["result_state"] == "computed"
    assert p["groups"][0]["included_quantity"] == "0.00"
    assert p["warehouses"] == p["stocks"] == []


def test_partial_suppresses_all_limits_and_preserves_reference(app, client):
    change(app, "INSERT INTO demand_groups VALUES(2,'食料',NULL,NULL,NULL,NULL,NULL,NULL)")
    p = calculate(client).json["data"]
    assert p["header"]["result_state"] == "partial"
    assert p["header"]["min_people"] is p["header"]["min_days"] is None
    assert p["groups"][0]["reference_quantity"] == "600.00"
    assert all(not g["limits_people"] and not g["limits_days"] for g in p["groups"])
    assert save(client, p["calculation_token"]).status_code == 201


def test_all_tied_limiting_groups(app, client):
    change(app, "INSERT INTO demand_groups VALUES(2,'食料','食',0,3,'試験','v1','試験')")
    change(app, "INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(2,'試験食料','食料','食',0,7)")
    change(app, "INSERT INTO item_conversions VALUES(2,2,100,'試験','v1','試験')")
    change(app, "INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state) VALUES(2,1,2,'棚2',600,'none')")
    p = calculate(client).json["data"]
    assert p["header"]["result_state"] == "computed"
    assert all(g["limits_people"] and g["limits_days"] for g in p["groups"])


@pytest.mark.parametrize("quantity,factor,expected", [(0.83,150,"1.25"),(0.40,311,"1.24")])
def test_half_up_conversion(app, client, quantity, factor, expected):
    # 0.83×1.50=1.245、0.40×3.11=1.244。入力はどちらも許可精度内。
    change(app, "UPDATE stocks SET quantity=?", (quantity,))
    change(app, "UPDATE item_conversions SET factor_x100=?", (factor,))
    p = calculate(client).json["data"]
    assert p["stocks"][0]["converted_quantity"] == expected


def test_final_quotient_floor_not_rounded_and_display_rate_not_fulfilment(app, client):
    change(app, "UPDATE stocks SET quantity=599.99")
    g = calculate(client).json["data"]["groups"][0]
    assert (g["coverage_rate"],g["shortage_quantity"],g["people"],g["days"]) == ("100.0","0.01",99,1)


def test_rounding_denominator_zero_from_legacy_data(app, client):
    change(app, "UPDATE demand_groups SET daily_usage=0.001")
    p = calculate(client).json["data"]
    assert p["groups"][0]["result_state"] == "unavailable"
    assert "ROUNDED_DENOMINATOR_ZERO" in p["header"]["unavailable_reason"]


def test_invalid_allocation_overage_500_and_link_conflict_as_result(app, client):
    change(app, "INSERT INTO stock_allocations VALUES(1,2,100)")
    p = calculate(client).json["data"]
    assert p["stocks"][0]["selection_reason"] == "unresolved"
    assert p["groups"][0]["reference_quantity"] is None
    assert "ALLOCATION_LINK_INVALID" in p["header"]["unavailable_reason"]
    change(app, "UPDATE stock_allocations SET quantity=601")
    before = stored(app)
    r = calculate(client)
    assert r.status_code == 500 and r.json["error"]["code"] == "DATA_INTEGRITY_ERROR"
    assert stored(app) == before


def test_frozen_saved_after_changes_and_midnight_no_master_rebuild(app, client, monkeypatch):
    p = calculate(client).json["data"]
    change(app, "UPDATE stocks SET quantity=1")
    change(app, "UPDATE shelters SET name='新しい避難所',target_people=10,setup_state='editing'")
    change(app, "UPDATE warehouses SET name='新しい倉庫'")
    change(app, "UPDATE items SET name='新しい品目'")
    change(app, "UPDATE demand_groups SET name='新しい需要',daily_usage=10")
    change(app, "UPDATE item_conversions SET factor_x100=200")
    monkeypatch.setattr(service,"now", lambda: datetime(2026,11,13,tzinfo=timezone.utc))
    r = save(client, p["calculation_token"])
    assert r.status_code == 201, r.json
    s = r.json["data"]
    assert s["run"]["shelter_name"] == "架空避難所"
    assert s["run"]["saved_at"] == "2026-11-13T00:00:00.000Z"
    assert s["run"]["calculated_at"] == "2026-11-11T15:00:00.000Z"
    for key in service.TABLES:
        assert [{k:v for k,v in row.items() if k != "run_id"} for row in s[key]] == p[key]
    assert client.get(r.headers["Location"]).json["data"] == s
    assert client.get("/api/v1/calculations/" + p["calculation_token"]).json["data"] == p


def test_save_idempotence_and_correction_reverse_links(app, client):
    token = calculate(client).json["data"]["calculation_token"]
    first = save(client, token)
    assert first.status_code == 201
    assert save(client, token).status_code == 200
    assert save(client, token, correction_of_run_id="1").status_code == 409
    other = calculate(client, shelter_id="2").json["data"]["calculation_token"]
    second = save(client, other, correction_of_run_id="1")
    assert second.status_code == 201  # 別避難所の訂正元も契約上許可。
    assert second.json["data"]["run"]["correction_of_run_id"] == "1"
    assert client.get(first.headers["Location"]).json["data"]["correction_run_ids"] == ["2"]
    assert client.get("/api/v1/calculation-runs").json["page"]["total"] == 2


def test_same_token_concurrent_saves_only_insert_once(app, client):
    token = calculate(client).json["data"]["calculation_token"]
    def run(_):
        with app.test_client() as c:
            return save(c, token).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == [200,201]
    assert client.get("/api/v1/calculation-runs").json["page"]["total"] == 1


@pytest.mark.parametrize("table", list(service.TABLES.values()) + ["calculation_runs"])
def test_each_save_stage_failure_rolls_back_and_can_retry(app, client, table):
    token = calculate(client).json["data"]["calculation_token"]
    change(app, f"CREATE TRIGGER fail_save BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'test failure'); END")
    before = stored(app)
    r = save(client, token)
    assert r.status_code == 500 and r.json["error"]["code"] == "SNAPSHOT_INVALID"
    assert stored(app) == before
    change(app, "DROP TRIGGER fail_save")
    assert save(client, token).status_code == 201


def test_commit_failure_rolls_back_all_six_tables(app, client):
    token = calculate(client).json["data"]["calculation_token"]
    change(app,"CREATE TABLE fault(operator_id INTEGER REFERENCES operators(operator_id) DEFERRABLE INITIALLY DEFERRED)")
    change(app,"CREATE TRIGGER fail_commit AFTER INSERT ON calculation_runs BEGIN INSERT INTO fault VALUES(999); END")
    before = stored(app)
    assert save(client,token).status_code == 500
    assert stored(app) == before
    change(app,"DROP TRIGGER fail_commit")
    assert save(client,token).status_code == 201
    with app.app_context():
        assert db.get_db().execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_corrupt_frozen_payload_rejected_before_insert(app, client):
    token = calculate(client).json["data"]["calculation_token"]
    entry = app.extensions["calculations"]["entries"][token]
    payload = json.loads(entry["frozen"].preview)
    payload["stocks"] = []
    entry["frozen"] = replace(entry["frozen"],preview=json.dumps(payload))
    before = stored(app)
    assert save(client,token).json["error"]["code"] == "SNAPSHOT_INVALID"
    assert stored(app) == before


def test_history_filters_calculated_time_not_saved_and_empty(app, client, monkeypatch):
    p = calculate(client).json["data"]
    monkeypatch.setattr(service,"now",lambda: datetime(2026,11,20,tzinfo=timezone.utc))
    save(client,p["calculation_token"])
    r = client.get("/api/v1/calculation-runs?from=2026-11-11T15:00:00.000Z&to=2026-11-12T00:00:00.000Z&shelter_id=1&result_state=computed&limit=1&offset=0")
    assert r.status_code == 200 and r.json["page"] == {"total":1,"limit":1,"offset":0}
    assert client.get("/api/v1/calculation-runs?to=2026-11-11T15:00:00.000Z").json["data"] == []
    assert client.get("/api/v1/calculation-runs?shelter_id=2").json["data"] == []


@pytest.mark.parametrize("values,code", [
    ({"base_date":"2026-11-12"},"UNKNOWN_FIELD"),({"target_people":1},"VALIDATION_ERROR"),
    ({"target_people":True,"target_days":2},"VALIDATION_ERROR"),({"target_people":"100","target_days":2},"VALIDATION_ERROR"),
    ({"target_people":0,"target_days":2},"VALIDATION_ERROR"),({"target_people":1.5,"target_days":2},"VALIDATION_ERROR"),
    ({"target_people":9007199254740992,"target_days":2},"NUMBER_NOT_REPRESENTABLE"),
    ({"target_people":1,"target_days":9007199254740991},"NUMBER_NOT_REPRESENTABLE"),
    ({"shelter_id":"999"},"REFERENCE_NOT_FOUND"),({"shelter_id":1},"VALIDATION_ERROR"),
])
def test_input_rejected_without_db_change(app, client, values, code):
    before = stored(app)
    r = calculate(client, **values)
    assert r.status_code == 422 and r.json["error"]["code"] == code
    assert stored(app) == before


def test_missing_target_lost_token_and_invalid_correction(app, client):
    change(app,"UPDATE shelters SET target_people=NULL,target_days=NULL")
    assert calculate(client).json["error"]["code"] == "TARGET_NOT_SET"
    token = calculate(client,target_people=100,target_days=2).json["data"]["calculation_token"]
    assert save(client,token,correction_of_run_id="999").json["error"]["code"] == "INVALID_CORRECTION"
    assert client.get("/api/v1/calculations/lost").status_code == 409
    assert save(client,"lost").status_code == 409


def test_empty_groups_are_rejected(tmp_path):
    application = create_app({"TESTING":True,"DATABASE":tmp_path / "empty.sqlite3"})
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO shelters(shelter_id,name,address,target_people,target_days) VALUES(1,'試験','試験',100,2)")
    assert calculate(application.test_client()).json["error"]["code"] == "CALCULATION_GROUPS_EMPTY"


@pytest.mark.parametrize("data", ['[]','null','{"shelter_id":"1","shelter_id":"1"}','{bad'])
def test_invalid_json(client,data):
    assert client.post("/api/v1/calculations",data=data,content_type="application/json").status_code == 400


@pytest.mark.parametrize("path", ["/api/v1/calculation-runs?from=2026-02-30T00:00:00.000Z", "/api/v1/calculation-runs?from=2026-11-12T00:00:00.000Z&to=2026-11-11T00:00:00.000Z", "/api/v1/calculation-runs?result_state=bad", "/api/v1/calculation-runs?limit=1&limit=2", "/api/v1/calculations/lost?unknown=1"])
def test_query_validation(client,path):
    assert client.get(path).status_code == 422


def test_http_errors(client):
    assert client.post("/api/v1/calculations",data="{}").status_code == 415
    r = client.delete("/api/v1/calculations")
    assert r.status_code == 405 and "POST" in r.headers["Allow"] and r.is_json
    assert client.get("/api/v1/calculation-runs/999").status_code == 404
    assert client.get("/api/v1/calculation-runs/1/unknown").is_json
    assert client.get("/api/v1/calculation-runs",data="{}").status_code == 400


def test_zero_unconfirmed_is_not_provisional_and_empty_items_are_snapshotted(app, client):
    change(app, "UPDATE stocks SET quantity=0,expiry_state='unconfirmed'")
    change(app, "INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(2,'在庫のない関連品目','水','L',1,7)")
    change(app, "INSERT INTO item_conversions VALUES(2,1,100,'試験','v1','試験')")
    p = calculate(client).json["data"]
    assert not p["header"]["has_unknown_expiry"]
    assert not p["stocks"][0]["unknown_expiry_warning"]
    assert len(p["items"]) == 2


def test_reference_includes_only_confirmed_warehouse_portion(app, client):
    change(app, "INSERT INTO warehouses(warehouse_id,name,facility_type,address,allocation_mode) VALUES(2,'未設定倉庫','試験','試験',NULL)")
    change(app, "INSERT INTO shelter_warehouses VALUES(1,2)")
    change(app, "INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state) VALUES(2,2,1,'棚2',900,'none')")
    p = calculate(client).json["data"]
    assert p["groups"][0]["reference_quantity"] == "600.00"
    assert p["groups"][0]["included_quantity"] is None
    assert p["stocks"][1]["selection_reason"] == "unresolved"


def test_shared_invalid_link_without_any_confirmed_quantity_is_null(app, client):
    change(app, "UPDATE warehouses SET allocation_mode='shared'")
    change(app, "INSERT INTO stock_allocations VALUES(1,2,100)")  # 避難所2への対応がない。
    p = calculate(client).json["data"]
    assert p["groups"][0]["reference_quantity"] is None
    assert p["stocks"][0]["selection_reason"] == "unresolved"


def test_clock_reversal_fails_without_altering_calculated_time(app, client, monkeypatch):
    p = calculate(client).json["data"]
    before = stored(app)
    monkeypatch.setattr(service,"now",lambda:datetime(2026,11,10,tzinfo=timezone.utc))
    r = save(client,p["calculation_token"])
    assert r.status_code == 500 and r.json["error"]["code"] == "SNAPSHOT_INVALID"
    assert stored(app) == before


def test_storage_lock_503_and_token_retry_after_release(app, client, monkeypatch):
    token = calculate(client).json["data"]["calculation_token"]
    original = db.connect_db
    def connect(path):
        c = original(path)
        c.execute("PRAGMA busy_timeout=1")
        return c
    monkeypatch.setattr(db,"connect_db",connect)
    before = stored(app)
    lock = original(app.config["DATABASE"])
    try:
        lock.execute("BEGIN IMMEDIATE")
        r = save(client,token)
        assert r.status_code == 503
        assert r.json["error"]["code"] == "STORAGE_BUSY" and r.json["error"]["retryable"]
    finally:
        lock.rollback(); lock.close()
    assert stored(app) == before
    assert save(client,token).status_code == 201


def test_capture_consistent_read_across_independent_connection_change(app):
    with app.app_context():
        c = db.get_db()
        c.execute("PRAGMA journal_mode=WAL")
        class Interleaved:
            changed = False
            def __getattr__(self,key): return getattr(c,key)
            def execute(self,sql,args=()):
                if sql.startswith("SELECT i.item_id") and not self.changed:
                    self.changed = True
                    other = db.connect_db(app.config["DATABASE"])
                    try:
                        with db.transaction(other):
                            other.execute("UPDATE stocks SET quantity=1")
                    finally: other.close()
                return c.execute(sql,args)
        frozen = service.calculate(Interleaved(),1)
        assert json.loads(frozen.preview)["groups"][0]["included_quantity"] == "600.00"
        assert c.execute("SELECT quantity FROM stocks").fetchone()[0] == 1


def test_saved_six_tables_remain_immutable_and_sealed(app,client):
    token = calculate(client).json["data"]["calculation_token"]
    assert save(client,token).status_code == 201
    before = stored(app)
    with app.app_context():
        for table in ["calculation_runs", *service.TABLES.values()]:
            for sql in (f"UPDATE {table} SET run_id=run_id WHERE run_id=1", f"DELETE FROM {table} WHERE run_id=1"):
                with pytest.raises(sqlite3.IntegrityError), db.transaction(db.get_db()) as c:
                    c.execute(sql)
        with pytest.raises(sqlite3.IntegrityError), db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO calculation_warehouse_snapshots VALUES(1,2,'追加禁止','shared')")
    assert stored(app) == before


def test_calculation_page_entry_and_saved_page_404(client):
    assert client.get("/calculations?shelter_id=1").status_code == 200
    assert "calculation-form" in client.get("/calculations").text
    assert "history-form" in client.get("/calculation-runs").text
    assert client.get("/calculation-runs/999").status_code == 404
    token = calculate(client).json["data"]["calculation_token"]
    save(client,token)
    assert 'data-run-id="1"' in client.get("/calculation-runs/1").text
