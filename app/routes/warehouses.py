"""WH01〜04・TH01/02。API1.0の基本マスター契約。"""

import math
from decimal import Decimal

from flask import Blueprint, jsonify, request, url_for

from app import db
from app.routes.master_contract import configure, decimal_value, found, pagination, read_body, search_text, text
from app.services import warehouses as service
from app.services.master_values import threshold_dto, warehouse_dto
from app.services.stocks import StockError

warehouses_bp = Blueprint("warehouses", __name__)
configure(warehouses_bp, {
    "get_warehouses": {"q", "coordinates", "limit", "offset"},
    "get_warehouse_thresholds": {"limit", "offset"},
})
_FIELDS = {"name", "facility_type", "address", "latitude", "longitude", "capacity_m3"}
_REQUIRED = {"name", "facility_type", "address"}
_READONLY = {"warehouse_id", "allocation_mode"}


def _values(create):
    values = read_body(_REQUIRED if create else (), _FIELDS, _READONLY)
    if not values:
        raise StockError("VALIDATION_ERROR", "編集する項目を指定してください。")
    for key in _REQUIRED & values.keys():
        text(values[key], f"/{key}")
    if "capacity_m3" in values:
        values["capacity_m3"] = decimal_value(values["capacity_m3"], "/capacity_m3", nullable=True)
    for key, bound in (("latitude", 90), ("longitude", 180)):
        if key in values and values[key] is not None:
            value = values[key]
            if type(value) not in (int, float) or not -bound <= value <= bound or not math.isfinite(value):
                raise StockError("VALIDATION_ERROR", f"{key}は-{bound}以上{bound}以下の有限数値にしてください。", path=f"/{key}")
    if create and (values.get("latitude") is None) != (values.get("longitude") is None):
        raise StockError("VALIDATION_ERROR", "緯度と経度は両方数値または両方nullにしてください。", path="/latitude")
    return values


@warehouses_bp.get("/warehouses")
def get_warehouses():
    limit, offset = pagination()
    coordinates = request.args.get("coordinates")
    if coordinates not in (None, "known", "missing"):
        raise StockError("VALIDATION_ERROR", "knownまたはmissingを指定してください。", path="/query/coordinates")
    rows, total = service.list_warehouses(db.get_db(), q=search_text(), coordinates=coordinates, limit=limit, offset=offset)
    return jsonify(data=[warehouse_dto(row) for row in rows], page={"limit": limit, "offset": offset, "total": total})


@warehouses_bp.post("/warehouses")
def post_warehouses():
    values = _values(True)
    connection = db.get_db()
    warehouse_id = service.post_warehouse(connection, **values)
    response = jsonify(data=warehouse_dto(service.get_warehouse(connection, warehouse_id)))
    response.status_code = 201
    response.headers["Location"] = url_for("warehouses.get_warehouse_detail", warehouse_id=warehouse_id)
    return response


@warehouses_bp.get("/warehouses/<warehouse_id>")
def get_warehouse_detail(warehouse_id):
    return jsonify(data=warehouse_dto(found(service.get_warehouse(db.get_db(), warehouse_id))))


@warehouses_bp.patch("/warehouses/<warehouse_id>")
def patch_warehouses(warehouse_id):
    values = _values(False)
    return jsonify(data=warehouse_dto(found(service.patch_warehouse(db.get_db(), warehouse_id, values))))


@warehouses_bp.get("/warehouses/<warehouse_id>/thresholds")
def get_warehouse_thresholds(warehouse_id):
    limit, offset = pagination()
    connection = db.get_db()
    found(service.get_warehouse(connection, warehouse_id))
    rows, total = service.list_thresholds(connection, warehouse_id, limit=limit, offset=offset)
    return jsonify(data=[threshold_dto(row) for row in rows], page={"limit": limit, "offset": offset, "total": total})


@warehouses_bp.put("/warehouses/<warehouse_id>/thresholds/<item_id>")
def put_warehouse_threshold(warehouse_id, item_id):
    values = read_body({"minimum_quantity"})
    value = decimal_value(values["minimum_quantity"], "/minimum_quantity")
    try:
        threshold, created = service.put_threshold(db.get_db(), warehouse_id, item_id, Decimal(str(value)))
    except service.ThresholdUnitError:
        raise StockError("INTEGER_REQUIRED", "分割不可の品目の基準は整数にしてください。", path="/minimum_quantity") from None
    response = jsonify(data=threshold_dto(found(threshold)))
    response.status_code = 201 if created else 200
    return response
