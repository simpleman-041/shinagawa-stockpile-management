"""需要条件と品目換算を、既存の在庫・保存済み計算を変えずに管理する。"""

import math
from decimal import Decimal

from app import db


GROUP_FIELDS = (
    "name", "calculation_unit", "is_divisible", "daily_usage",
    "source_text", "version_or_date", "conditions",
)
CONVERSION_FIELDS = ("factor_x100", "source_text", "version_or_date", "conditions")
MAX_REAL = Decimal("1.7976931348623157e308")


class DemandGroupError(Exception):
    """HTTP層へ伝える、契約で定めた入力・参照・整合性エラー。"""

    def __init__(self, code, message, *, status=422, path=None, details=None):
        """エラーコード・HTTP状態・入力位置・補足情報をHTTP層向けに保持する。"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = [] if path is None else [
            {"path": path, "code": code, "message": message}
        ]
        self.details = details or {}


def _group_dto(row):
    """DB行をAPI表現へ変換し、保存済み使用量の不正な値・精度を検出する。"""
    group = dict(row)
    group["group_id"] = str(group["group_id"])
    if group["is_divisible"] is not None:
        group["is_divisible"] = bool(group["is_divisible"])
    if group["daily_usage"] is not None:
        usage = Decimal(str(group["daily_usage"]))
        text = format(usage, "f")
        if not usage.is_finite() or usage <= 0 or len(text.partition(".")[2].rstrip("0")) > 2:
            raise DemandGroupError(
                "DATA_INTEGRITY_ERROR", "保存済み使用量の値・精度を確認してください。", status=500
            )
        group["daily_usage"] = format(usage, ".2f")
    return group


def _conversion_dto(row):
    """換算行のIDを文字列化し、100倍整数から丸めずに表示係数を作る。"""
    conversion = dict(row)
    conversion["item_id"] = str(conversion["item_id"])
    conversion["group_id"] = str(conversion["group_id"])
    factor = conversion["factor_x100"]
    conversion["factor_x100"] = None if factor is None else str(factor)
    # 整数のまま分解し、大きな係数にも浮動小数・Decimalの丸めを入れない。
    conversion["factor"] = None if factor is None else f"{factor // 100}.{factor % 100:02d}"
    return conversion


def _get_group(connection, group_id):
    """呼出元の接続で需要を取得し、不存在なら404に対応する例外を送出する。"""
    row = connection.execute(
        "SELECT * FROM demand_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        raise DemandGroupError(
            "RESOURCE_NOT_FOUND", "指定された需要グループが見つかりません。", status=404
        )
    return _group_dto(row)


def _conditions(connection, group_id):
    """呼出元のトランザクション内で需要と品目ID順の全所属換算を読む。"""
    group = _get_group(connection, group_id)
    conversions = connection.execute(
        "SELECT * FROM item_conversions WHERE group_id = ? ORDER BY item_id", (group_id,)
    ).fetchall()
    return {"group": group, "conversions": [_conversion_dto(row) for row in conversions]}


def _group_values(group, *, path=""):
    """使用量と分割可否を同時に検証し、入力の十進値を保つREALへ変換する。"""
    values = dict(group)
    usage = values["daily_usage"]
    if usage is not None:
        if values["is_divisible"] is False and usage != usage.to_integral_value():
            raise DemandGroupError(
                "INTEGER_REQUIRED", "分割不可の共通単位では使用量を整数にしてください。",
                path=f"{path}/daily_usage",
            )
        real = float(usage)
        if not math.isfinite(real) or usage > MAX_REAL or Decimal(str(real)) != usage:
            raise DemandGroupError(
                "NUMBER_NOT_REPRESENTABLE", "使用量をDBへ正確に保存できません。値を確認してください。",
                path=f"{path}/daily_usage",
            )
        values["daily_usage"] = real
    if values["is_divisible"] is not None:
        values["is_divisible"] = int(values["is_divisible"])
    return tuple(values[field] for field in GROUP_FIELDS)


def _write_conversion(connection, item_id, group_id, conversion, *, exists):
    """既存行を削除せず更新し、未登録なら追加する。commitは呼出元が担う。"""
    values = tuple(conversion[field] for field in CONVERSION_FIELDS)
    if exists:
        connection.execute(
            "UPDATE item_conversions SET group_id = ?, factor_x100 = ?, "
            "source_text = ?, version_or_date = ?, conditions = ? WHERE item_id = ?",
            (group_id, *values, item_id),
        )
    else:
        connection.execute(
            "INSERT INTO item_conversions "
            "(item_id, group_id, factor_x100, source_text, version_or_date, conditions) "
            "VALUES (?, ?, ?, ?, ?, ?)", (item_id, group_id, *values),
        )


def list_groups(connection, *, limit=50, offset=0):
    """同一の読取トランザクションで一覧と総件数を取得する。"""
    with db.transaction(connection, write=False):
        total = connection.execute("SELECT count(*) FROM demand_groups").fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM demand_groups ORDER BY group_id LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [_group_dto(row) for row in rows], total


def create_group(connection, group):
    """使用量の保存条件を検証して需要を登録し、確定前に応答用の値を取得する。"""
    with db.transaction(connection):
        values = _group_values(group)
        cursor = connection.execute(
            "INSERT INTO demand_groups "
            "(name, calculation_unit, is_divisible, daily_usage, source_text, version_or_date, conditions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", values,
        )
        return _get_group(connection, cursor.lastrowid)


def get_conditions(connection, group_id):
    """需要と全所属換算を同じ時点のデータとして読み取る。"""
    with db.transaction(connection, write=False):
        return _conditions(connection, group_id)


def replace_conditions(connection, group_id, group, conversions):
    """全所属の欠落・重複・暗黙移動を拒否し、需要と換算を一括保存する。

    参照確認から更新まで書込トランザクションで保護し、失敗時は全件取り消す。
    """
    with db.transaction(connection):
        _get_group(connection, group_id)
        current = {
            row[0] for row in connection.execute(
                "SELECT item_id FROM item_conversions WHERE group_id = ?", (group_id,)
            )
        }
        submitted = [entry["item_id"] for entry in conversions]
        if len(set(submitted)) != len(submitted) or not current.issubset(submitted):
            raise DemandGroupError(
                "INCOMPLETE_CONVERSION_SET", "現在の所属品目を重複なく全件指定してください。",
                path="/conversions",
            )
        for index, entry in enumerate(conversions):
            path = f"/conversions/{index}/item_id"
            if connection.execute("SELECT 1 FROM items WHERE item_id = ?", (entry["item_id"],)).fetchone() is None:
                raise DemandGroupError(
                    "REFERENCE_NOT_FOUND", "指定された品目が見つかりません。", path=path
                )
            other = connection.execute(
                "SELECT group_id FROM item_conversions WHERE item_id = ?", (entry["item_id"],)
            ).fetchone()
            if other is not None and other[0] != group_id:
                raise DemandGroupError(
                    "INCOMPLETE_CONVERSION_SET",
                    "他の需要へ所属する品目の移動には品目換算設定APIを使用してください。", path=path,
                )
        values = _group_values(group, path="/group")
        connection.execute(
            "UPDATE demand_groups SET name = ?, calculation_unit = ?, is_divisible = ?, "
            "daily_usage = ?, source_text = ?, version_or_date = ?, conditions = ? WHERE group_id = ?",
            (*values, group_id),
        )
        for entry in conversions:
            _write_conversion(connection, entry["item_id"], group_id, entry, exists=entry["item_id"] in current)
        return _conditions(connection, group_id)


def set_item_conversion(connection, item_id, group_id, conversion):
    """品目と需要の実在を確認し、1品目1需要の対応を設定・明示移動する。

    応答用の換算値と、新規登録かどうかを返す。登録終了品目も対象とする。
    """
    with db.transaction(connection):
        if connection.execute("SELECT 1 FROM items WHERE item_id = ?", (item_id,)).fetchone() is None:
            raise DemandGroupError("RESOURCE_NOT_FOUND", "指定された品目が見つかりません。", status=404)
        if connection.execute("SELECT 1 FROM demand_groups WHERE group_id = ?", (group_id,)).fetchone() is None:
            raise DemandGroupError("REFERENCE_NOT_FOUND", "指定された需要グループが見つかりません。", path="/group_id")
        exists = connection.execute(
            "SELECT 1 FROM item_conversions WHERE item_id = ?", (item_id,)
        ).fetchone() is not None
        _write_conversion(connection, item_id, group_id, conversion, exists=exists)
        row = connection.execute("SELECT * FROM item_conversions WHERE item_id = ?", (item_id,)).fetchone()
        return _conversion_dto(row), not exists
