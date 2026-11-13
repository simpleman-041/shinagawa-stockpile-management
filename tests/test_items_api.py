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


@pytest.mark.parametrize("value", ["9007199254740993.01", "9007199254740993", "12345678901234567890.12"])
def test_volume_rejects_real_round_trip_loss(client, app, value):
    response = client.post("/api/v1/items", json={
        "name": "precision", "category": "test", "quantity_unit": "L",
        "is_divisible": True, "near_expiry_days": 1, "unit_volume_m3": value,
    })
    assert response.status_code == 422
    with app.app_context():
        assert db.get_db().execute("SELECT count(*) FROM items").fetchone()[0] == 0


@pytest.mark.parametrize("value, expected", [("0", "0.00"), ("1.23", "1.23"), ("9007199254740992", "9007199254740992.00")])
def test_volume_round_trip_is_exact(client, value, expected):
    response = client.post("/api/v1/items", json={
        "name": "precision", "category": "test", "quantity_unit": "L",
        "is_divisible": True, "near_expiry_days": 1, "unit_volume_m3": value,
    })
    assert response.status_code == 201
    item_id = response.json["data"]["item_id"]
    for _ in range(3):
        assert client.get(f"/api/v1/items/{item_id}").json["data"]["unit_volume_m3"] == expected
        updated = client.patch(f"/api/v1/items/{item_id}", json={"unit_volume_m3": expected})
        assert updated.status_code == 200
        assert updated.json["data"]["unit_volume_m3"] == expected


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


def _stored_tables(app):
    with app.app_context():
        connection = db.get_db()
        tables = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {
            row[0]: [tuple(value) for value in connection.execute(f'SELECT * FROM "{row[0]}" ORDER BY 1, 2')]
            for row in tables
        }


@pytest.mark.parametrize(
    "case,item_id,status,source",
    [
        ("no_stock", 1, 200, None),
        ("integers", 2, 200, None),
        ("fractional_stock", 3, 409, "stocks"),
        ("fractional_allocation", 2, 409, "stock_allocations"),
        ("fractional_threshold", 2, 409, "stock_thresholds"),
        ("unrelated_fractions", 2, 200, None),
    ],
)
def test_divisibility_change_checks_stock_allocation_and_threshold_atomically(
    app, client, seeded_items, case, item_id, status, source
):
    """DB設計TX10・AUD-03: 自品目の整数整合だけを確認し、拒否時は全表不変。"""
    with app.app_context(), db.transaction(db.get_db()) as connection:
        connection.execute("UPDATE items SET is_divisible = 1 WHERE item_id = 1")
        connection.execute("UPDATE warehouses SET allocation_mode = 'shared' WHERE warehouse_id = 1")
        connection.execute("INSERT INTO shelters (shelter_id, name, address) VALUES (1, '試験避難所', '試験住所')")
        connection.execute("INSERT INTO shelter_warehouses VALUES (1, 1)")
        connection.execute(
            "INSERT INTO stock_allocations VALUES (1, 1, ?)",
            (1.5 if case == "fractional_allocation" else 2,),
        )
        connection.execute(
            "INSERT INTO stock_thresholds VALUES (1, 2, ?)",
            (1.5 if case == "fractional_threshold" else 3,),
        )
        if case == "unrelated_fractions":
            connection.execute("INSERT INTO stock_allocations VALUES (2, 1, 0.5)")
            connection.execute("INSERT INTO stock_thresholds VALUES (1, 3, 0.5)")

    before = _stored_tables(app)
    response = client.patch(
        f"/api/v1/items/{item_id}", json={"is_divisible": False, "name": "変更後の品目"}
    )
    assert response.status_code == status, response.json
    after = _stored_tables(app)
    if status == 409:
        assert response.json["error"]["code"] == "UNIT_HAS_STOCK"
        assert response.json["error"]["details"]["source"] == source
        assert after == before
    else:
        assert response.json["data"]["is_divisible"] is False
        saved = client.get(f"/api/v1/items/{item_id}").json["data"]
        assert saved["is_divisible"] is False
        assert saved["name"] == "変更後の品目"
        assert {k: v for k, v in after.items() if k != "items"} == {
            k: v for k, v in before.items() if k != "items"
        }
        assert [row for row in after["items"] if row[0] != item_id] == [
            row for row in before["items"] if row[0] != item_id
        ]
