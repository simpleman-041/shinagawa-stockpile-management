import pytest

from app import create_app, db
from tools import seed_stockpile


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "test.sqlite3", "DEMO_MODE": True})
    with application.app_context():
        db.init_db()
    return application


def test_existing_warehouses_are_preserved_on_repeated_catalog_import(app):
    with app.app_context():
        connection = db.get_db()
        connection.execute(
            "INSERT INTO warehouses(name,facility_type,address,capacity_m3) VALUES(?,?,?,?)",
            ("大井1丁目備蓄倉庫", "既存データ", "大井1-15-13", 42),
        )
        existing = tuple(connection.execute("SELECT * FROM warehouses").fetchone())
        first = seed_stockpile.seed_database(connection)
        second = seed_stockpile.seed_database(connection)
        assert first["warehouses"] == 28
        assert first["preserved"] == ["大井１丁目備蓄倉庫"]
        assert second["warehouses"] == 0
        assert tuple(connection.execute("SELECT * FROM warehouses WHERE warehouse_id=1").fetchone()) == existing
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0
        with pytest.raises(ValueError, match="空の専用DB"):
            seed_stockpile.seed_database(connection, demo=True)


def test_demo_rollback_leaves_no_records(app, monkeypatch):
    def rejected(*args):
        raise RuntimeError("test failure during stock initialization")

    monkeypatch.setattr(seed_stockpile, "demo_stock", rejected)
    with app.app_context():
        connection = db.get_db()
        with pytest.raises(RuntimeError, match="test failure"):
            seed_stockpile.seed_database(connection, demo=True)
        for table in ("warehouses", "items", "operators", "shelters", "demand_groups", "stocks", "stock_movements"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_demo_uses_existing_views_and_recalculation(app):
    with app.app_context():
        connection = db.get_db()
        seeded = seed_stockpile.seed_database(connection, demo=True)
        assert (seeded["warehouses"], seeded["items"], seeded["stocks"]) == (30, 14, 8)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        warehouses = dict(connection.execute("SELECT name, warehouse_id FROM warehouses"))
        dedicated = warehouses["荏原備蓄倉庫"]
        capacity_sample = warehouses["演習用容量検証倉庫（架空）"]

    client = app.test_client()
    assert "演習用データ" in client.get("/warehouses").get_data(as_text=True)
    assert client.get(f"/warehouses/{dedicated}").status_code == 200
    assert client.get("/api/v1/warehouses?coordinates=known").json["page"]["total"] == 28
    assert client.get("/api/v1/items").json["page"]["total"] == 14
    assert client.get("/api/v1/stocks?expiry_status=expired").json["page"]["total"] == 1
    assert client.get("/api/v1/stocks?expiry_status=near").json["page"]["total"] == 1
    assert client.get(f"/api/v1/warehouses/{dedicated}/summary").json["data"]["capacity"]["state"] == "unavailable"
    assert client.get(f"/api/v1/warehouses/{capacity_sample}/summary").json["data"]["capacity"]["level"] == "over"

    initial = client.post("/api/v1/calculations", json={"shelter_id": "1"}).json["data"]
    groups = {group["group_name"]: group for group in initial["groups"]}
    assert groups["食料"]["included_quantity"] == "660.00"
    assert groups["飲料水"]["included_quantity"] == "550.00"
    water = next(stock for stock in client.get(f"/api/v1/stocks?warehouse_id={dedicated}").json["data"]
                 if stock["item_name"] == "ミネラルウォーター（飲料水）")
    stock_id = water["stock"]["stock_id"]
    assert client.post(f"/api/v1/stocks/{stock_id}/movements", json={
        "kind": "in", "quantity": "50", "operator_id": "1",
    }).status_code == 201
    updated = client.post("/api/v1/calculations", json={"shelter_id": "1"}).json["data"]
    assert updated["header"]["min_people"] == 100
    with app.app_context():
        connection = db.get_db()
        assert seed_stockpile.seed_database(connection, demo=True)["already_seeded"]
        assert connection.execute("SELECT quantity FROM stocks WHERE stock_id=?", (stock_id,)).fetchone()[0] == 500
        assert connection.execute("SELECT count(*) FROM stock_movements").fetchone()[0] == 8
