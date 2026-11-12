"""在庫の参照・登録・訂正・状態変更・確認付き統合。API設計1.0のTX01/03/04/07。"""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

from app import db


class StockError(Exception):
    """HTTP境界へ渡す入力・業務エラー。"""

    def __init__(self, code, message, *, status=422, path=None, details=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.fields = [] if path is None else [{"path": path, "code": code, "message": message}]
        self.details = details or {}


def today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def decimal_text(value):
    return format(Decimal(str(value)), "f")


def stored_quantity(value, divisible=True, path="/initial_quantity"):
    """REALへ往復しても十進値が失われない数量だけを受け入れる。"""
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise StockError("VALIDATION_ERROR", "数量は0以上にしてください。", path=path)
    if value.as_tuple().exponent < -2:
        raise StockError("DECIMAL_PRECISION", "小数第2位まで指定できます。", path=path)
    if not divisible and value != value.to_integral_value():
        raise StockError("INTEGER_REQUIRED", "この品目の数量は整数にしてください。", path=path)
    number = float(value)
    if not math.isfinite(number) or Decimal(str(number)) != value:
        raise StockError("NUMBER_NOT_REPRESENTABLE", "保存できる数値範囲・精度を超えています。", path=path)
    return number


def add_quantities(left, right):
    # 最大REAL付近の値にも既定の28桁丸めを入れない。
    with localcontext() as context:
        context.prec = 650
        return Decimal(str(left)) + Decimal(str(right))


def reference(connection, table, key, value, *, path=None):
    """呼出元が指定した固定テーブル・列の参照を確認する。"""
    row = connection.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
    if row is None:
        raise StockError("REFERENCE_NOT_FOUND" if path else "RESOURCE_NOT_FOUND",
                         "指定した対象が見つかりません。", status=422 if path else 404, path=path)
    return row


def stock_row(connection, stock_id, *, active=False):
    row = reference(connection, "stocks", "stock_id", stock_id)
    if active and row["state"] != "active":
        raise StockError("STOCK_NOT_ACTIVE", "有効な在庫だけを操作できます。", status=409)
    return row


def dto(row):
    """在庫・履歴のIDとREAL数量を契約の文字列表現にする。"""
    result = dict(row)
    for key, value in result.items():
        if value is not None and (key.endswith("_id") or key in ("merged_by", "operator_id")):
            result[key] = str(value)
        elif key == "quantity":
            result[key] = decimal_text(value)
    return result


def view(connection, stock_id, base_date=None):
    row = stock_row(connection, stock_id)
    item = reference(connection, "items", "item_id", row["item_id"])
    base_date = base_date or today()
    allocated = Decimal(0)
    for allocation in connection.execute("SELECT quantity FROM stock_allocations WHERE stock_id=?", (stock_id,)):
        allocated = add_quantities(allocated, allocation[0])
    remaining = add_quantities(row["quantity"], allocated.copy_negate())
    if remaining < 0:
        raise StockError("DATA_INTEGRITY_ERROR", "割当数量が現在庫を超えています。", status=500)
    status = row["expiry_state"]
    if status == "dated":
        try:
            days = (date.fromisoformat(row["expiry_date"]) - base_date).days
        except ValueError:
            raise StockError("DATA_INTEGRITY_ERROR", "保存済み使用期限を確認してください。", status=500) from None
        status = "expired" if days < 0 else "near" if days <= item["near_expiry_days"] else "valid"
    return {"stock": dto(row), "item_name": item["name"], "quantity_unit": item["quantity_unit"],
            "item_registration_state": item["registration_state"], "allocated_total": decimal_text(allocated),
            "unallocated_quantity": decimal_text(remaining), "expiry_status": status, "base_date": base_date.isoformat()}


def get_stock(connection, stock_id):
    with db.transaction(connection, write=False):
        return view(connection, stock_id)


def restoration_context(connection, stock_id):
    """復元確認画面に表示する、現在の倉庫区分と全対応先を読む。"""
    with db.transaction(connection, write=False):
        row = stock_row(connection, stock_id)
        warehouse = reference(connection, "warehouses", "warehouse_id", row["warehouse_id"])
        shelters = connection.execute(
            "SELECT name FROM shelters JOIN shelter_warehouses USING(shelter_id) "
            "WHERE warehouse_id=? ORDER BY shelter_id", (row["warehouse_id"],),
        ).fetchall()
        return {"mode": {"dedicated": "専用", "shared": "共有", None: "未設定"}[warehouse["allocation_mode"]],
                "shelters": [shelter[0] for shelter in shelters]}


def list_stocks(connection, *, limit=50, offset=0, **filters):
    base_date = today()
    clauses, params = ["s.state=?"], [filters.get("state", "active")]
    for key in ("warehouse_id", "item_id"):
        if key in filters:
            clauses.append(f"s.{key}=?")
            params.append(filters[key])
    if "q" in filters:
        escaped = filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(i.name LIKE ? ESCAPE '\\' OR s.location LIKE ? ESCAPE '\\')")
        params.extend([f"%{escaped}%"] * 2)
    with db.transaction(connection, write=False):
        rows = connection.execute("SELECT s.stock_id FROM stocks s JOIN items i USING(item_id) WHERE "
                                  + " AND ".join(clauses) + " ORDER BY s.stock_id", params).fetchall()
        values = [view(connection, row[0], base_date) for row in rows]
        if "expiry_status" in filters:
            values = [value for value in values if value["expiry_status"] == filters["expiry_status"]]
        return values[offset:offset + limit], len(values)


def create_stock(connection, values):
    """一致候補検索・初期数量加算・職員名付き入庫履歴を同じ書込みで保存する。"""
    with db.transaction(connection):
        reference(connection, "warehouses", "warehouse_id", values["warehouse_id"], path="/warehouse_id")
        item = reference(connection, "items", "item_id", values["item_id"], path="/item_id")
        if item["registration_state"] != "active":
            raise StockError("ITEM_CLOSED", "登録終了品目への在庫登録はできません。", status=409)
        amount = stored_quantity(values["initial_quantity"], item["is_divisible"])
        operator = None
        if values.get("operator_id") is not None:
            operator = reference(connection, "operators", "operator_id", values["operator_id"], path="/operator_id")
        if amount > 0 and operator is None:
            raise StockError("VALIDATION_ERROR", "初期数量が正の場合は担当者が必要です。", path="/operator_id")
        if amount == 0 and values.get("reason") is not None:
            raise StockError("VALIDATION_ERROR", "数量0の登録では理由を指定できません。", path="/reason")
        candidates = []
        if values["expiry_state"] != "unconfirmed":
            candidates = connection.execute(
                "SELECT * FROM stocks WHERE warehouse_id=? AND item_id=? AND location=? "
                "AND expiry_state=? AND expiry_date IS ? AND state='active' ORDER BY stock_id",
                tuple(values[key] for key in ("warehouse_id", "item_id", "location", "expiry_state", "expiry_date")),
            ).fetchall()
        if len(candidates) > 1:
            raise StockError("STOCK_CANDIDATES_AMBIGUOUS", "一致する在庫が複数あります。詳細で対象を確認してください。",
                             status=409, details={"candidate_stock_ids": [str(row["stock_id"]) for row in candidates]})
        reused = bool(candidates)
        if reused:
            stock_id = candidates[0]["stock_id"]
            quantity = stored_quantity(add_quantities(candidates[0]["quantity"], amount), item["is_divisible"])
            connection.execute("UPDATE stocks SET quantity=? WHERE stock_id=?", (quantity, stock_id))
        else:
            stock_id = connection.execute(
                "INSERT INTO stocks(warehouse_id,item_id,location,quantity,expiry_state,expiry_date) VALUES(?,?,?,?,?,?)",
                (values["warehouse_id"], values["item_id"], values["location"], amount, values["expiry_state"], values["expiry_date"]),
            ).lastrowid
        movement = None
        if amount > 0:
            generation = stock_row(connection, stock_id)["merge_generation"]
            movement_id = connection.execute(
                "INSERT INTO stock_movements(stock_id,operator_id,operator_name,kind,quantity,registered_at,reason,merge_generation) "
                "VALUES(?,?,?,'in',?,?,?,?)",
                (stock_id, operator["operator_id"], operator["name"], amount, timestamp(), values.get("reason"), generation),
            ).lastrowid
            movement = dto(reference(connection, "stock_movements", "movement_id", movement_id))
        return {"stock": view(connection, stock_id), "reused_existing": reused, "movement": movement}


def change_location(connection, stock_id, location):
    with db.transaction(connection):
        stock_row(connection, stock_id, active=True)
        connection.execute("UPDATE stocks SET location=? WHERE stock_id=?", (location, stock_id))
        return view(connection, stock_id)


def change_state(connection, stock_id, operator_id, *, restore):
    with db.transaction(connection):
        row = stock_row(connection, stock_id)
        reference(connection, "operators", "operator_id", operator_id, path="/operator_id")
        if row["state"] != ("deleted" if restore else "active"):
            raise StockError("INVALID_STOCK_STATE", "削除・復元できる状態ではありません。", status=409)
        if restore:
            item = reference(connection, "items", "item_id", row["item_id"])
            if item["registration_state"] != "active":
                raise StockError("ITEM_CLOSED", "登録終了品目の在庫は復元できません。", status=409)
        if connection.execute("SELECT 1 FROM stock_allocations WHERE stock_id=?", (stock_id,)).fetchone():
            raise StockError("ALLOCATIONS_EXIST", "割当を解除してから操作してください。", status=409)
        connection.execute("UPDATE stocks SET state=? WHERE stock_id=?", ("active" if restore else "deleted", stock_id))
        event_id = connection.execute(
            "INSERT INTO stock_state_events(stock_id,action,operator_id,occurred_at) VALUES(?,?,?,?)",
            (stock_id, "restore" if restore else "delete", operator_id, timestamp()),
        ).lastrowid
        return {"stock": view(connection, stock_id), "event": dto(reference(connection, "stock_state_events", "event_id", event_id))}


def change_expiry(connection, stock_id, expiry_state, expiry_date, operator_id):
    with db.transaction(connection):
        row = stock_row(connection, stock_id, active=True)
        reference(connection, "operators", "operator_id", operator_id, path="/operator_id")
        if (row["expiry_state"], row["expiry_date"]) == (expiry_state, expiry_date):
            raise StockError("NO_CHANGE", "現在と同じ期限です。", status=409)
        connection.execute("UPDATE stocks SET expiry_state=?,expiry_date=? WHERE stock_id=?", (expiry_state, expiry_date, stock_id))
        change_id = connection.execute(
            "INSERT INTO stock_expiry_changes(stock_id,before_expiry_state,before_expiry_date,after_expiry_state,after_expiry_date,operator_id,changed_at) "
            "VALUES(?,?,?,?,?,?,?)", (stock_id, row["expiry_state"], row["expiry_date"], expiry_state, expiry_date, operator_id, timestamp()),
        ).lastrowid
        return {"stock": view(connection, stock_id), "change": dto(reference(connection, "stock_expiry_changes", "change_id", change_id))}


def history(connection, stock_id, kind, limit, offset):
    table, order = {"state-events": ("stock_state_events", "occurred_at DESC,event_id DESC"),
                    "expiry-changes": ("stock_expiry_changes", "changed_at DESC,change_id DESC")}[kind]
    with db.transaction(connection, write=False):
        stock_row(connection, stock_id)
        count = connection.execute(f"SELECT count(*) FROM {table} WHERE stock_id=?", (stock_id,)).fetchone()[0]
        rows = connection.execute(f"SELECT * FROM {table} WHERE stock_id=? ORDER BY {order} LIMIT ? OFFSET ?", (stock_id, limit, offset))
        return [dto(row) for row in rows], count


def merge_snapshot(connection, source_id, target_id):
    if source_id == target_id:
        raise StockError("MERGE_CONDITION_MISMATCH", "異なる在庫を選択してください。", status=409)
    source, target = view(connection, source_id), view(connection, target_id)
    left, right = source["stock"], target["stock"]
    if left["state"] != "active" or right["state"] != "active":
        raise StockError("STOCK_NOT_ACTIVE", "双方とも有効な在庫である必要があります。", status=409)
    if "unconfirmed" in (left["expiry_state"], right["expiry_state"]):
        raise StockError("MERGE_EXPIRY_UNCONFIRMED", "期限未確認の在庫は統合できません。", status=409)
    keys = ("warehouse_id", "item_id", "location", "expiry_state", "expiry_date")
    if any(left[key] != right[key] for key in keys):
        raise StockError("MERGE_CONDITION_MISMATCH", "倉庫・品目・場所・期限が一致する在庫を選んでください。", status=409)
    if connection.execute("SELECT 1 FROM stock_allocations WHERE stock_id IN (?,?)", (source_id, target_id)).fetchone():
        raise StockError("ALLOCATIONS_EXIST", "双方の割当を解除してください。", status=409)
    amount = add_quantities(left["quantity"], right["quantity"])
    item = reference(connection, "items", "item_id", int(left["item_id"]))
    stored_quantity(amount, item["is_divisible"])
    if right["merge_generation"] >= 9007199254740991:
        raise StockError("NUMBER_NOT_REPRESENTABLE", "統合世代の表現範囲を超えます。")
    return {"source": source, "target": target, "after_source_quantity": "0",
            "after_target_quantity": decimal_text(amount), "after_target_generation": right["merge_generation"] + 1,
            "cancellation_notice": "元在庫は統合済み・数量0になります。統合の取消と、元先双方の統合前取引の直接取消はできません。"}


def preview_merge(connection, source_id, target_id):
    with db.transaction(connection, write=False):
        reference(connection, "stocks", "stock_id", source_id, path="/source_stock_id")
        reference(connection, "stocks", "stock_id", target_id, path="/target_stock_id")
        return merge_snapshot(connection, source_id, target_id)


def execute_merge(connection, snapshot, operator_id):
    source_id = int(snapshot["source"]["stock"]["stock_id"])
    target_id = int(snapshot["target"]["stock"]["stock_id"])
    with db.transaction(connection):
        reference(connection, "operators", "operator_id", operator_id, path="/operator_id")
        try:
            current = merge_snapshot(connection, source_id, target_id)
        except StockError as error:
            if error.status == 409:
                raise StockError("PREVIEW_CHANGED", "在庫の状態が変わりました。再度プレビューしてください。", status=409) from None
            raise
        # 判定日だけの変化は統合条件を変えない。表示した名前・単位等は比較する。
        def comparable(value):
            return {key: val for key, val in value.items() if key not in ("base_date", "expiry_status")}
        if (comparable(current["source"]) != comparable(snapshot["source"])
                or comparable(current["target"]) != comparable(snapshot["target"])):
            raise StockError("PREVIEW_CHANGED", "プレビュー後に情報が変わりました。再確認してください。", status=409)
        connection.execute("UPDATE stocks SET quantity=?,merge_generation=? WHERE stock_id=?",
                           (float(current["after_target_quantity"]), current["after_target_generation"], target_id))
        connection.execute("UPDATE stocks SET state='merged',quantity=0,merged_into_stock_id=?,merged_at=?,merged_by=? WHERE stock_id=?",
                           (target_id, timestamp(), operator_id, source_id))
        return {"source": view(connection, source_id), "target": view(connection, target_id)}
