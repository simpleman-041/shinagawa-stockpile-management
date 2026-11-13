"""IT01〜05。API1.0の基本マスター契約。"""

from flask import Blueprint, jsonify, request, url_for

from app import db
from app.routes.master_contract import configure, decimal_value, found, pagination, positive_integer, read_body, search_text, text
from app.routes.stocks import error_response
from app.services import items as service
from app.services.stocks import StockError

items_bp = Blueprint("items", __name__)
configure(items_bp, {"get_items": {"q", "registration_state", "limit", "offset"}})
_FIELDS = {"name", "category", "quantity_unit", "unit_volume_m3", "is_divisible", "near_expiry_days"}
_REQUIRED = _FIELDS - {"unit_volume_m3"}
_READONLY = {"item_id", "registration_state"}


def _values(create):
    values = read_body(_REQUIRED if create else (), _FIELDS, _READONLY)
    if not values:
        raise StockError("VALIDATION_ERROR", "編集する項目を指定してください。")
    for key in {"name", "category", "quantity_unit"} & values.keys():
        text(values[key], f"/{key}")
    if "unit_volume_m3" in values:
        values["unit_volume_m3"] = decimal_value(values["unit_volume_m3"], "/unit_volume_m3", nullable=True)
    if "is_divisible" in values and type(values["is_divisible"]) is not bool:
        raise StockError("VALIDATION_ERROR", "分割可否はtrueまたはfalseを指定してください。", path="/is_divisible")
    if "near_expiry_days" in values:
        positive_integer(values["near_expiry_days"], "/near_expiry_days", maximum=3650)
    return values


@items_bp.get("/items")
def get_items():
    limit, offset = pagination()
    state = request.args.get("registration_state")
    if state not in (None, "active", "closed"):
        raise StockError("VALIDATION_ERROR", "activeまたはclosedを指定してください。", path="/query/registration_state")
    rows, total = service.list_items(db.get_db(), q=search_text(), registration_state=state, limit=limit, offset=offset)
    return jsonify(data=rows, page={"limit": limit, "offset": offset, "total": total})


@items_bp.post("/items")
def post_items():
    values = _values(True)
    connection = db.get_db()
    item_id = service.post_item(connection, **values)
    response = jsonify(data=service.get_item(connection, item_id))
    response.status_code = 201
    response.headers["Location"] = url_for("items.get_item_detail", item_id=item_id)
    return response


@items_bp.get("/items/<item_id>")
def get_item_detail(item_id):
    return jsonify(data=found(service.get_item(db.get_db(), item_id)))


@items_bp.patch("/items/<item_id>")
def patch_items(item_id):
    values = _values(False)
    try:
        item = service.patch_item(db.get_db(), item_id, values)
    except service.ItemConflict as conflict:
        return error_response(conflict.code, conflict.message, 409, details=conflict.details)
    return jsonify(data=found(item))


@items_bp.post("/items/<item_id>/closure")
def close_items(item_id):
    read_body()
    return jsonify(data=found(service.close_item(db.get_db(), item_id)))
