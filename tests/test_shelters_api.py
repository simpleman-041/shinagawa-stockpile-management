import pytest

from html.parser import HTMLParser

from app import db


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


class _Forms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = {}
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = attrs["id"]
            self.forms[self.current] = set()
        elif tag == "input" and self.current and "name" in attrs:
            self.forms[self.current].add(attrs["name"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def _snapshot(app):
    with app.app_context():
        connection = db.get_db()
        return {
            row[0]: [tuple(value) for value in connection.execute(f'SELECT * FROM "{row[0]}" ORDER BY 1, 2')]
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }


@pytest.mark.parametrize("has_targets", [False, True])
@pytest.mark.parametrize("field", ["name", "address"])
def test_edit_separates_normal_information_from_formal_targets(app, has_targets, field):
    """Q13・AUD-01: 正式目標あり／なしで名称・住所を独立に編集する。"""
    client = app.test_client()
    values = {"name": "旧名称", "address": "旧住所"}
    if has_targets:
        values.update(target_people=100, target_days=2)
    shelter = client.post("/api/v1/shelters", json=values).json["data"]
    sid = shelter["shelter_id"]
    page = client.get(f"/shelters/{sid}/edit")
    assert page.status_code == 200
    forms = _Forms()
    forms.feed(page.get_data(as_text=True))
    assert forms.forms["shelter-form"] == {"name", "address"}
    assert forms.forms["shelter-targets-form"] == {"target_people", "target_days"}

    response = client.patch(f"/api/v1/shelters/{sid}", json={field: "新しい値"})
    assert response.status_code == 200
    saved = client.get(f"/api/v1/shelters/{sid}").json["data"]
    assert saved == {**shelter, field: "新しい値"}

    updated = client.put(
        f"/api/v1/shelters/{sid}/targets", json={"target_people": 120, "target_days": 3}
    )
    assert updated.status_code == 200
    assert updated.json["data"] == {**saved, "target_people": 120, "target_days": 3}
    with app.app_context(), db.transaction(db.get_db()) as connection:
        connection.execute("INSERT INTO demand_groups (name) VALUES ('試験需要')")
    calculation = client.post("/api/v1/calculations", json={"shelter_id": str(sid)})
    assert calculation.status_code == 200
    assert calculation.json["data"]["header"]["target_people"] == 120
    assert calculation.json["data"]["header"]["target_days"] == 3


@pytest.mark.parametrize("failing", ["normal", "targets"])
def test_independent_shelter_save_failure_preserves_database(app, failing):
    client = app.test_client()
    sid = client.post(
        "/api/v1/shelters", json={"name": "旧名称", "address": "旧住所", "target_people": 100, "target_days": 2}
    ).json["data"]["shelter_id"]
    if failing == "targets":
        assert client.patch(f"/api/v1/shelters/{sid}", json={"name": "保存済み名称"}).status_code == 200
        method, path, payload = "PUT", f"/api/v1/shelters/{sid}/targets", {"target_people": 120, "target_days": 3}
    else:
        assert client.put(f"/api/v1/shelters/{sid}/targets", json={"target_people": 120, "target_days": 3}).status_code == 200
        method, path, payload = "PATCH", f"/api/v1/shelters/{sid}", {"name": "保存しない名称", "address": "保存しない住所"}
    with app.app_context():
        db.get_db().execute("CREATE TRIGGER fail_shelter_save BEFORE UPDATE ON shelters BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    before = _snapshot(app)
    assert client.open(path, method=method, json=payload).status_code == 500
    assert _snapshot(app) == before
