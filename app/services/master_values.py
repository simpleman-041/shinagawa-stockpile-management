"""保存済みマスター値を丸めず、契約の2桁十進文字列へ戻す。"""

from decimal import Decimal

from app.services.stocks import StockError, stored_quantity


def decimal_text(value):
    if value is None:
        return None
    try:
        stored_quantity(value)
    except (StockError, ValueError, OverflowError):
        raise StockError("DATA_INTEGRITY_ERROR", "保存済み数値の精度・範囲を確認してください。", status=500) from None
    whole, _, fraction = format(Decimal(str(value)), "f").partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}"


def warehouse_dto(row):
    if row is None:
        return None
    value = dict(row)
    value["warehouse_id"] = str(value["warehouse_id"])
    value["capacity_m3"] = decimal_text(value["capacity_m3"])
    return value


def threshold_dto(row):
    return {"warehouse_id": str(row["warehouse_id"]), "item_id": str(row["item_id"]),
            "minimum_quantity": decimal_text(row["minimum_quantity"])}
