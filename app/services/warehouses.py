"""倉庫一覧の読取処理。"""

from app import db


class ThresholdUnitError(Exception):
    """基準数量が品目の単位条件に合わない場合に発生する例外。"""


def list_warehouses(connection, *, q=None, coordinates=None, limit=50, offset=0):
    """倉庫一覧を同じ読取トランザクション内で取得する。

    q は倉庫名または住所のリテラル部分一致、coordinates は座標の有無で
    絞り込む。値はSQLへ直接埋め込まず、すべてバインドする。
    """
    filters = []
    parameters = []

    if q is not None:
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_q}%"
        filters.append("(name LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\')")
        parameters.extend([pattern, pattern])

    if coordinates == "known":
        filters.append("latitude IS NOT NULL")
    elif coordinates == "missing":
        filters.append("latitude IS NULL")

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with db.transaction(connection, write=False):
        total = connection.execute(
            f"SELECT count(*) FROM warehouses {where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT warehouse_id, name, facility_type, address,
                   latitude, longitude, capacity_m3, allocation_mode
            FROM warehouses
            {where}
            ORDER BY warehouse_id ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()

    return [dict(row) for row in rows], total

def post_warehouse(
    connection,
    *,
    name,
    facility_type,
    address,
    latitude=None,
    longitude=None,
    capacity_m3=None,
):
    """倉庫を新規作成する。計算区分は専用APIで設定するためnullにする。"""
    with db.transaction(connection, write=True):
        cursor = connection.execute(
            """
            INSERT INTO warehouses (name, facility_type, address, latitude, longitude, capacity_m3, allocation_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, facility_type, address, latitude, longitude, capacity_m3, None),
        )
        warehouse_id = cursor.lastrowid
    return warehouse_id

def patch_warehouse(connection, warehouse_id, changes):
    """指定された通常項目だけを倉庫へ反映する。"""
    updates = []
    parameters = []

    for column in (
        "name",
        "facility_type",
        "address",
        "latitude",
        "longitude",
        "capacity_m3",
    ):
        if column in changes:
            updates.append(f"{column} = ?")
            parameters.append(changes[column])

    if not updates:
        return

    set_clause = ", ".join(updates)

    with db.transaction(connection, write=True):
        connection.execute(
            f"UPDATE warehouses SET {set_clause} WHERE warehouse_id = ?",
            [*parameters, warehouse_id],
        )

def get_warehouse(connection, warehouse_id):
    """倉庫を取得する。"""
    with db.transaction(connection, write=False):
        row = connection.execute(
            """
            SELECT warehouse_id, name, facility_type, address,
            latitude, longitude, capacity_m3, allocation_mode
            FROM warehouses
            WHERE warehouse_id = ?
            """,
            (warehouse_id,),
        ).fetchone()
        return dict(row) if row is not None else None


def list_thresholds(connection, warehouse_id):
    """倉庫に設定済みの基準だけを返す。未設定の品目は行を返さない。"""
    with db.transaction(connection, write=False):
        rows = connection.execute(
            """
            SELECT warehouse_id, item_id, minimum_quantity
            FROM stock_thresholds
            WHERE warehouse_id = ?
            ORDER BY item_id ASC
            """,
            (warehouse_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def put_threshold(connection, warehouse_id, item_id, minimum_quantity):
    """倉庫×品目の基準を新設または更新する。0も有効な値として保存する。"""
    with db.transaction(connection, write=True):
        warehouse = connection.execute(
            "SELECT warehouse_id FROM warehouses WHERE warehouse_id = ?",
            (warehouse_id,),
        ).fetchone()
        item = connection.execute(
            "SELECT item_id, is_divisible FROM items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if warehouse is None or item is None:
            return None, False

        if not bool(item["is_divisible"]) and minimum_quantity != minimum_quantity.to_integral_value():
            raise ThresholdUnitError()

        existing = connection.execute(
            """
            SELECT 1 FROM stock_thresholds
            WHERE warehouse_id = ? AND item_id = ?
            """,
            (warehouse_id, item_id),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO stock_thresholds (warehouse_id, item_id, minimum_quantity)
            VALUES (?, ?, ?)
            ON CONFLICT (warehouse_id, item_id)
            DO UPDATE SET minimum_quantity = excluded.minimum_quantity
            """,
            (warehouse_id, item_id, float(minimum_quantity)),
        )
        row = connection.execute(
            """
            SELECT warehouse_id, item_id, minimum_quantity
            FROM stock_thresholds
            WHERE warehouse_id = ? AND item_id = ?
            """,
            (warehouse_id, item_id),
        ).fetchone()
    return dict(row), existing is None
