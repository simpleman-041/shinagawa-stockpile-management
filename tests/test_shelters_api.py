import pytest


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE", str(tmp_path / "test.sqlite"))
    from app import create_app

    application = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite")})
    with application.app_context():
        from app.db import init_db

        init_db()
    return application


def test_create_shelter_defaults_targets_and_state(app):
    client = app.test_client()
    response = client.post("/api/v1/shelters", json={"name": "品川避難所", "address": "品川区"})
    assert response.status_code == 201
    assert response.json["data"]["target_people"] is None
    assert response.json["data"]["target_days"] is None
    assert response.json["data"]["setup_state"] == "editing"


def test_create_shelter_rejects_only_one_target(app):
    response = app.test_client().post(
        "/api/v1/shelters", json={"name": "品川避難所", "address": "品川区", "target_people": 10}
    )
    assert response.status_code == 422


def test_patch_and_update_targets(app):
    client = app.test_client()
    created = client.post("/api/v1/shelters", json={"name": "旧名称", "address": "品川区"}).json["data"]
    shelter_id = created["shelter_id"]

    patched = client.patch(f"/api/v1/shelters/{shelter_id}", json={"name": "新名称"})
    assert patched.status_code == 200
    assert patched.json["data"]["name"] == "新名称"

    targets = client.put(
        f"/api/v1/shelters/{shelter_id}/targets",
        json={"target_people": 100, "target_days": 3},
    )
    assert targets.status_code == 200
    assert targets.json["data"]["target_people"] == 100
    assert targets.json["data"]["target_days"] == 3


def test_setup_state_can_be_changed(app):
    client = app.test_client()
    shelter_id = client.post("/api/v1/shelters", json={"name": "避難所", "address": "住所"}).json["data"]["shelter_id"]
    response = client.put(
        f"/api/v1/shelters/{shelter_id}/warehouse-setup",
        json={"setup_state": "complete"},
    )
    assert response.status_code == 200
    assert response.json["data"]["setup_state"] == "complete"
