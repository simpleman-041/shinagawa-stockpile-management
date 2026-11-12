"""避難所の倉庫対応と共有割当。API SH06〜08・AL01/02、TX05/06。"""

from decimal import Decimal

from app import db
from app.services import stocks
from app.services.stocks import StockError


def warehouse_dto(row):
    value = stocks.dto(row)
    if value["capacity_m3"] is not None:
        value["capacity_m3"] = stocks.decimal_text(value["capacity_m3"])
    return value


def links_for(connection, warehouse_id):
    return [stocks.dto(row) for row in connection.execute(
        "SELECT * FROM shelter_warehouses WHERE warehouse_id=? ORDER BY shelter_id", (warehouse_id,))]


def issue(code, message, *paths):
    return {"code": code, "message": message, "paths": list(paths)}


def warehouse_issues(connection, warehouse):
    """対応先・在庫・割当の矛盾を、完了操作と表示で同じ基準で検証する。"""
    warehouse_id = warehouse["warehouse_id"]
    prefix = f"/warehouses/{warehouse_id}"
    issues = []
    links = links_for(connection, warehouse_id)
    if warehouse["allocation_mode"] is None:
        issues.append(issue("WAREHOUSE_MODE_MISSING", "倉庫の専用・共有が未設定です。", prefix + "/allocation_mode"))
    if warehouse["allocation_mode"] == "dedicated" and len(links) != 1:
        issues.append(issue("DEDICATED_LINK_COUNT_INVALID", "専用倉庫の対応避難所は1件にしてください。", prefix + "/shelter_ids"))
    targets = {link["shelter_id"] for link in links}
    rows = connection.execute("SELECT * FROM stocks WHERE warehouse_id=? ORDER BY stock_id", (warehouse_id,)).fetchall()
    for row in rows:
        total = Decimal(0)
        allocations = connection.execute("SELECT * FROM stock_allocations WHERE stock_id=? ORDER BY shelter_id", (row["stock_id"],)).fetchall()
        item = stocks.reference(connection, "items", "item_id", row["item_id"])
        for allocation in allocations:
            total = stocks.add_quantities(total, allocation["quantity"])
            amount = Decimal(str(allocation["quantity"]))
            invalid_precision = amount.as_tuple().exponent < -2 or (not item["is_divisible"] and amount != amount.to_integral_value())
            if (row["state"] != "active" or warehouse["allocation_mode"] != "shared"
                    or str(allocation["shelter_id"]) not in targets or invalid_precision):
                issues.append(issue("ALLOCATION_LINK_INVALID", "在庫の状態・倉庫対応・数量単位と整合しない割当があります。",
                                    f'/stocks/{row["stock_id"]}/allocations/{allocation["shelter_id"]}'))
        if total > Decimal(str(row["quantity"])):
            issues.append(issue("ALLOCATION_LINK_INVALID", "全避難所の割当合計が現在庫を超えています。", f'/stocks/{row["stock_id"]}/allocations'))
    return issues


def settings_snapshot(connection, shelter_id):
    shelter = stocks.reference(connection, "shelters", "shelter_id", shelter_id)
    warehouses = connection.execute(
        "SELECT w.* FROM warehouses w JOIN shelter_warehouses sw USING(warehouse_id) "
        "WHERE sw.shelter_id=? ORDER BY w.warehouse_id", (shelter_id,),
    ).fetchall()
    issues, links = [], []
    if shelter["setup_state"] == "editing":
        issues.append(issue("SETUP_EDITING", "倉庫対応は設定中です。内容を確認して設定完了にしてください。", f"/shelters/{shelter_id}/setup_state"))
    for warehouse in warehouses:
        links.extend(links_for(connection, warehouse["warehouse_id"]))
        issues.extend(warehouse_issues(connection, warehouse))
    # 自分への割当があるが対応倉庫から外れている破損データも検出する。
    invalid = connection.execute(
        "SELECT a.stock_id FROM stock_allocations a JOIN stocks s USING(stock_id) "
        "WHERE a.shelter_id=? AND NOT EXISTS(SELECT 1 FROM shelter_warehouses sw "
        "WHERE sw.shelter_id=a.shelter_id AND sw.warehouse_id=s.warehouse_id) ORDER BY a.stock_id", (shelter_id,),
    )
    for row in invalid:
        issues.append(issue("ALLOCATION_LINK_INVALID", "対応のない倉庫の在庫が割り当てられています。", f'/stocks/{row["stock_id"]}/allocations/{shelter_id}'))
    groups = connection.execute("SELECT * FROM demand_groups ORDER BY group_id").fetchall()
    for group in groups:
        prefix = f'/demand_groups/{group["group_id"]}'
        for field, code, message in (
            ("calculation_unit", "GROUP_UNIT_MISSING", "需要の計算単位が未設定です。"),
            ("is_divisible", "GROUP_DIVISIBILITY_MISSING", "需要の分割可否が未設定です。"),
            ("daily_usage", "DAILY_USAGE_MISSING", "1人1日の使用量が未設定です。"),
        ):
            if group[field] is None:
                issues.append(issue(code, message, prefix + "/" + field))
        missing = [prefix + "/" + field for field in ("source_text", "version_or_date", "conditions") if group[field] is None]
        if missing:
            issues.append(issue("USAGE_SOURCE_MISSING", "使用量の根拠が未設定です。", *missing))
        conversions = connection.execute("SELECT * FROM item_conversions WHERE group_id=? ORDER BY item_id", (group["group_id"],)).fetchall()
        if not conversions:
            issues.append(issue("ITEM_CONVERSION_MISSING", "需要に品目が対応していません。", prefix))
        for conversion in conversions:
            cp = f'/item_conversions/{conversion["item_id"]}'
            if conversion["factor_x100"] is None:
                issues.append(issue("CONVERSION_FACTOR_MISSING", "品目の換算係数が未設定です。", cp + "/factor_x100"))
            missing = [cp + "/" + field for field in ("source_text", "version_or_date", "conditions") if conversion[field] is None]
            if missing:
                issues.append(issue("CONVERSION_SOURCE_MISSING", "品目換算の根拠が未設定です。", *missing))
        for warehouse in warehouses:
            if warehouse["allocation_mode"] != "dedicated":
                continue
            registered = connection.execute(
                "SELECT 1 FROM stocks s JOIN item_conversions ic USING(item_id) "
                "WHERE s.warehouse_id=? AND s.state='active' AND ic.group_id=? LIMIT 1",
                (warehouse["warehouse_id"], group["group_id"]),
            ).fetchone()
            if registered is None:
                issues.append(issue("STOCK_UNREGISTERED", "専用倉庫にこの需要の有効在庫が登録されていません。",
                                    f'/warehouses/{warehouse["warehouse_id"]}', prefix))
    links.sort(key=lambda link: (int(link["shelter_id"]), int(link["warehouse_id"])))
    return {"shelter": stocks.dto(shelter), "warehouses": [warehouse_dto(w) for w in warehouses], "links": links, "issues": issues}


def get_settings(connection, shelter_id):
    with db.transaction(connection, write=False):
        return settings_snapshot(connection, shelter_id)


def put_warehouse(connection, shelter_id, warehouse_id, mode, shelter_ids):
    with db.transaction(connection):
        stocks.reference(connection, "shelters", "shelter_id", shelter_id)
        warehouse = stocks.reference(connection, "warehouses", "warehouse_id", warehouse_id)
        if mode not in ("dedicated", "shared"):
            raise StockError("VALIDATION_ERROR", "専用または共有を選択してください。", path="/allocation_mode")
        if len(set(shelter_ids)) != len(shelter_ids):
            raise StockError("VALIDATION_ERROR", "対応避難所を重複指定できません。", path="/shelter_ids")
        if mode == "dedicated" and len(shelter_ids) != 1:
            raise StockError("INVALID_WAREHOUSE_LINKS", "専用倉庫は対応避難所を1件にしてください。", status=409)
        for index, target in enumerate(shelter_ids):
            stocks.reference(connection, "shelters", "shelter_id", target, path=f"/shelter_ids/{index}")
        old_ids = {int(link["shelter_id"]) for link in links_for(connection, warehouse_id)}
        new_ids = set(shelter_ids)
        affected = sorted(old_ids | new_ids)
        changed = old_ids != new_ids or mode != warehouse["allocation_mode"]
        if changed:
            invalid = connection.execute(
                "SELECT 1 FROM stock_allocations a JOIN stocks s USING(stock_id) "
                "WHERE s.warehouse_id=? AND (s.state!='active' OR NOT EXISTS(SELECT 1 FROM shelter_warehouses sw "
                "WHERE sw.warehouse_id=s.warehouse_id AND sw.shelter_id=a.shelter_id)) LIMIT 1", (warehouse_id,),
            ).fetchone()
            if invalid:
                raise StockError("DATA_INTEGRITY_ERROR", "状態・対応先と整合しない割当があります。データを確認してください。", status=500)
            in_use = connection.execute("SELECT 1 FROM stocks WHERE warehouse_id=? AND state='active' LIMIT 1", (warehouse_id,)).fetchone()
            if in_use:
                raise StockError("WAREHOUSE_IN_USE", "有効在庫がある倉庫の区分・対応先は変更できません。数量0の在庫も対象です。", status=409)
            connection.execute("UPDATE warehouses SET allocation_mode=? WHERE warehouse_id=?", (mode, warehouse_id))
            connection.execute("DELETE FROM shelter_warehouses WHERE warehouse_id=?", (warehouse_id,))
            connection.executemany("INSERT INTO shelter_warehouses(shelter_id,warehouse_id) VALUES(?,?)", [(target, warehouse_id) for target in sorted(new_ids)])
            connection.executemany("UPDATE shelters SET setup_state='editing' WHERE shelter_id=?", [(target,) for target in affected])
        return {"warehouse": warehouse_dto(stocks.reference(connection, "warehouses", "warehouse_id", warehouse_id)),
                "links": links_for(connection, warehouse_id),
                "affected_shelters": [stocks.dto(stocks.reference(connection, "shelters", "shelter_id", target)) for target in affected]}


def put_setup(connection, shelter_id, state):
    with db.transaction(connection):
        stocks.reference(connection, "shelters", "shelter_id", shelter_id)
        if state not in ("editing", "complete"):
            raise StockError("VALIDATION_ERROR", "設定中または完了を選択してください。", path="/setup_state")
        if state == "complete":
            snapshot = settings_snapshot(connection, shelter_id)
            blocking = [i for i in snapshot["issues"] if i["code"] in {
                "WAREHOUSE_MODE_MISSING", "DEDICATED_LINK_COUNT_INVALID", "ALLOCATION_LINK_INVALID"}]
            if blocking:
                raise StockError("INVALID_WAREHOUSE_LINKS", "倉庫対応・割当の矛盾を修正してください。", status=409, details={"issues": blocking})
        connection.execute("UPDATE shelters SET setup_state=? WHERE shelter_id=?", (state, shelter_id))
        return stocks.dto(stocks.reference(connection, "shelters", "shelter_id", shelter_id))


def list_allocations(connection, shelter_id, *, warehouse_id=None, limit=50, offset=0):
    with db.transaction(connection, write=False):
        stocks.reference(connection, "shelters", "shelter_id", shelter_id)
        where = "WHERE sw.shelter_id=? AND w.allocation_mode='shared' AND s.state='active'"
        params = [shelter_id]
        if warehouse_id is not None:
            where += " AND w.warehouse_id=?"
            params.append(warehouse_id)
        source = " FROM stocks s JOIN warehouses w USING(warehouse_id) JOIN shelter_warehouses sw USING(warehouse_id) "
        total = connection.execute("SELECT count(*)" + source + where, params).fetchone()[0]
        rows = connection.execute("SELECT s.stock_id" + source + where + " ORDER BY s.stock_id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        values = []
        base_date = stocks.today()
        for row in rows:
            selected = connection.execute("SELECT quantity FROM stock_allocations WHERE stock_id=? AND shelter_id=?", (row["stock_id"], shelter_id)).fetchone()
            values.append({"stock": stocks.view(connection, row["stock_id"], base_date),
                           "selected_allocation": stocks.decimal_text(selected[0]) if selected else "0"})
        return values, total


def put_allocation(connection, shelter_id, stock_id, amount):
    with db.transaction(connection):
        stocks.reference(connection, "shelters", "shelter_id", shelter_id)
        row = stocks.stock_row(connection, stock_id, active=True)
        warehouse = stocks.reference(connection, "warehouses", "warehouse_id", row["warehouse_id"])
        if warehouse["allocation_mode"] != "shared" or connection.execute(
            "SELECT 1 FROM shelter_warehouses WHERE warehouse_id=? AND shelter_id=?", (row["warehouse_id"], shelter_id),
        ).fetchone() is None:
            raise StockError("INVALID_WAREHOUSE_LINKS", "対応する共有倉庫の有効在庫だけを割り当てられます。", status=409)
        item = stocks.reference(connection, "items", "item_id", row["item_id"])
        number = stocks.stored_quantity(amount, item["is_divisible"], path="/quantity")
        total = Decimal(0)
        for allocation in connection.execute("SELECT quantity FROM stock_allocations WHERE stock_id=? AND shelter_id!=?", (stock_id, shelter_id)):
            total = stocks.add_quantities(total, allocation[0])
        total = stocks.add_quantities(total, amount)
        if total > Decimal(str(row["quantity"])):
            raise StockError("ALLOCATION_EXCEEDS_STOCK", "全避難所の割当合計が現在庫を超えます。割当数量を減らしてください。", status=409,
                             path="/quantity", details={"stock_id": str(stock_id), "allocated_total": stocks.decimal_text(total)})
        if number == 0:
            connection.execute("DELETE FROM stock_allocations WHERE stock_id=? AND shelter_id=?", (stock_id, shelter_id))
        else:
            changed = connection.execute("UPDATE stock_allocations SET quantity=? WHERE stock_id=? AND shelter_id=?", (number, stock_id, shelter_id)).rowcount
            if changed == 0:
                connection.execute("INSERT INTO stock_allocations(stock_id,shelter_id,quantity) VALUES(?,?,?)", (stock_id, shelter_id, number))
        current = stocks.view(connection, stock_id)
        return {"stock_id": str(stock_id), "shelter_id": str(shelter_id), "quantity": stocks.decimal_text(number),
                "allocated_total": current["allocated_total"], "unallocated_quantity": current["unallocated_quantity"]}
