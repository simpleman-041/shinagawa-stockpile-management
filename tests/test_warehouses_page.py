"""倉庫一覧画面の入口テスト。"""

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "test.sqlite3"})
    return application.test_client()


def test_warehouse_page_renders_list_shell(client):
    response = client.get("/warehouses")

    assert response.status_code == 200
    assert "倉庫一覧" in response.get_data(as_text=True)
    assert "/static/js/warehouses.js" in response.get_data(as_text=True)
    assert "warehouse-loading" in response.get_data(as_text=True)
    assert "warehouse-empty" in response.get_data(as_text=True)
    assert "warehouse-error" in response.get_data(as_text=True)
