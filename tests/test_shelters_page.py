"""避難所一覧・フォーム画面の入口確認。"""

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "test.sqlite3"})
    return application.test_client()


def test_shelters_page_renders_list_shell(client):
    response = client.get("/shelters")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "避難所一覧" in html
    assert "/static/js/shelters.js" in html
    assert 'id="shelter-loading"' in html
    assert 'id="shelter-empty"' in html
    assert 'id="shelter-error"' in html


def test_shelter_form_pages_render_field_error_descriptions(client):
    create = client.get("/shelters/new")
    assert create.status_code == 200
    assert 'aria-describedby="shelter-form-field-error-name"' in create.text
    assert 'id="shelter-form-field-error-target_people"' in create.text
