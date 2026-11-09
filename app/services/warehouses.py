"""倉庫一覧の読取処理。"""

from app import db


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
