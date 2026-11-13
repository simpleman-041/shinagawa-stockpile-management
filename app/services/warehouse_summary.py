"""WH05。異なる管理単位を足さず、現物容量と日常使用可能数を区別する。"""

import math
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from app import db
from app.services import stocks
from app.services.stocks import StockError
from app.services.warehouse_settings import issue, warehouse_dto


def summary(connection, warehouse_id):
    with db.transaction(connection, write=False), localcontext() as context:
        context.prec = 1000
        warehouse = stocks.reference(connection, "warehouses", "warehouse_id", warehouse_id)
        base = stocks.today()
        rows = connection.execute("SELECT s.*,i.unit_volume_m3,i.near_expiry_days FROM stocks s JOIN items i USING(item_id) WHERE s.warehouse_id=? AND s.state='active' ORDER BY s.stock_id", (warehouse_id,)).fetchall()
        thresholds = {r["item_id"]: r["minimum_quantity"] for r in connection.execute("SELECT * FROM stock_thresholds WHERE warehouse_id=?", (warehouse_id,))}
        ids = sorted({r["item_id"] for r in rows} | thresholds.keys())
        def dec(v):
            if v is None:
                return None
            if not v.is_finite() or not math.isfinite(float(v)):
                raise StockError("NUMBER_NOT_REPRESENTABLE", "集計の数値範囲を超えています。")
            return format(v.quantize(Decimal(".01"), rounding=ROUND_HALF_UP), "f")
        issues, used, values = [], Decimal(0), []
        for iid in ids:
            item = stocks.reference(connection, "items", "item_id", iid)
            result = {k: Decimal(0) for k in ("physical_quantity", "allocated_total", "dated_usable_quantity", "no_expiry_quantity", "expired_quantity", "unconfirmed_quantity", "near_expiry_quantity")}
            for row in (r for r in rows if r["item_id"] == iid):
                quantity = Decimal(str(row["quantity"]))
                allocated = sum((Decimal(str(a[0])) for a in connection.execute("SELECT quantity FROM stock_allocations WHERE stock_id=? ORDER BY shelter_id", (row["stock_id"],))), Decimal(0))
                if not quantity.is_finite() or quantity < 0 or allocated > quantity:
                    raise StockError("DATA_INTEGRITY_ERROR", "在庫・割当数量の整合性を確認してください。", status=500)
                result["physical_quantity"] += quantity
                result["allocated_total"] += allocated
                if row["unit_volume_m3"] is None:
                    value = issue("UNIT_VOLUME_MISSING", "品目の単位容積が未設定です。", f"/items/{iid}/unit_volume_m3")
                    if value not in issues:
                        issues.append(value)
                else:
                    used += quantity * Decimal(str(row["unit_volume_m3"]))
                state = row["expiry_state"]
                if state == "dated":
                    try:
                        remaining = (date.fromisoformat(row["expiry_date"]) - base).days
                    except ValueError:
                        raise StockError("DATA_INTEGRITY_ERROR", "期限日が不正です。", status=500) from None
                    result["expired_quantity" if remaining < 0 else "dated_usable_quantity"] += quantity
                    if remaining >= 0 and row["near_expiry_days"] is not None and remaining <= row["near_expiry_days"]:
                        result["near_expiry_quantity"] += quantity
                else:
                    result["no_expiry_quantity" if state == "none" else "unconfirmed_quantity"] += quantity
            result["unallocated_quantity"] = result["physical_quantity"] - result["allocated_total"]
            result["daily_usable_quantity"] = result["dated_usable_quantity"] + result["no_expiry_quantity"]
            minimum = Decimal(str(thresholds[iid])) if iid in thresholds else None
            values.append({"item_id": str(iid), "item_name": item["name"], "quantity_unit": item["quantity_unit"],
                           **{k: dec(v) for k, v in result.items()}, "minimum_quantity": dec(minimum),
                           "below_minimum": None if minimum is None else result["daily_usable_quantity"] < minimum})
        volume_missing = bool(issues)
        capacity = None if warehouse["capacity_m3"] is None else Decimal(str(warehouse["capacity_m3"]))
        if capacity is None or capacity == 0:
            issues.append(issue("CAPACITY_MISSING" if capacity is None else "CAPACITY_ZERO", "保管可能容量が未設定または0です。", f"/warehouses/{warehouse_id}/capacity_m3"))
        rate = None if issues else used / capacity * 100
        return {"warehouse": warehouse_dto(warehouse), "base_date": base.isoformat(), "items": values,
                "capacity": {"state": "unavailable" if issues else "computed", "used_volume_m3": None if volume_missing else dec(used), "capacity_m3": dec(capacity), "usage_rate": dec(rate),
                             "level": "unknown" if issues else "over" if used > capacity else "full" if used == capacity else "available", "issues": issues}}
