"""公開倉庫台帳と、専用DB向けの演習データを投入する。"""

import argparse
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from unicodedata import normalize

from app import db
from app.services import stocks


CATALOG = Path(__file__).resolve().parents[1] / "data/demo/shinagawa-stockpile-catalog.json"
DEMO_OPERATOR = "演習デモ初期投入担当"
DEMO_REASON = "演習用の架空在庫を初期投入"


def comparison_key(value):
    return "".join(normalize("NFKC", value).split())


def insert_warehouses(connection, catalog):
    current = connection.execute("SELECT name, address FROM warehouses").fetchall()
    names = {comparison_key(row["name"]) for row in current}
    addresses = {
        comparison_key(row["address"]).removeprefix("東京都").removeprefix("品川区")
        for row in current
    }
    inserted, preserved = {}, []
    for warehouse in catalog:
        name = comparison_key(warehouse["name"])
        address = comparison_key(warehouse["address"]).removeprefix("東京都").removeprefix("品川区")
        if name in names or address in addresses:
            preserved.append(warehouse["name"])
            continue
        latitude, longitude = warehouse.get("coordinates", (None, None))
        inserted[warehouse["number"]] = connection.execute(
            "INSERT INTO warehouses(name, facility_type, address, latitude, longitude) VALUES(?,?,?,?,?)",
            (warehouse["name"], warehouse.get("facility_type", "災害対策備蓄倉庫"),
             warehouse["address"], latitude, longitude),
        ).lastrowid
        names.add(name)
        addresses.add(address)
    return inserted, preserved


def demo_stock(connection, warehouse, item, label, quantity, expiry_day, operator, timestamp):
    divisible = connection.execute("SELECT is_divisible FROM items WHERE item_id=?", (item,)).fetchone()[0]
    amount = stocks.stored_quantity(quantity, divisible)
    stock_id = connection.execute(
        "INSERT INTO stocks(warehouse_id,item_id,location,quantity,expiry_state,expiry_date) VALUES(?,?,?,0,?,?)",
        (warehouse, item, f"演習用・{label}", "dated" if expiry_day else "none", expiry_day.isoformat() if expiry_day else None),
    ).lastrowid
    if amount > 0:
        connection.execute("UPDATE stocks SET quantity=? WHERE stock_id=?", (amount, stock_id))
        connection.execute(
            """INSERT INTO stock_movements(stock_id,operator_id,operator_name,kind,quantity,registered_at,reason,merge_generation)
               VALUES(?,?,?,'in',?,?,?,0)""",
            (stock_id, operator, DEMO_OPERATOR, amount, timestamp, DEMO_REASON),
        )
    return stock_id


def insert_demo(connection, catalog, warehouses):
    base_day = stocks.today()
    timestamp = stocks.timestamp()
    near = base_day + timedelta(days=3)
    valid = base_day + timedelta(days=365)
    expired = base_day - timedelta(days=1)

    operator = connection.execute("INSERT INTO operators(name) VALUES(?)", (DEMO_OPERATOR,)).lastrowid
    shelter_a, shelter_b = [
        connection.execute(
            "INSERT INTO shelters(name,address,target_people,target_days) VALUES(?,?,100,2)",
            (name, "演習用の所在地"),
        ).lastrowid
        for name in ("演習避難所A（架空）", "演習避難所B（架空）")
    ]
    dedicated, shared = warehouses[2], warehouses[6]
    connection.executemany("UPDATE warehouses SET allocation_mode=? WHERE warehouse_id=?", (
        ("dedicated", dedicated), ("shared", shared),
    ))
    connection.executemany("INSERT INTO shelter_warehouses(shelter_id,warehouse_id) VALUES(?,?)", (
        (shelter_a, dedicated), (shelter_a, shared), (shelter_b, shared),
    ))
    test_warehouse = connection.execute(
        "INSERT INTO warehouses(name,facility_type,address,capacity_m3) VALUES(?,?,?,1)",
        ("演習用容量検証倉庫（架空）", "演習用施設", "演習用の所在地"),
    ).lastrowid

    items = {}
    for item in catalog:
        items[item["name"]] = connection.execute(
            "INSERT INTO items(name,category,quantity_unit,is_divisible,near_expiry_days) VALUES(?,?,?,?,7)",
            (item["name"], item["category"], item["unit"], item["unit"] == "L"),
        ).lastrowid
    test_item = connection.execute(
        "INSERT INTO items(name,category,quantity_unit,is_divisible,near_expiry_days,unit_volume_m3) VALUES(?,?,?,0,7,0.2)",
        ("演習用容積箱（架空）", "演習用品目", "箱"),
    ).lastrowid
    food = items["アルファ化米"]
    water = items["ミネラルウォーター（飲料水）"]
    toilet = items["携帯トイレ（便袋タイプ）"]
    basis = "演習用の架空基準"
    condition = "大学演習の動作検証専用"
    for name, unit, divisible, daily, item_id in (
        ("食料", "食", 0, 3, food), ("飲料水", "L", 1, 3, water), ("携帯トイレ", "回", 0, 5, toilet),
    ):
        group = connection.execute(
            """INSERT INTO demand_groups(name,calculation_unit,is_divisible,daily_usage,source_text,version_or_date,conditions)
               VALUES(?,?,?,?,?,'演習1',?)""",
            (name, unit, divisible, daily, basis, condition),
        ).lastrowid
        connection.execute(
            "INSERT INTO item_conversions(item_id,group_id,factor_x100,source_text,version_or_date,conditions) VALUES(?,?,100,?,'演習1',?)",
            (item_id, group, basis, condition),
        )

    samples = (
        (dedicated, food, "棚A1 通常期限", "600", valid),
        (dedicated, food, "棚A2 期限接近", "60", near),
        (dedicated, food, "棚A3 期限切れ", "100", expired),
        (dedicated, water, "棚A4 飲料水", "450", valid),
        (dedicated, toilet, "棚A5 携帯トイレ", "1000", valid),
        (shared, food, "棚B1 数量ゼロ", "0", valid),
        (shared, water, "棚B2 共有分", "200", valid),
        (test_warehouse, test_item, "棚C1 容量超過", "10", None),
    )
    stock_ids = [demo_stock(connection, *sample, operator, timestamp) for sample in samples]
    connection.executemany("INSERT INTO stock_allocations(stock_id,shelter_id,quantity) VALUES(?,?,?)", (
        (stock_ids[6], shelter_a, 100), (stock_ids[6], shelter_b, 50),
    ))
    connection.executemany("INSERT INTO stock_thresholds(warehouse_id,item_id,minimum_quantity) VALUES(?,?,?)", (
        (dedicated, food, 500), (dedicated, water, 500),
    ))
    connection.execute("UPDATE shelters SET setup_state='complete' WHERE shelter_id IN (?,?)", (shelter_a, shelter_b))
    return len(items) + 1, len(stock_ids)


def seed_database(connection, *, demo=False):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    with db.transaction(connection):
        db.check_database(connection)
        if demo:
            if connection.execute("SELECT 1 FROM operators WHERE name=?", (DEMO_OPERATOR,)).fetchone():
                return {"already_seeded": True, "warehouses": 0, "preserved": [], "items": 0, "stocks": 0}
            # 演習の対応付け・必須設定値を利用中のDBへ混ぜない。
            if any(connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in (
                "warehouses", "items", "shelters", "operators", "demand_groups",
            )):
                raise ValueError("演習データの初回投入は、空の専用DBを指定してください。")

        warehouses, preserved = insert_warehouses(connection, catalog["warehouses"])
        item_count, stock_count = insert_demo(connection, catalog["items"], warehouses) if demo else (0, 0)
        db.check_database(connection)
        return {"already_seeded": False, "warehouses": len(warehouses) + int(demo),
                "preserved": preserved, "items": item_count, "stocks": stock_count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="初期化済みSQLiteファイル")
    parser.add_argument("--demo", action="store_true", help="専用DB向けの演習在庫・計算条件を含める")
    args = parser.parse_args()
    try:
        with closing(db.connect_db(args.database)) as connection:
            result = seed_database(connection, demo=args.demo)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"投入できませんでした: {error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
