"""SH06〜08・AL01/02のHTTP境界。"""

import re
from decimal import Decimal

from flask import Blueprint, jsonify, request

from app import db
from app.routes.stocks import body, contract_error, identifier, list_response, pagination, unexpected_error
from app.services import warehouse_settings as service
from app.services.stocks import StockError


warehouse_settings_bp = Blueprint("warehouse_settings", __name__)
warehouse_settings_bp.register_error_handler(StockError, contract_error)
warehouse_settings_bp.register_error_handler(Exception, unexpected_error)


@warehouse_settings_bp.before_request
def validate_request():
    allowed = {"limit", "offset", "warehouse_id"} if request.endpoint == "warehouse_settings.allocations" else set()
    for key in request.args:
        if key not in allowed:
            raise StockError("UNKNOWN_FIELD", "未対応の検索条件です。", path=f"/query/{key}")
        if len(request.args.getlist(key)) != 1:
            raise StockError("VALIDATION_ERROR", "検索条件の重複はできません。", path=f"/query/{key}")
    if request.method in ("GET", "HEAD") and request.get_data():
        raise StockError("INVALID_JSON", "取得要求には本文を指定できません。", status=400)


@warehouse_settings_bp.get("/shelters/<shelter_id>/warehouse-settings")
def settings(shelter_id):
    return jsonify(data=service.get_settings(db.get_db(), identifier(shelter_id, "/path/shelter_id")))


@warehouse_settings_bp.put("/shelters/<shelter_id>/warehouse-settings/warehouses/<warehouse_id>")
def warehouse_setting(shelter_id, warehouse_id):
    shelter_id = identifier(shelter_id, "/path/shelter_id")
    warehouse_id = identifier(warehouse_id, "/path/warehouse_id")
    values = body(("allocation_mode", "shelter_ids"))
    if values["allocation_mode"] not in ("dedicated", "shared"):
        raise StockError("VALIDATION_ERROR", "専用または共有を選択してください。", path="/allocation_mode")
    if not isinstance(values["shelter_ids"], list):
        raise StockError("VALIDATION_ERROR", "対応避難所はIDの配列で指定してください。", path="/shelter_ids")
    targets = [identifier(value, f"/shelter_ids/{index}") for index, value in enumerate(values["shelter_ids"])]
    return jsonify(data=service.put_warehouse(db.get_db(), shelter_id, warehouse_id, values["allocation_mode"], targets))


@warehouse_settings_bp.put("/shelters/<shelter_id>/warehouse-setup")
def setup(shelter_id):
    shelter_id = identifier(shelter_id, "/path/shelter_id")
    values = body(("setup_state",))
    if values["setup_state"] not in ("editing", "complete"):
        raise StockError("VALIDATION_ERROR", "設定中または完了を選択してください。", path="/setup_state")
    return jsonify(data=service.put_setup(db.get_db(), shelter_id, values["setup_state"]))


@warehouse_settings_bp.get("/shelters/<shelter_id>/allocations")
def allocations(shelter_id):
    shelter_id = identifier(shelter_id, "/path/shelter_id")
    limit, offset = pagination()
    warehouse_id = identifier(request.args["warehouse_id"], "/query/warehouse_id") if "warehouse_id" in request.args else None
    values, total = service.list_allocations(db.get_db(), shelter_id, warehouse_id=warehouse_id, limit=limit, offset=offset)
    return list_response(values, total, limit, offset)


@warehouse_settings_bp.put("/shelters/<shelter_id>/allocations/<stock_id>")
def allocation(shelter_id, stock_id):
    shelter_id = identifier(shelter_id, "/path/shelter_id")
    stock_id = identifier(stock_id, "/path/stock_id")
    values = body(("quantity",))
    raw = values["quantity"]
    if not isinstance(raw, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", raw) is None:
        raise StockError("VALIDATION_ERROR", "数量は0以上の10進文字列にしてください。", path="/quantity")
    try:
        amount = Decimal(raw)
    except ValueError:
        raise StockError("NUMBER_NOT_REPRESENTABLE", "数量の表現範囲を超えています。", path="/quantity") from None
    return jsonify(data=service.put_allocation(db.get_db(), shelter_id, stock_id, amount))
