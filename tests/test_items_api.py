"""品目APIの契約テスト。"""

import pytest

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "test.sqlite3"})
    with application.app_context():
        db.init_db()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_items(app):
    with app.app_context():
        connection = db.get_db()
        with db.transaction(connection):
            connection.execute(
                """
                INSERT INTO warehouses
                    (warehouse_id, name, facility_type, address)
                VALUES (1, '倉庫', '避難所倉庫', '品川区')
                """
            )
            connection.executemany(
                """
                INSERT INTO items
                    (item_id, name, category, quantity_unit, unit_volume_m3,
                     is_divisible, near_expiry_days, registration_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "在庫なし", "食料", "食", 0.01, 0, 180, "active"),
                    (2, "在庫あり", "食料", "食", 0.01, 1, 180, "active"),
                    (3, "小数在庫あり", "液体", "L", 0.01, 1, 180, "active"),
                ],
            )
            connection.executemany(
                """
                INSERT INTO stocks
                    (stock_id, warehouse_id, item_id, location, quantity,
                     expiry_state, expiry_date)
                VALUES (?, 1, ?, '棚A', ?, 'none', NULL)
                """,
                [(1, 2, 10.0), (2, 3, 1.5)],
            )
    return app


def test_post_item_creates_active_item(client):
    response = client.post(
        "/api/v1/items",
        json={
            "name": "アルファ化米",
            "category": "食料",
            "quantity_unit": "食",
            "unit_volume_m3": "0.01",
            "is_divisible": False,
            "near_expiry_days": 180,
        },
    )

    assert response.status_code == 201
    assert response.headers["Location"].endswith("/api/v1/items/1")
    assert response.json["data"] == {
        "item_id": "1",
        "name": "アルファ化米",
        "category": "食料",
        "quantity_unit": "食",
        "unit_volume_m3": "0.01",
        "is_divisible": False,
        "near_expiry_days": 180,
        "registration_state": "active",
    }


def test_patch_item_allows_unit_change_without_stock(client, seeded_items):
    response = client.patch("/api/v1/items/1", json={"quantity_unit": "箱"})

    assert response.status_code == 200
    assert response.json["data"]["quantity_unit"] == "箱"


def test_patch_item_rejects_unit_change_with_stock(client, seeded_items):
    response = client.patch("/api/v1/items/2", json={"quantity_unit": "箱"})

    assert response.status_code == 409
    assert response.json["error"]["code"] == "UNIT_HAS_STOCK"


def test_patch_item_rejects_non_divisible_when_existing_quantity_is_fractional(
    client, seeded_items
):
    response = client.patch("/api/v1/items/3", json={"is_divisible": False})

    assert response.status_code == 409
    assert response.json["error"]["code"] == "UNIT_HAS_STOCK"


def test_closure_is_idempotent_and_reactivation_is_not_allowed(client, seeded_items):
    first = client.post("/api/v1/items/1/closure", json={})
    second = client.post("/api/v1/items/1/closure", json={})
    reopen = client.patch("/api/v1/items/1", json={"registration_state": "active"})

    assert first.status_code == 200
    assert first.json["data"]["registration_state"] == "closed"
    assert second.status_code == 200
    assert second.json == first.json
    assert reopen.status_code == 422


def test_closed_item_allows_normal_edit_but_not_state_edit(client, seeded_items):
    client.post("/api/v1/items/1/closure", json={})

    response = client.patch("/api/v1/items/1", json={"name": "終了済み品目"})

    assert response.status_code == 200
    assert response.json["data"]["name"] == "終了済み品目"
    assert response.json["data"]["registration_state"] == "closed"
