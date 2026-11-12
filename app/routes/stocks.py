"""ST01〜09、履歴、警告、事前登録職員の在庫管理用HTTP境界。"""

import copy
import json
import re
import secrets
import sqlite3
from datetime import date
from decimal import Decimal
from threading import RLock

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from app import db
from app.services import stocks as service
from app.services.stocks import StockError


stocks_bp = Blueprint("stocks", __name__)


def error_response(code, message, status, fields=None, details=None):
    return jsonify(error={"code": code, "message": message, "fields": fields or [],
                          "details": details or {}, "retryable": code == "STORAGE_BUSY"}), status


@stocks_bp.errorhandler(StockError)
def contract_error(error):
    return error_response(error.code, error.message, error.status, error.fields, error.details)


@stocks_bp.errorhandler(Exception)
def unexpected_error(error):
    if isinstance(error, BadRequest):
        return error_response("INVALID_JSON", "要求本文を確認してください。", 400)
    if isinstance(error, sqlite3.IntegrityError):
        return error_response("DATA_INTEGRITY_ERROR", "DBの整合性を確認してください。", 500)
    if isinstance(error, sqlite3.Error):
        code = getattr(error, "sqlite_errorcode", 0) & 255
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return error_response("STORAGE_BUSY", "DBが使用中です。結果確認後に再操作してください。", 503)
        if code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL,
                    sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM):
            return error_response("STORAGE_UNAVAILABLE", "DBを利用できません。接続先を確認してください。", 503)
    if isinstance(error, OSError):
        return error_response("STORAGE_UNAVAILABLE", "保存先を利用できません。", 503)
    current_app.logger.error("在庫APIの処理に失敗しました。")
    return error_response("INTERNAL_ERROR", "処理に失敗しました。更新結果を確認してください。", 500)


def identifier(value, path):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise StockError("VALIDATION_ERROR", "IDは正の整数文字列にしてください。", path=path)
    if len(value) > 19 or (len(value) == 19 and value > "9223372036854775807"):
        raise StockError("NUMBER_NOT_REPRESENTABLE", "IDの範囲を超えています。", path=path)
    return int(value)


def text(value, path, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip() or not value.strip(" ").split("\x00", 1)[0]:
        raise StockError("VALIDATION_ERROR", "空でない文字列を入力してください。", path=path)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise StockError("VALIDATION_ERROR", "UTF-8の文字列を入力してください。", path=path) from None
    return value


def body(required, optional=()):
    if request.mimetype != "application/json":
        raise StockError("UNSUPPORTED_MEDIA_TYPE", "application/jsonを指定してください。", status=415)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("invalid constant")
    try:
        value = json.loads(request.get_data().decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(value, dict):
            raise ValueError("not object")
    except (ValueError, UnicodeError, RecursionError):
        raise StockError("INVALID_JSON", "重複のないJSONオブジェクトを指定してください。", status=400) from None
    for key in value.keys() - set(required) - set(optional):
        code = "READ_ONLY_FIELD" if key in {"quantity", "state", "stock_id", "merge_generation", "merged_at", "merged_by", "merged_into_stock_id"} else "UNKNOWN_FIELD"
        raise StockError(code, "この項目は指定できません。", path="/" + key.replace("~", "~0").replace("/", "~1"))
    for key in set(required) - value.keys():
        raise StockError("VALIDATION_ERROR", "必須項目を入力してください。", path=f"/{key}")
    return value


def expiry(values):
    state, value = values["expiry_state"], values["expiry_date"]
    if state not in ("dated", "none", "unconfirmed"):
        raise StockError("VALIDATION_ERROR", "期限状態を選択してください。", path="/expiry_state")
    if state != "dated":
        if value is not None:
            raise StockError("VALIDATION_ERROR", "期限不要・未確認では日付はnullにしてください。", path="/expiry_date")
    else:
        try:
            if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                raise ValueError()
            date.fromisoformat(value)
        except ValueError:
            raise StockError("VALIDATION_ERROR", "実在する日付をYYYY-MM-DDで入力してください。", path="/expiry_date") from None


def pagination():
    values = []
    for key, default, minimum, maximum in (("limit", 50, 1, 200), ("offset", 0, 0, 9007199254740991)):
        value = request.args.get(key, str(default))
        if not re.fullmatch(r"[0-9]+", value) or len(value.lstrip("0")) > 16:
            raise StockError("VALIDATION_ERROR", "ページ指定を確認してください。", path=f"/query/{key}")
        number = int(value.lstrip("0") or "0")
        if not minimum <= number <= maximum:
            raise StockError("VALIDATION_ERROR", "ページ指定が範囲外です。", path=f"/query/{key}")
        values.append(number)
    return values


@stocks_bp.before_request
def validate_request():
    allowed = set()
    if request.endpoint in ("stocks.stocks_list", "stocks.events", "stocks.operators"):
        allowed.update(("limit", "offset"))
    if request.endpoint == "stocks.stocks_list":
        allowed.update(("warehouse_id", "item_id", "state", "expiry_status", "q"))
    for key in request.args:
        if key not in allowed:
            raise StockError("UNKNOWN_FIELD", "未対応の検索条件です。", path=f"/query/{key}")
        if len(request.args.getlist(key)) != 1:
            raise StockError("VALIDATION_ERROR", "検索条件の重複はできません。", path=f"/query/{key}")
    if request.method in ("GET", "HEAD") and request.get_data():
        raise StockError("INVALID_JSON", "取得要求の本文を確認してください。", status=400)


def list_response(values, total, limit, offset):
    return jsonify(data=values, page={"limit": limit, "offset": offset, "total": total})


@stocks_bp.get("/stocks")
def stocks_list():
    limit, offset = pagination()
    filters = {}
    for key in ("warehouse_id", "item_id"):
        if key in request.args:
            filters[key] = identifier(request.args[key], f"/query/{key}")
    for key, options in (("state", ("active", "deleted", "merged")),
                         ("expiry_status", ("valid", "near", "expired", "none", "unconfirmed"))):
        if key in request.args:
            if request.args[key] not in options:
                raise StockError("VALIDATION_ERROR", "検索状態を確認してください。", path=f"/query/{key}")
            filters[key] = request.args[key]
    if "q" in request.args:
        filters["q"] = text(request.args["q"], "/query/q")
    values, total = service.list_stocks(db.get_db(), limit=limit, offset=offset, **filters)
    return list_response(values, total, limit, offset)


@stocks_bp.post("/stocks")
def stocks_create():
    values = body(("warehouse_id", "item_id", "location", "initial_quantity", "expiry_state", "expiry_date"), ("operator_id", "reason"))
    for key in ("warehouse_id", "item_id", "operator_id"):
        if key in values:
            values[key] = identifier(values[key], f"/{key}")
    values["location"] = text(values["location"], "/location")
    if "reason" in values:
        values["reason"] = text(values["reason"], "/reason", nullable=True)
    raw = values["initial_quantity"]
    if not isinstance(raw, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", raw):
        raise StockError("VALIDATION_ERROR", "数量は0以上の10進文字列にしてください。", path="/initial_quantity")
    values["initial_quantity"] = Decimal(raw)
    expiry(values)
    result = service.create_stock(db.get_db(), values)
    response = jsonify(data=result)
    response.status_code = 200 if result["reused_existing"] else 201
    response.headers["Location"] = f'/api/v1/stocks/{result["stock"]["stock"]["stock_id"]}'
    return response


@stocks_bp.get("/stocks/<stock_id>")
def stock_detail(stock_id):
    return jsonify(data=service.get_stock(db.get_db(), identifier(stock_id, "/path/stock_id")))


@stocks_bp.patch("/stocks/<stock_id>")
def stock_patch(stock_id):
    stock_id = identifier(stock_id, "/path/stock_id")
    values = body(("location",))
    return jsonify(data=service.change_location(db.get_db(), stock_id, text(values["location"], "/location")))


@stocks_bp.post("/stocks/<stock_id>/logical-deletion")
@stocks_bp.post("/stocks/<stock_id>/restoration")
def stock_state(stock_id):
    stock_id = identifier(stock_id, "/path/stock_id")
    values = body(("operator_id", "confirmed"))
    if values["confirmed"] is not True:
        raise StockError("VALIDATION_ERROR", "表示内容を確認してください。", path="/confirmed")
    return jsonify(data=service.change_state(db.get_db(), stock_id, identifier(values["operator_id"], "/operator_id"),
                                             restore=request.path.endswith("/restoration")))


@stocks_bp.put("/stocks/<stock_id>/expiry")
def stock_expiry(stock_id):
    stock_id = identifier(stock_id, "/path/stock_id")
    values = body(("expiry_state", "expiry_date", "operator_id"))
    expiry(values)
    return jsonify(data=service.change_expiry(db.get_db(), stock_id, values["expiry_state"], values["expiry_date"],
                                              identifier(values["operator_id"], "/operator_id")))


@stocks_bp.get("/stocks/<stock_id>/state-events")
@stocks_bp.get("/stocks/<stock_id>/expiry-changes")
def events(stock_id):
    limit, offset = pagination()
    values, total = service.history(db.get_db(), identifier(stock_id, "/path/stock_id"), request.path.rsplit("/", 1)[1], limit, offset)
    return list_response(values, total, limit, offset)


@stocks_bp.get("/operators")
def operators():
    limit, offset = pagination()
    with db.transaction(db.get_db(), write=False) as connection:
        total = connection.execute("SELECT count(*) FROM operators").fetchone()[0]
        values = [{"operator_id": str(row[0]), "name": row[1]} for row in connection.execute(
            "SELECT operator_id,name FROM operators ORDER BY operator_id LIMIT ? OFFSET ?", (limit, offset))]
    return list_response(values, total, limit, offset)


@stocks_bp.get("/stock-alerts")
def alerts():
    values, _ = service.list_stocks(db.get_db(), limit=9007199254740991)
    return jsonify(data={"base_date": values[0]["base_date"] if values else service.today().isoformat(),
                         "expired_count": sum(v["expiry_status"] == "expired" for v in values),
                         "near_expiry_count": sum(v["expiry_status"] == "near" for v in values),
                         "unconfirmed_count": sum(v["expiry_status"] == "unconfirmed" for v in values),
                         "filters": {key: {"state": "active", "expiry_status": status} for key, status in
                                     (("expired", "expired"), ("near", "near"), ("unconfirmed", "unconfirmed"))}})


@stocks_bp.post("/stock-merges/preview")
def merge_preview():
    values = body(("source_stock_id", "target_stock_id"))
    snapshot = service.preview_merge(db.get_db(), identifier(values["source_stock_id"], "/source_stock_id"),
                                     identifier(values["target_stock_id"], "/target_stock_id"))
    token = secrets.token_urlsafe(32)
    store = current_app.extensions["stock_merges"]
    with store["lock"]:
        store["tokens"][token] = {"snapshot": copy.deepcopy(snapshot), "completed": False}
    return jsonify(data={"preview_token": token, **snapshot})


@stocks_bp.post("/stock-merges")
def merge_execute():
    values = body(("preview_token", "operator_id", "confirmed"))
    token = text(values["preview_token"], "/preview_token")
    operator_id = identifier(values["operator_id"], "/operator_id")
    if values["confirmed"] is not True:
        raise StockError("VALIDATION_ERROR", "プレビューを確認してください。", path="/confirmed")
    store = current_app.extensions["stock_merges"]
    with store["lock"]:
        entry = store["tokens"].get(token)
        if entry is None:
            raise StockError("PREVIEW_UNAVAILABLE", "プレビューが失われました。再確認してください。", status=409)
        snapshot = entry["snapshot"]
        if entry["completed"]:
            with db.transaction(db.get_db(), write=False) as connection:
                service.reference(connection, "operators", "operator_id", operator_id, path="/operator_id")
                result = {key: service.view(connection, int(snapshot[key]["stock"]["stock_id"])) for key in ("source", "target")}
        else:
            result = service.execute_merge(db.get_db(), snapshot, operator_id)
            entry["completed"] = True
    return jsonify(data=result)


def init_app(app):
    app.extensions["stock_merges"] = {"tokens": {}, "lock": RLock()}
    app.register_blueprint(stocks_bp, url_prefix="/api/v1")
