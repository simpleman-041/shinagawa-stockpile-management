"""基本マスターで採用するAPI1.0の共通境界。既存の在庫API部品を共用する。"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from app.routes.stocks import body, contract_error, identifier, pagination, text, unexpected_error
from app.services.stocks import StockError, stored_quantity


def configure(blueprint, list_queries):
    blueprint.register_error_handler(StockError, contract_error)
    blueprint.register_error_handler(Exception, unexpected_error)

    @blueprint.before_request
    def validate_request():
        allowed = list_queries.get(request.endpoint.rsplit(".", 1)[-1], set())
        for key in request.args:
            path = "/query/" + key.replace("~", "~0").replace("/", "~1")
            if key not in allowed:
                raise StockError("UNKNOWN_FIELD", "未対応の検索条件です。", path=path)
            if len(request.args.getlist(key)) != 1:
                raise StockError("VALIDATION_ERROR", "検索条件は重複指定できません。", path=path)
        if request.method in ("GET", "HEAD") and request.get_data():
            raise StockError("INVALID_JSON", "取得要求には本文を指定できません。", status=400)
        for key, value in request.view_args.items():
            if key.endswith("_id"):
                request.view_args[key] = identifier(value, f"/path/{key}")


def read_body(required=(), optional=(), readonly=()):
    values = body(required, set(optional) | set(readonly))
    for key in sorted(set(values) & set(readonly)):
        raise StockError("READ_ONLY_FIELD", "この項目は読み取り専用です。", path=f"/{key}")
    return values


def decimal_value(value, path, *, nullable=False):
    if value is None and nullable:
        return None
    match = re.fullmatch(r"(0|[1-9][0-9]*)(?:\.([0-9]+))?", value) if isinstance(value, str) else None
    if match is None:
        raise StockError("VALIDATION_ERROR", "符号・指数なしの10進文字列を指定してください。", path=path)
    if len(match.group(2) or "") > 2:
        raise StockError("DECIMAL_PRECISION", "小数第2位まで指定してください。", path=path)
    try:
        value = Decimal(value)
    except (InvalidOperation, ValueError):
        raise StockError("NUMBER_NOT_REPRESENTABLE", "数値の表現範囲を超えています。", path=path) from None
    return stored_quantity(value, path=path)


def positive_integer(value, path, maximum=9007199254740991):
    if type(value) is not int or not 1 <= value <= maximum:
        raise StockError("INTEGER_REQUIRED", f"1以上{maximum}以下の整数を指定してください。", path=path)
    return value


def search_text():
    value = request.args.get("q")
    return None if value is None else text(value, "/query/q")


def found(value):
    if value is None:
        raise StockError("RESOURCE_NOT_FOUND", "指定された対象が見つかりません。", status=404)
    return value
