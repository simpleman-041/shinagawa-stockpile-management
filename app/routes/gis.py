"""GISの読取APIと版付きデータ配信。"""

from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from app import db
from app.routes.stocks import contract_error, identifier, unexpected_error
from app.services import gis as service
from app.services.stocks import StockError
from app.services.warehouse_summary import summary


gis_bp = Blueprint("gis", __name__)
gis_bp.register_error_handler(StockError, contract_error)
gis_bp.register_error_handler(Exception, unexpected_error)


def init_app(app):
    app.config.setdefault("GIS_DATA_ROOT", Path(app.root_path).parent / "data" / "gis")
    app.config.setdefault("GIS_CURRENT_DATASET", "shinagawa-census2020-v1")
    app.register_blueprint(gis_bp)


@gis_bp.before_request
def validate_request():
    if request.args:
        key = next(iter(request.args))
        raise StockError("UNKNOWN_FIELD", "地図APIには検索クエリーを指定できません。", path=f"/query/{key}")
    if request.get_data():
        raise StockError("INVALID_JSON", "取得要求には本文を指定できません。", status=400)


@gis_bp.get("/api/v1/gis/warehouses")
def warehouses():
    return jsonify(data=service.warehouses(db.get_db()))


@gis_bp.get("/api/v1/gis/datasets/current")
def current():
    data, _ = service.load_dataset(current_app.config["GIS_DATA_ROOT"], current_app.config["GIS_CURRENT_DATASET"])
    response = jsonify(data=data)
    response.headers["Cache-Control"] = "no-store"
    return response


@gis_bp.get("/gis/<dataset_id>/<filename>")
def dataset_file(dataset_id, filename):
    if filename not in service.FILES:
        raise StockError("RESOURCE_NOT_FOUND", "指定された地図ファイルはありません。", status=404)
    _, raw = service.load_dataset(current_app.config["GIS_DATA_ROOT"], dataset_id)
    return Response(raw[filename], content_type=service.FILES[filename], headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


@gis_bp.get("/api/v1/warehouses/<warehouse_id>/summary")
def warehouse_summary(warehouse_id):
    return jsonify(data=summary(db.get_db(), identifier(warehouse_id, "/path/warehouse_id")))
