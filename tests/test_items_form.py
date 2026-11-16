"""ITEM 01/02の実テンプレートと実JS→HTTP→隔離DBの検証。"""
from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "items-form.sqlite3"})
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as connection:
            connection.execute(
                "INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,near_expiry_days) "
                "VALUES(1,'既存の架空品目','試験用','本',0,180)"
            )
    return application


def snapshot(app, *, include_items=True):
    with app.app_context():
        connection = db.get_db()
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        return {
            name: [tuple(row) for row in connection.execute(f'SELECT * FROM "{name}" ORDER BY 1')]
            for name in tables if include_items or name != "items"
        }


def test_create_and_edit_recovery_controls_are_rendered_without_writing(app):
    before = snapshot(app)
    client = app.test_client()
    for url, edit in [("/items/new", False), ("/items/1/edit", True)]:
        page = client.get(url)
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        for identifier in ("item-form-submit", "item-form-status", "item-form-recovery", "item-form-resume"):
            assert f'id="{identifier}"' in html
        assert ('id="item-form-recheck"' in html) == edit
        assert ('target="_blank" rel="noopener"' in html) == (not edit)
        assert "保存できている場合は再操作は不要" in html
        if not edit:
            assert "今回の登録成功とは断定できません" in html
    assert snapshot(app) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="実JSとHTTPの連携確認にはNode.jsが必要")
def test_form_single_insert_and_uncertain_results_through_real_http(app):
    before = snapshot(app, include_items=False)
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("items-form-api-flow.cjs")), f"http://127.0.0.1:{server.server_port}"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert snapshot(app, include_items=False) == before
    with app.app_context():
        connection = db.get_db()
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 4
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
