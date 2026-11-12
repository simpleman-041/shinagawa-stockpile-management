"""当日備蓄計算と不変の手動保存。API 1.0 §6/7、TX08/09。"""

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_HALF_UP, localcontext

from app import db
from app.services.stocks import StockError, reference
from app.services.warehouse_settings import issue


FORMULA = "unfire-20261101-r1"
MAX_INTEGER = 9007199254740991
TABLES = {
    "groups": "calculation_group_results", "items": "calculation_item_snapshots",
    "warehouses": "calculation_warehouse_snapshots", "warehouse_links": "calculation_warehouse_links",
    "stocks": "calculation_stock_snapshots",
}
BOOLS = {"is_divisible", "has_unknown_expiry", "limits_people", "limits_days",
         "unknown_expiry_warning", "expires_in_period"}
DECIMALS = {"daily_usage", "reference_quantity", "required_quantity", "included_quantity",
            "covered_quantity", "shortage_quantity", "coverage_rate", "stock_quantity",
            "allocated_total", "selected_allocation", "converted_quantity"}
METRICS = ("required_quantity", "included_quantity", "covered_quantity", "shortage_quantity",
           "coverage_rate", "people", "days")


def now():
    return datetime.now(timezone.utc)


def instant(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class FrozenCalculation:
    """文字列にして可変参照を共有しない。ダイジェストは欠落・改変も検出する。"""
    source: str
    preview: str
    digest: str


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def number(value, *, positive=False):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise StockError("DATA_INTEGRITY_ERROR", "保存済み数量・基準が不正です。", status=500)
    return result


def real(value):
    """演算結果を黙ってREALへ丸めず、APIと保存値を一致させる。"""
    result = float(value)
    if not math.isfinite(result) or Decimal(str(result)) != value:
        raise StockError("NUMBER_NOT_REPRESENTABLE", "計算結果の数値範囲・精度を超えています。")
    return result


def dto(row):
    result = dict(row)
    for key, value in result.items():
        if value is None:
            continue
        if key.endswith("_id") or key == "factor_x100":
            result[key] = str(value)
        elif key in BOOLS:
            result[key] = bool(value)
        elif key in DECIMALS:
            result[key] = format(number(value), ".1f" if key == "coverage_rate" else ".2f")
    return result


def reason(issues):
    def order(value):
        # 数値IDを文字列順で並べない。Issueの列順も固定する。
        parts = "/".join(value["paths"]).split("/")
        return value["code"], tuple((0, int(p)) if p.isdecimal() else (1, p) for p in parts)
    return "\n".join(f'{v["code"]} {", ".join(v["paths"])}: {v["message"]}' for v in sorted(issues, key=order)) or None


def capture(connection, shelter_id, people=None, days=None):
    with db.transaction(connection, write=False):
        at = now()
        shelter = dict(reference(connection, "shelters", "shelter_id", shelter_id, path="/shelter_id"))
        people = shelter["target_people"] if people is None else people
        days = shelter["target_days"] if days is None else days
        if people is None or days is None:
            raise StockError("TARGET_NOT_SET", "正式目標を登録するか試算人数・日数を入力してください。", status=409)
        if any(type(v) is not int or not 1 <= v <= MAX_INTEGER for v in (people, days)):
            raise StockError("NUMBER_NOT_REPRESENTABLE", "登録済み目標の整数範囲を確認してください。")
        base = at.astimezone(timezone(timedelta(hours=9))).date()
        try:
            end = base + timedelta(days=days - 1)
        except OverflowError:
            raise StockError("NUMBER_NOT_REPRESENTABLE", "目標日数が日付の表現範囲を超えています。", path="/target_days") from None
        def rows(sql, args=()):
            return [dict(row) for row in connection.execute(sql, args)]
        groups = rows("SELECT * FROM demand_groups ORDER BY group_id")
        if not groups:
            raise StockError("CALCULATION_GROUPS_EMPTY", "需要条件を登録してから計算してください。", status=409)
        return {
            "header": {"shelter_id": shelter_id, "shelter_name": shelter["name"],
                       "target_people": people, "target_days": days, "base_date": base.isoformat(),
                       "calculated_at": instant(at), "formula_version": FORMULA, "setup_state": shelter["setup_state"]},
            "end_date": end.isoformat(), "groups": groups,
            "items": rows("SELECT i.item_id,i.name AS item_name,i.quantity_unit,i.is_divisible,i.registration_state,"
                          "ic.group_id,ic.factor_x100,ic.source_text,ic.version_or_date,ic.conditions "
                          "FROM items i JOIN item_conversions ic USING(item_id) ORDER BY i.item_id"),
            "warehouses": rows("SELECT w.warehouse_id,w.name AS warehouse_name,w.allocation_mode "
                               "FROM warehouses w JOIN shelter_warehouses sw USING(warehouse_id) WHERE sw.shelter_id=? ORDER BY w.warehouse_id", (shelter_id,)),
            "warehouse_links": rows("SELECT sw.warehouse_id,sw.shelter_id,s.name AS shelter_name FROM shelter_warehouses sw "
                                    "JOIN shelters s USING(shelter_id) WHERE sw.warehouse_id IN "
                                    "(SELECT warehouse_id FROM shelter_warehouses WHERE shelter_id=?) ORDER BY sw.warehouse_id,sw.shelter_id", (shelter_id,)),
            # 無効行への不正割当の検出にも使う。公開写しはactiveかつ明示所属品目だけ。
            "stocks": rows("SELECT s.stock_id,s.warehouse_id,s.item_id,s.quantity,s.expiry_state,s.expiry_date,s.state FROM stocks s WHERE s.warehouse_id IN "
                           "(SELECT warehouse_id FROM shelter_warehouses WHERE shelter_id=?) OR s.stock_id IN "
                           "(SELECT stock_id FROM stock_allocations WHERE shelter_id=?) ORDER BY s.stock_id", (shelter_id, shelter_id)),
            "allocations": rows("SELECT a.* FROM stock_allocations a JOIN stocks s USING(stock_id) "
                                "WHERE a.shelter_id=? OR s.warehouse_id IN (SELECT warehouse_id FROM shelter_warehouses WHERE shelter_id=?) "
                                "ORDER BY a.stock_id,a.shelter_id", (shelter_id, shelter_id)),
        }


def _evaluate(source):
    header = dict(source["header"])
    groups = {r["group_id"]: dict(r) for r in source["groups"]}
    items = {r["item_id"]: r for r in source["items"]}
    warehouses = {r["warehouse_id"]: r for r in source["warehouses"]}
    links = {wid: {r["shelter_id"] for r in source["warehouse_links"] if r["warehouse_id"] == wid} for wid in warehouses}
    issues = {gid: [] for gid in groups}
    shelter_id = header["shelter_id"]
    def add(gid, code, message, *paths):
        value = issue(code, message, *paths)
        if value not in issues[gid]:
            issues[gid].append(value)
    for gid, group in groups.items():
        prefix = f"/demand_groups/{gid}"
        if header["setup_state"] == "editing":
            add(gid, "SETUP_EDITING", "倉庫対応が設定中です。設定画面で確認・完了してください。", f"/shelters/{shelter_id}/setup_state")
        for field, code, label in (("calculation_unit", "GROUP_UNIT_MISSING", "計算単位"),
                                   ("is_divisible", "GROUP_DIVISIBILITY_MISSING", "分割可否"),
                                   ("daily_usage", "DAILY_USAGE_MISSING", "1人1日の使用量")):
            if group[field] is None:
                add(gid, code, f"{label}が未設定です。", prefix + "/" + field)
        missing = [prefix + "/" + f for f in ("source_text", "version_or_date", "conditions") if not group[f]]
        if missing:
            add(gid, "USAGE_SOURCE_MISSING", "使用量の出典・版・適用条件を設定してください。", *missing)
        members = [i for i in items.values() if i["group_id"] == gid]
        if not members:
            add(gid, "ITEM_CONVERSION_MISSING", "需要に品目を明示対応してください。", prefix)
        for item in members:
            ip = f'/item_conversions/{item["item_id"]}'
            if item["factor_x100"] is None:
                add(gid, "CONVERSION_FACTOR_MISSING", "換算係数が未設定です。", ip + "/factor_x100")
            missing = [ip + "/" + f for f in ("source_text", "version_or_date", "conditions") if not item[f]]
            if missing:
                add(gid, "CONVERSION_SOURCE_MISSING", "換算の出典・版・適用条件を設定してください。", *missing)
        for wid, warehouse in warehouses.items():
            wp = f"/warehouses/{wid}"
            if warehouse["allocation_mode"] is None:
                add(gid, "WAREHOUSE_MODE_MISSING", "倉庫の専用・共有を設定してください。", wp + "/allocation_mode")
            if warehouse["allocation_mode"] == "dedicated":
                if len(links[wid]) != 1:
                    add(gid, "DEDICATED_LINK_COUNT_INVALID", "専用倉庫の対応先が1件ではありません。", wp)
                if not any(s["state"] == "active" and s["warehouse_id"] == wid and s["item_id"] in {i["item_id"] for i in members} for s in source["stocks"]):
                    add(gid, "STOCK_UNREGISTERED", "専用倉庫にこの需要の有効在庫が未登録です。確認済み0も登録してください。", wp, prefix)

    snapshots = []
    for stock in source["stocks"]:
        item = items.get(stock["item_id"])
        allocations = [a for a in source["allocations"] if a["stock_id"] == stock["stock_id"]]
        quantity = number(stock["quantity"])
        total = sum((number(a["quantity"], positive=True) for a in allocations), Decimal(0))
        selected = sum((number(a["quantity"]) for a in allocations if a["shelter_id"] == shelter_id), Decimal(0))
        if total > quantity or selected > total:
            raise StockError("DATA_INTEGRITY_ERROR", "割当合計が在庫数量を超えています。割当を確認してください。", status=500)
        if item is None:
            continue
        gid, wid = item["group_id"], stock["warehouse_id"]
        warehouse = warehouses.get(wid)
        mode = warehouse["allocation_mode"] if warehouse else None
        invalid = any(stock["state"] != "active" or mode != "shared" or a["shelter_id"] not in links.get(wid, set()) for a in allocations)
        if invalid:
            add(gid, "ALLOCATION_LINK_INVALID", "在庫の状態・倉庫対応と割当が整合していません。", f'/stocks/{stock["stock_id"]}/allocations')
        if stock["state"] != "active" or warehouse is None:
            continue
        if quantity.as_tuple().exponent < -2 or (not item["is_divisible"] and quantity != quantity.to_integral_value()):
            raise StockError("DATA_INTEGRITY_ERROR", "在庫数量の精度・管理単位が不正です。", status=500)
        if any(number(a["quantity"]).as_tuple().exponent < -2 or (not item["is_divisible"] and number(a["quantity"]) != number(a["quantity"]).to_integral_value()) for a in allocations):
            invalid = True
            add(gid, "ALLOCATION_LINK_INVALID", "割当数量の精度・管理単位が不正です。", f'/stocks/{stock["stock_id"]}/allocations')
        expiry = stock["expiry_date"]
        if stock["expiry_state"] == "dated":
            try:
                date.fromisoformat(expiry)
            except (ValueError, TypeError):
                raise StockError("DATA_INTEGRITY_ERROR", "在庫の期限日が不正です。", status=500) from None
        unresolved = invalid or mode is None or (mode == "dedicated" and len(links[wid]) != 1)
        if unresolved:
            selection, included = "unresolved", Decimal(0)
        elif expiry is not None and expiry < header["base_date"]:
            selection, included = "expired", Decimal(0)
        elif mode == "shared" and selected == 0:
            selection, included = "unallocated", Decimal(0)
        elif mode == "dedicated":
            selection, included = "dedicated", quantity
        else:
            selection, included = "shared", selected
        # 係数だけあっても出典等が欠ける場合、正式指標は不可。写しには算術換算量を保持。
        converted = None if item["factor_x100"] is None else q2(included * Decimal(item["factor_x100"]) / 100)
        snapshots.append({"stock_id": stock["stock_id"], "item_id": stock["item_id"], "warehouse_id": wid,
                          "stock_quantity": quantity, "allocated_total": total, "selected_allocation": selected,
                          "expiry_state": stock["expiry_state"], "expiry_date": expiry,
                          "included_quantity": included, "converted_quantity": converted, "selection_reason": selection,
                          "unknown_expiry_warning": stock["expiry_state"] == "unconfirmed" and included > 0,
                          "expires_in_period": expiry is not None and header["base_date"] <= expiry <= source["end_date"]})

    results = []
    for gid, group in groups.items():
        own = [s for s in snapshots if items[s["item_id"]]["group_id"] == gid]
        confirmed = [s for s in own if s["selection_reason"] != "unresolved" and s["converted_quantity"] is not None
                     and all(items[s["item_id"]][f] is not None for f in ("source_text", "version_or_date", "conditions"))]
        # 対応倉庫0件と共有割当0は確認済み0。未登録の専用倉庫や換算欠損はnullと区別する。
        valid_members = [i for i in items.values() if i["group_id"] == gid and all(i[f] is not None for f in ("factor_x100", "source_text", "version_or_date", "conditions"))]
        known_zero = bool(valid_members) and (not warehouses or any(
            w["allocation_mode"] == "shared" and not any(
                s["warehouse_id"] == wid and s["state"] == "active" and s["item_id"] in {i["item_id"] for i in valid_members}
                for s in source["stocks"])
            for wid, w in warehouses.items()))
        amount = Decimal(0) if confirmed or known_zero else None
        for stock in confirmed:
            amount = q2(amount + stock["converted_quantity"])
        result = {"group_id": gid, "group_name": group["name"], **{f: group[f] for f in ("calculation_unit", "is_divisible", "daily_usage", "source_text", "version_or_date", "conditions")},
                  "reference_quantity": amount, "has_unknown_expiry": any(s["unknown_expiry_warning"] for s in own),
                  "limits_people": False, "limits_days": False, **dict.fromkeys(METRICS)}
        if not issues[gid]:
            usage = number(group["daily_usage"], positive=True)
            required = q2(Decimal(header["target_people"]) * header["target_days"] * usage)
            if not group["is_divisible"]:
                required = required.to_integral_value(rounding=ROUND_CEILING)
            pd, dd = q2(header["target_days"] * usage), q2(header["target_people"] * usage)
            if pd == 0 or dd == 0 or required == 0:
                add(gid, "ROUNDED_DENOMINATOR_ZERO", "丸め後の分母が0のため計算できません。使用量を確認してください。", f"/demand_groups/{gid}/daily_usage")
            else:
                amount = amount if amount is not None else Decimal(0)
                people, days = int(amount // pd), int(amount // dd)
                if max(people, days) > MAX_INTEGER:
                    raise StockError("NUMBER_NOT_REPRESENTABLE", "対応可能人数・日数が整数の表現範囲を超えています。")
                result.update(required_quantity=required, included_quantity=amount, covered_quantity=min(amount, required),
                              shortage_quantity=q2(max(required - amount, 0)),
                              coverage_rate=(amount / required * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), people=people, days=days)
        result.update(result_state="unavailable" if issues[gid] else "computed", unavailable_reason=reason(issues[gid]))
        results.append(result)
    computed = [r for r in results if r["result_state"] == "computed"]
    complete = len(computed) == len(results)
    all_issues = []
    for values in issues.values():
        for value in values:
            if value not in all_issues:
                all_issues.append(value)
    header.update(result_state="computed" if complete else "partial" if computed else "unavailable",
                  has_unknown_expiry=any(r["has_unknown_expiry"] for r in results),
                  min_people=min(r["people"] for r in results) if complete else None,
                  min_days=min(r["days"] for r in results) if complete else None,
                  unavailable_reason=reason(all_issues))
    if complete:
        for result in results:
            result.update(limits_people=result["people"] == header["min_people"], limits_days=result["days"] == header["min_days"])
    preview = {"header": dto(header), "groups": [dto(r) for r in results], "items": [dto(r) for r in items.values()],
               "warehouses": [dto(r) for r in warehouses.values()], "warehouse_links": [dto(r) for r in source["warehouse_links"]],
               "stocks": [dto(r) for r in snapshots], "issues": all_issues}
    for row in [*results, *snapshots]:
        for key, value in row.items():
            if key in DECIMALS and value is not None:
                real(number(value))
    return preview


def evaluate(source):
    try:
        with localcontext() as context:
            context.prec = 1000
            return _evaluate(source)
    except (DecimalException, OverflowError):
        raise StockError("NUMBER_NOT_REPRESENTABLE", "計算の表現範囲を超えています。") from None


def calculate(connection, shelter_id, people=None, days=None):
    source = encoded(capture(connection, shelter_id, people, days))
    preview = encoded(evaluate(json.loads(source)))
    return FrozenCalculation(source, preview, hashlib.sha256((source + preview).encode()).hexdigest())


def validate_frozen(frozen):
    try:
        if hashlib.sha256((frozen.source + frozen.preview).encode()).hexdigest() != frozen.digest:
            raise ValueError()
        source, preview = json.loads(frozen.source), json.loads(frozen.preview)
        for key, id_key in (("groups", "group_id"), ("items", "item_id"), ("warehouses", "warehouse_id"), ("stocks", "stock_id")):
            if len({r[id_key] for r in source[key]}) != len(source[key]):
                raise ValueError()
        link_keys = {(r["warehouse_id"], r["shelter_id"]) for r in source["warehouse_links"]}
        if len(link_keys) != len(source["warehouse_links"]):
            raise ValueError()
        if not source["groups"] or encoded(evaluate(source)) != frozen.preview:
            raise ValueError()
        gids = {r["group_id"] for r in preview["groups"]}
        iids = {r["item_id"] for r in preview["items"]}
        wids = {r["warehouse_id"] for r in preview["warehouses"]}
        if any(r["group_id"] not in gids for r in preview["items"]) or any(r["item_id"] not in iids or r["warehouse_id"] not in wids for r in preview["stocks"]):
            raise ValueError()
        if any(r["warehouse_id"] not in wids for r in preview["warehouse_links"]) or any(
                (wid, preview["header"]["shelter_id"]) not in {(r["warehouse_id"], r["shelter_id"]) for r in preview["warehouse_links"]}
                for wid in wids):
            raise ValueError()
        return preview
    except (ValueError, KeyError, TypeError, AttributeError, StockError):
        raise StockError("SNAPSHOT_INVALID", "保持した計算結果と根拠が不正です。再計算してください。", status=500) from None


def _saved(connection, run_id):
    run = reference(connection, "calculation_runs", "run_id", run_id)
    result = {"run": dto(run)}
    for key, table in TABLES.items():
        result[key] = [dto(r) for r in connection.execute(f"SELECT * FROM {table} WHERE run_id=? ORDER BY 2,3", (run_id,))]
    result["correction_run_ids"] = [str(r[0]) for r in connection.execute("SELECT run_id FROM calculation_runs WHERE correction_of_run_id=? ORDER BY run_id", (run_id,))]
    return result


def get_saved(connection, run_id):
    with db.transaction(connection, write=False):
        return _saved(connection, run_id)


def save(connection, frozen, correction=None):
    preview = validate_frozen(frozen)
    try:
        with db.transaction(connection):
            run_id = connection.execute("SELECT COALESCE(MAX(run_id),0)+1 FROM calculation_runs").fetchone()[0]
            if type(run_id) is not int or run_id > 9223372036854775807:
                raise StockError("NUMBER_NOT_REPRESENTABLE", "計算IDの範囲を超えています。")
            if correction is not None and (correction >= run_id or connection.execute("SELECT 1 FROM calculation_runs WHERE run_id=?", (correction,)).fetchone() is None):
                raise StockError("INVALID_CORRECTION", "訂正元には保存済みの既存計算IDを指定してください。", path="/correction_of_run_id")
            saved_at = instant(now())
            if saved_at < preview["header"]["calculated_at"]:
                raise StockError("SNAPSHOT_INVALID", "保存日時が計算日時より前です。サーバーの時刻を確認してください。", status=500)
            def insert(table, values):
                # 列と表はサーバーで生成・検証した固定DTOだけから取得する。
                values = {k: real(number(v)) if k in DECIMALS and v is not None else int(v) if (k.endswith("_id") or k == "factor_x100") and v is not None else v for k, v in values.items()}
                columns = ",".join(values)
                connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
            for key, table in TABLES.items():
                for row in preview[key]:
                    insert(table, {"run_id": run_id, **row})
                count = connection.execute(f"SELECT count(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0]
                if count != len(preview[key]):
                    raise StockError("SNAPSHOT_INVALID", "計算根拠の保存件数が一致しません。", status=500)
            insert("calculation_runs", {"run_id": run_id, **preview["header"], "saved_at": saved_at, "correction_of_run_id": correction})
            result = _saved(connection, run_id)
        return result
    except sqlite3.IntegrityError:
        raise StockError("SNAPSHOT_INVALID", "計算根拠を一括保存できませんでした。参照と整合性を確認してください。", status=500) from None


def list_saved(connection, *, limit=50, offset=0, **filters):
    clauses, args = [], []
    for key in ("shelter_id", "result_state"):
        if key in filters:
            clauses.append(f"{key}=?")
            args.append(filters[key])
    for key, op in (("from", ">="), ("to", "<")):
        if key in filters:
            clauses.append(f"calculated_at{op}?")
            args.append(filters[key])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db.transaction(connection, write=False):
        count = connection.execute("SELECT count(*) FROM calculation_runs" + where, args).fetchone()[0]
        values = connection.execute("SELECT * FROM calculation_runs" + where + " ORDER BY calculated_at DESC,run_id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        return [dto(r) for r in values], count
