"""MV01〜04のHTTP境界。共通の在庫API検証・エラー表現を利用する。"""

import re
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request

from app import db
from app.routes.stocks import body, contract_error, identifier, list_response, pagination, text, unexpected_error
from app.services import movements as service
from app.services.stocks import StockError


movements_bp = Blueprint("movements", __name__)
movements_bp.register_error_handler(StockError, contract_error)
movements_bp.register_error_handler(Exception, unexpected_error)


def instant(value, path):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value) is None:
        raise StockError("VALIDATION_ERROR", "UTC日時をYYYY-MM-DDTHH:mm:ss.SSSZで指定してください。", path=path)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
            raise ValueError()
    except ValueError:
        raise StockError("VALIDATION_ERROR", "実在する日時を指定してください。", path=path) from None
    return value


@movements_bp.before_request
def validate_request():
    allowed = {"limit", "offset", "stock_id", "state", "kind", "from", "to"} if request.endpoint == "movements.movements_list" else set()
    for key in request.args:
        if key not in allowed:
            raise StockError("UNKNOWN_FIELD", "未対応の検索条件です。", path=f"/query/{key}")
        if len(request.args.getlist(key)) != 1:
            raise StockError("VALIDATION_ERROR", "検索条件の重複はできません。", path=f"/query/{key}")
    if request.method in ("GET", "HEAD") and request.get_data():
        raise StockError("INVALID_JSON", "取得要求には本文を指定できません。", status=400)


@movements_bp.get("/stock-movements")
def movements_list():
    limit, offset = pagination()
    filters = {}
    if "stock_id" in request.args:
        filters["stock_id"] = identifier(request.args["stock_id"], "/query/stock_id")
    for key, options in (("state", ("active", "cancelled")), ("kind", ("in", "out"))):
        if key in request.args:
            if request.args[key] not in options:
                raise StockError("VALIDATION_ERROR", "検索条件を確認してください。", path=f"/query/{key}")
            filters[key] = request.args[key]
    for key in ("from", "to"):
        if key in request.args:
            filters[key] = instant(request.args[key], f"/query/{key}")
    if "from" in filters and "to" in filters and filters["from"] >= filters["to"]:
        raise StockError("VALIDATION_ERROR", "終了日時は開始日時より後にしてください。", path="/query/to")
    values, total = service.list_movements(db.get_db(), limit=limit, offset=offset, **filters)
    return list_response(values, total, limit, offset)


@movements_bp.get("/stock-movements/<movement_id>")
def movement_detail(movement_id):
    return jsonify(data=service.get_movement(db.get_db(), identifier(movement_id, "/path/movement_id")))


@movements_bp.post("/stocks/<stock_id>/movements")
def movement_create(stock_id):
    stock_id = identifier(stock_id, "/path/stock_id")
    values = body(("kind", "quantity", "operator_id"), ("reason",))
    if values["kind"] not in ("in", "out"):
        raise StockError("VALIDATION_ERROR", "入庫・出庫を選択してください。", path="/kind")
    raw = values["quantity"]
    if not isinstance(raw, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", raw) is None:
        raise StockError("VALIDATION_ERROR", "数量は正の10進文字列にしてください。", path="/quantity")
    values["quantity"] = Decimal(raw)
    values["operator_id"] = identifier(values["operator_id"], "/operator_id")
    if "reason" in values:
        values["reason"] = text(values["reason"], "/reason", nullable=True)
    result = service.create_movement(db.get_db(), stock_id, values)
    response = jsonify(data=result)
    response.status_code = 201
    response.headers["Location"] = f'/api/v1/stock-movements/{result["movement"]["movement_id"]}'
    return response


@movements_bp.post("/stock-movements/<movement_id>/cancellation")
def movement_cancel(movement_id):
    movement_id = identifier(movement_id, "/path/movement_id")
    values = body(("operator_id",))
    return jsonify(data=service.cancel_movement(db.get_db(), movement_id, identifier(values["operator_id"], "/operator_id")))
