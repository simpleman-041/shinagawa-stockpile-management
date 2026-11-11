"""品目の登録・編集・登録終了を扱う業務処理。"""

from decimal import Decimal

from app import db


class ItemConflict(Exception):
    """品目の状態や既存データが原因で更新できない場合の例外。"""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _item_from_row(row):
    item = dict(row)
    item["item_id"] = str(item["item_id"])
    if item["unit_volume_m3"] is not None:
        value = format(Decimal(str(item["unit_volume_m3"])), "f")
        integer_part, _, fraction_part = value.partition(".")
        item["unit_volume_m3"] = f"{integer_part}.{fraction_part[:2].ljust(2, '0')}"
    item["is_divisible"] = bool(item["is_divisible"])
    return item


def _get_item_row(connection, item_id):
    return connection.execute(
        """
        SELECT item_id, name, category, quantity_unit, unit_volume_m3,
               is_divisible, near_expiry_days, registration_state
        FROM items
        WHERE item_id = ?
        """,
        (item_id,),
    ).fetchone()


def list_items(connection, *, q=None, registration_state=None, limit=50, offset=0):
    filters = []
    parameters = []

    if q is not None:
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append("name LIKE ? ESCAPE '\\'")
        parameters.append(f"%{escaped_q}%")
    if registration_state is not None:
        filters.append("registration_state = ?")
        parameters.append(registration_state)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with db.transaction(connection, write=False):
        total = connection.execute(
            f"SELECT count(*) FROM items {where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT item_id, name, category, quantity_unit, unit_volume_m3,
                   is_divisible, near_expiry_days, registration_state
            FROM items
            {where}
            ORDER BY item_id ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()

    return [_item_from_row(row) for row in rows], total


def get_item(connection, item_id):
    with db.transaction(connection, write=False):
        row = _get_item_row(connection, item_id)
    return _item_from_row(row) if row is not None else None


def post_item(
    connection,
    *,
    name,
    category,
    quantity_unit,
    is_divisible,
    near_expiry_days,
    unit_volume_m3=None,
):
    with db.transaction(connection, write=True):
        cursor = connection.execute(
            """
            INSERT INTO items
                (name, category, quantity_unit, unit_volume_m3,
                 is_divisible, near_expiry_days, registration_state)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                name,
                category,
                quantity_unit,
                unit_volume_m3,
                int(is_divisible),
                near_expiry_days,
            ),
        )
        return cursor.lastrowid


def _has_fractional_values(connection, item_id):
    checks = (
        ("stocks", "quantity"),
        ("stock_allocations", "quantity"),
        ("stock_thresholds", "minimum_quantity"),
    )
    for table, column in checks:
        rows = connection.execute(
            f"SELECT {column} FROM {table} WHERE item_id = ?", (item_id,)
        ).fetchall()
        for row in rows:
            value = Decimal(str(row[0]))
            if value != value.to_integral_value():
                return table
    return None


def patch_item(connection, item_id, changes):
    with db.transaction(connection, write=True):
        current = _get_item_row(connection, item_id)
        if current is None:
            return None

        if (
            "quantity_unit" in changes
            and changes["quantity_unit"] != current["quantity_unit"]
        ):
            has_stock = connection.execute(
                "SELECT 1 FROM stocks WHERE item_id = ? LIMIT 1", (item_id,)
            ).fetchone()
            if has_stock is not None:
                raise ItemConflict(
                    "UNIT_HAS_STOCK",
                    "既存在庫がある品目の管理単位は変更できません。",
                    {"item_id": str(item_id)},
                )

        if "is_divisible" in changes:
            new_is_divisible = bool(changes["is_divisible"])
            if not new_is_divisible and new_is_divisible != bool(current["is_divisible"]):
                table = _has_fractional_values(connection, item_id)
                if table is not None:
                    raise ItemConflict(
                        "UNIT_HAS_STOCK",
                        "既存の数量・割当・基準に小数があるため分割不可へ変更できません。",
                        {"item_id": str(item_id), "source": table},
                    )

        assignments = []
        parameters = []
        for column in (
            "name",
            "category",
            "quantity_unit",
            "unit_volume_m3",
            "is_divisible",
            "near_expiry_days",
        ):
            if column in changes:
                assignments.append(f"{column} = ?")
                value = changes[column]
                if column == "is_divisible":
                    value = int(value)
                parameters.append(value)

        set_clause = ", ".join(assignments)
        connection.execute(
            f"UPDATE items SET {set_clause} WHERE item_id = ?",
            [*parameters, item_id],
        )
        return _item_from_row(_get_item_row(connection, item_id))


def close_item(connection, item_id):
    with db.transaction(connection, write=True):
        current = _get_item_row(connection, item_id)
        if current is None:
            return None
        if current["registration_state"] == "active":
            connection.execute(
                "UPDATE items SET registration_state = 'closed' WHERE item_id = ?",
                (item_id,),
            )
            current = _get_item_row(connection, item_id)
        return _item_from_row(current)
