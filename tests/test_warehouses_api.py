"""倉庫一覧APIの契約テスト。"""

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
def seeded_database(app):
    with app.app_context():
        connection = db.get_db()
        with db.transaction(connection):
            connection.executemany(
                """
                INSERT INTO warehouses
                    (warehouse_id, name, facility_type, address, latitude, longitude, capacity_m3, allocation_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "第一倉庫", "避難所倉庫", "品川区北品川1-1", 35.62, 139.74, 100.0, "shared"),
                    (2, "第二倉庫", "集中備蓄倉庫", "品川区南品川2-2", None, None, None, None),
                    (3, "第三倉庫", "分散備蓄倉庫", "大田区東六郷3-3", 35.55, 139.72, 50.0, "dedicated"),
                ],
            )
    return app


def test_get_warehouses_returns_rows_and_page(client, seeded_database):
    response = client.get("/api/v1/warehouses")

    assert response.status_code == 200
    assert response.json == {
        "data": [
            {
                "warehouse_id": 1,
                "name": "第一倉庫",
                "facility_type": "避難所倉庫",
                "address": "品川区北品川1-1",
                "latitude": 35.62,
                "longitude": 139.74,
                "capacity_m3": 100.0,
                "allocation_mode": "shared",
            },
            {
                "warehouse_id": 2,
                "name": "第二倉庫",
                "facility_type": "集中備蓄倉庫",
                "address": "品川区南品川2-2",
                "latitude": None,
                "longitude": None,
                "capacity_m3": None,
                "allocation_mode": None,
            },
            {
                "warehouse_id": 3,
                "name": "第三倉庫",
                "facility_type": "分散備蓄倉庫",
                "address": "大田区東六郷3-3",
                "latitude": 35.55,
                "longitude": 139.72,
                "capacity_m3": 50.0,
                "allocation_mode": "dedicated",
            },
        ],
        "page": {"limit": 50, "offset": 0, "total": 3},
    }


def test_get_warehouses_supports_search_coordinates_and_paging(client, seeded_database):
    response = client.get(
        "/api/v1/warehouses?q=倉庫&coordinates=known&limit=1&offset=1"
    )

    assert response.status_code == 200
    assert response.json["page"] == {"limit": 1, "offset": 1, "total": 2}
    assert response.json["data"][0]["warehouse_id"] == 3


def test_get_warehouses_returns_empty_success(client, seeded_database):
    response = client.get("/api/v1/warehouses?q=存在しない")

    assert response.status_code == 200
    assert response.json == {
        "data": [],
        "page": {"limit": 50, "offset": 0, "total": 0},
    }


def test_post_warehouse_creates_row_and_returns_location(client):
    response = client.post(
        "/api/v1/warehouses",
        json={
            "name": "新倉庫",
            "facility_type": "避難所倉庫",
            "address": "品川区東品川1-1",
            "latitude": 35.6,
            "longitude": 139.75,
            "capacity_m3": 120.5,
        },
    )

    assert response.status_code == 201
    assert response.headers["Location"].endswith("/api/v1/warehouses/1")
    assert response.json["data"] == {
        "warehouse_id": 1,
        "name": "新倉庫",
        "facility_type": "避難所倉庫",
        "address": "品川区東品川1-1",
        "latitude": 35.6,
        "longitude": 139.75,
        "capacity_m3": 120.5,
        "allocation_mode": None,
    }


def test_post_warehouse_rejects_one_coordinate(client):
    response = client.post(
        "/api/v1/warehouses",
        json={
            "name": "新倉庫",
            "facility_type": "避難所倉庫",
            "address": "品川区東品川1-1",
            "latitude": 35.6,
        },
    )

    assert response.status_code == 422
    assert response.json["error"]["fields"][0]["code"] == "COORDINATE_PAIR_REQUIRED"


def test_patch_warehouse_updates_row(client, seeded_database):
    response = client.patch(
        "/api/v1/warehouses/1",
        json={"name": "更新後倉庫", "capacity_m3": None},
    )

    assert response.status_code == 200
    assert response.json["data"]["name"] == "更新後倉庫"
    assert response.json["data"]["capacity_m3"] is None
    assert response.json["data"]["facility_type"] == "避難所倉庫"


def test_patch_warehouse_returns_not_found(client, seeded_database):
    response = client.patch(
        "/api/v1/warehouses/999",
        json={"name": "存在しない倉庫"},
    )

    assert response.status_code == 404
    assert response.json["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=201",
        "?offset=-1",
        "?coordinates=unknown",
        "?unknown=value",
    ],
)
def test_get_warehouses_rejects_invalid_query(client, seeded_database, query):
    response = client.get(f"/api/v1/warehouses{query}")

    assert response.status_code == 422
    assert response.json["error"]["fields"]
