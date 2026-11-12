"""避難所の登録・編集・正式目標・設定状態を扱う業務処理。"""

from app import db


def _shelter_from_row(row):
    return dict(row) if row is not None else None


def _get_shelter_row(connection, shelter_id):
    return connection.execute(
        """
        SELECT shelter_id, name, address, target_people, target_days, setup_state
        FROM shelters
        WHERE shelter_id = ?
        """,
        (shelter_id,),
    ).fetchone()


def list_shelters(connection, *, q=None, limit=50, offset=0):
    parameters = []
    where = ""
    if q is not None:
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = "WHERE (name LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\')"
        pattern = f"%{escaped_q}%"
        parameters.extend([pattern, pattern])

    with db.transaction(connection, write=False):
        total = connection.execute(
            f"SELECT count(*) FROM shelters {where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT shelter_id, name, address, target_people, target_days, setup_state
            FROM shelters
            {where}
            ORDER BY shelter_id ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()
    return [_shelter_from_row(row) for row in rows], total


def get_shelter(connection, shelter_id):
    with db.transaction(connection, write=False):
        return _shelter_from_row(_get_shelter_row(connection, shelter_id))


def post_shelter(connection, *, name, address, target_people=None, target_days=None):
    with db.transaction(connection, write=True):
        cursor = connection.execute(
            """
            INSERT INTO shelters (name, address, target_people, target_days, setup_state)
            VALUES (?, ?, ?, ?, 'editing')
            """,
            (name, address, target_people, target_days),
        )
        return cursor.lastrowid


def patch_shelter(connection, shelter_id, changes):
    assignments = []
    parameters = []
    for column in ("name", "address"):
        if column in changes:
            assignments.append(f"{column} = ?")
            parameters.append(changes[column])
    with db.transaction(connection, write=True):
        if _get_shelter_row(connection, shelter_id) is None:
            return None
        connection.execute(
            f"UPDATE shelters SET {', '.join(assignments)} WHERE shelter_id = ?",
            [*parameters, shelter_id],
        )
        return _shelter_from_row(_get_shelter_row(connection, shelter_id))


def put_targets(connection, shelter_id, *, target_people, target_days):
    with db.transaction(connection, write=True):
        if _get_shelter_row(connection, shelter_id) is None:
            return None
        connection.execute(
            "UPDATE shelters SET target_people = ?, target_days = ? WHERE shelter_id = ?",
            (target_people, target_days, shelter_id),
        )
        return _shelter_from_row(_get_shelter_row(connection, shelter_id))


def put_setup_state(connection, shelter_id, *, setup_state):
    """既存のサービス入口も、倉庫対応の整合性検証を経由する。"""
    from app.services.warehouse_settings import put_setup
    from app.services.stocks import StockError
    try:
        result = put_setup(connection, shelter_id, setup_state)
    except StockError as error:
        if error.status == 404:
            return None
        raise
    result["shelter_id"] = int(result["shelter_id"])
    return result
