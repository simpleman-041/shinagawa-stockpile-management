"""承認済みの独立条件画面とP1の実JS→HTTP→SQLite連携を確認する。"""
from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "p1-ui.sqlite3"})
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO operators VALUES (1, 'Fictional operator')")
            c.execute("INSERT INTO shelters VALUES (1, 'Test shelter', 'Fictional address', 50, 1, 'complete')")
            c.execute("INSERT INTO warehouses (warehouse_id,name,facility_type,address,allocation_mode) VALUES (1,'Test warehouse','Test','Fictional','dedicated')")
            c.execute("INSERT INTO shelter_warehouses VALUES (1,1)")
            c.executemany(
                "INSERT INTO items (item_id,name,category,quantity_unit,is_divisible,near_expiry_days,registration_state) VALUES (?,?,'Test','L',1,7,?)",
                [(1, "Water", "active"), (2, "Old water", "closed"), (3, "Empty item", "active")],
            )
            c.executemany(
                "INSERT INTO stocks (stock_id,warehouse_id,item_id,location,quantity,expiry_state) VALUES (?,1,?,'Shelf',?,'none')",
                [(1, 1, 600), (2, 2, 0)],
            )
    return application


def snapshot(app, tables):
    with app.app_context():
        return {name: [tuple(row) for row in db.get_db().execute(f'SELECT * FROM "{name}" ORDER BY 1,2')] for name in tables}


def test_conditions_page_navigation_and_get_do_not_modify_database(app):
    with app.app_context():
        tables = [row[0] for row in db.get_db().execute("SELECT name FROM sqlite_schema WHERE type='table'")]
    before = snapshot(app, tables)
    client = app.test_client()
    page = client.get("/calculation-conditions")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for form in ("group-create-form", "group-edit-form", "membership-form"):
        assert f'id="{form}"' in html
    assert "js/calculation-conditions.js" in html
    for url in ("/calculations", "/shelters"):
        assert 'href="/calculation-conditions"' in client.get(url).get_data(as_text=True)
    assert snapshot(app, tables) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="実JSとHTTPの連携確認にはNode.jsが必要")
def test_p1_screen_scripts_through_real_api_and_sqlite_preserve_saved_results(app):
    """ブラウザの描画ではなく、DOM代替上の実JSと実API/DBの統合検証。"""
    preserved = ("operators", "warehouses", "stocks", "stock_allocations", "stock_thresholds", "stock_movements", "stock_state_events", "stock_expiry_changes")
    before = snapshot(app, preserved)
    with app.app_context():
        schema_before = [tuple(row) for row in db.get_db().execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("p1-ui-api-flow.cjs")), f"http://127.0.0.1:{server.server_port}"],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert snapshot(app, preserved) == before
    with app.app_context():
        connection = db.get_db()
        assert [tuple(row) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")] == schema_before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.check_database(connection)["tables"] == 19
        assert connection.execute("SELECT count(*) FROM calculation_runs").fetchone()[0] == 1
