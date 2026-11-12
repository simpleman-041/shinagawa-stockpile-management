"""入出庫と元取引の条件付き取消。API設計1.0のMV01〜04、TX01・TX02。"""

from decimal import Decimal

from app import db
from app.services import stocks
from app.services.stocks import StockError


def get_movement(connection, movement_id):
    with db.transaction(connection, write=False):
        return stocks.dto(stocks.reference(connection, "stock_movements", "movement_id", movement_id))


def list_movements(connection, *, limit=50, offset=0, **filters):
    clauses, params = [], []
    for key in ("stock_id", "state", "kind"):
        if key in filters:
            clauses.append(f"{key}=?")
            params.append(filters[key])
    for key, comparison in (("from", ">="), ("to", "<")):
        if key in filters:
            clauses.append(f"registered_at{comparison}?")
            params.append(filters[key])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db.transaction(connection, write=False):
        total = connection.execute("SELECT count(*) FROM stock_movements" + where, params).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM stock_movements" + where
            + " ORDER BY registered_at DESC,movement_id DESC LIMIT ? OFFSET ?", (*params, limit, offset),
        ).fetchall()
        return [stocks.dto(row) for row in rows], total


def resulting_quantity(connection, row, item, difference):
    """書込ロック内で数量・全割当を検証し、丸めずに保存可能な値を返す。"""
    quantity = stocks.add_quantities(row["quantity"], difference)
    if quantity < 0:
        raise StockError("NEGATIVE_STOCK", "数量が現在庫を超えます。数量を減らしてください。", status=409,
                         path="/quantity", details={"stock_id": str(row["stock_id"]),
                                                   "result_quantity": stocks.decimal_text(quantity)})
    current = stocks.view(connection, row["stock_id"])
    if quantity < Decimal(current["allocated_total"]):
        raise StockError("ALLOCATION_EXCEEDS_STOCK", "更新後の数量が割当合計を下回ります。先に割当を減らすか、数量を減らしてください。",
                         status=409, path="/quantity", details={"stock_id": str(row["stock_id"]),
                             "result_quantity": stocks.decimal_text(quantity), "allocated_total": current["allocated_total"]})
    return stocks.stored_quantity(quantity, item["is_divisible"], path="/quantity")


def create_movement(connection, stock_id, values):
    with db.transaction(connection):
        row = stocks.stock_row(connection, stock_id, active=True)
        item = stocks.reference(connection, "items", "item_id", row["item_id"])
        if values["kind"] not in ("in", "out"):
            raise StockError("VALIDATION_ERROR", "入庫・出庫を選択してください。", path="/kind")
        amount = stocks.stored_quantity(values["quantity"], item["is_divisible"], path="/quantity")
        if amount <= 0:
            raise StockError("VALIDATION_ERROR", "数量は0より大きい値にしてください。", path="/quantity")
        if values["kind"] == "in" and item["registration_state"] != "active":
            raise StockError("ITEM_CLOSED", "登録終了品目への入庫はできません。出庫と条件付き取消は利用できます。", status=409)
        operator = stocks.reference(connection, "operators", "operator_id", values["operator_id"], path="/operator_id")
        difference = Decimal(str(amount))
        if values["kind"] == "out":
            difference = difference.copy_negate()
        quantity = resulting_quantity(connection, row, item, difference)
        if connection.execute("UPDATE stocks SET quantity=? WHERE stock_id=?", (quantity, stock_id)).rowcount != 1:
            raise RuntimeError("Stock update failed")
        movement_id = connection.execute(
            "INSERT INTO stock_movements(stock_id,operator_id,operator_name,kind,quantity,registered_at,reason,merge_generation) "
            "VALUES(?,?,?,?,?,?,?,?)", (stock_id, operator["operator_id"], operator["name"], values["kind"],
                amount, stocks.timestamp(), values.get("reason"), row["merge_generation"]),
        ).lastrowid
        return {"stock": stocks.view(connection, stock_id),
                "movement": stocks.dto(stocks.reference(connection, "stock_movements", "movement_id", movement_id))}


def cancel_movement(connection, movement_id, operator_id):
    with db.transaction(connection):
        movement = stocks.reference(connection, "stock_movements", "movement_id", movement_id)
        if movement["state"] != "active":
            raise StockError("MOVEMENT_ALREADY_CANCELLED", "この取引は既に取り消されています。", status=409)
        row = stocks.stock_row(connection, movement["stock_id"], active=True)
        if movement["merge_generation"] != row["merge_generation"]:
            raise StockError("MERGE_GENERATION_MISMATCH", "統合前の取引は直接取り消せません。", status=409)
        operator = stocks.reference(connection, "operators", "operator_id", operator_id, path="/operator_id")
        item = stocks.reference(connection, "items", "item_id", row["item_id"])
        difference = Decimal(str(movement["quantity"]))
        if movement["kind"] == "in":
            difference = difference.copy_negate()
        quantity = resulting_quantity(connection, row, item, difference)
        if connection.execute("UPDATE stocks SET quantity=? WHERE stock_id=?", (quantity, row["stock_id"])).rowcount != 1:
            raise RuntimeError("Stock update failed")
        changed = connection.execute(
            "UPDATE stock_movements SET state='cancelled',cancelled_at=?,cancel_operator_id=?,cancel_operator_name=? "
            "WHERE movement_id=? AND state='active'",
            (stocks.timestamp(), operator["operator_id"], operator["name"], movement_id),
        ).rowcount
        if changed != 1:
            raise RuntimeError("Movement cancellation failed")
        return {"stock": stocks.view(connection, row["stock_id"]),
                "movement": stocks.dto(stocks.reference(connection, "stock_movements", "movement_id", movement_id))}
