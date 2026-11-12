"""CA01/02・CR01〜03のHTTP境界とプロセス内計算保持。"""

import json
import re
import secrets
from datetime import datetime
from threading import RLock

from flask import Blueprint, current_app, jsonify, request

from app import db
from app.routes.stocks import body, contract_error, identifier, list_response, pagination, text, unexpected_error
from app.services import calculations as service
from app.services.stocks import StockError


calculations_bp = Blueprint("calculations", __name__)
calculations_bp.register_error_handler(StockError, contract_error)
calculations_bp.register_error_handler(Exception, unexpected_error)


def init_app(app):
    app.extensions["calculations"] = {"lock": RLock(), "entries": {}}
    app.register_blueprint(calculations_bp, url_prefix="/api/v1")


@calculations_bp.before_request
def validate_request():
    allowed = {"limit", "offset", "shelter_id", "result_state", "from", "to"} if request.endpoint == "calculations.history" else set()
    for key in request.args:
        if key not in allowed:
            raise StockError("UNKNOWN_FIELD", "未対応の検索条件です。", path=f"/query/{key}")
        if len(request.args.getlist(key)) != 1:
            raise StockError("VALIDATION_ERROR", "検索条件を重複指定できません。", path=f"/query/{key}")
    if request.method in ("GET", "HEAD") and request.get_data():
        raise StockError("INVALID_JSON", "取得要求には本文を指定できません。", status=400)


def entry(token):
    store = current_app.extensions["calculations"]
    with store["lock"]:
        value = store["entries"].get(token)
    if value is None:
        raise StockError("CALCULATION_TOKEN_UNAVAILABLE", "未保存の計算結果を保持していません。再計算してください。", status=409)
    return value


@calculations_bp.post("/calculations")
def calculate():
    values = body(("shelter_id",), ("target_people", "target_days"))
    shelter_id = identifier(values["shelter_id"], "/shelter_id")
    if ("target_people" in values) != ("target_days" in values):
        raise StockError("VALIDATION_ERROR", "試算人数と日数は両方入力してください。", path="/target_people")
    for key in ("target_people", "target_days"):
        if key in values:
            value = values[key]
            if type(value) is not int or value < 1:
                raise StockError("VALIDATION_ERROR", "1以上のJSON整数を指定してください。", path=f"/{key}")
            if value > service.MAX_INTEGER:
                raise StockError("NUMBER_NOT_REPRESENTABLE", "整数の表現範囲を超えています。", path=f"/{key}")
    frozen = service.calculate(db.get_db(), shelter_id, values.get("target_people"), values.get("target_days"))
    token = secrets.token_urlsafe(32)
    store = current_app.extensions["calculations"]
    with store["lock"]:
        store["entries"][token] = {"frozen": frozen, "lock": RLock(), "saved": None}
    return jsonify(data={"calculation_token": token, **json.loads(frozen.preview)})


@calculations_bp.get("/calculations/<token>")
def preview(token):
    value = entry(token)
    return jsonify(data={"calculation_token": token, **service.validate_frozen(value["frozen"])})


@calculations_bp.post("/calculation-runs")
def save():
    values = body(("calculation_token",), ("correction_of_run_id",))
    token = text(values["calculation_token"], "/calculation_token")
    correction = values.get("correction_of_run_id")
    if correction is not None:
        correction = identifier(correction, "/correction_of_run_id")
    value = entry(token)
    with value["lock"]:
        if value["saved"] is not None:
            run_id, original_correction = value["saved"]
            if correction != original_correction:
                raise StockError("TOKEN_ALREADY_SAVED", "この結果は別の訂正元指定で保存済みです。保存履歴を確認してください。", status=409)
            return jsonify(data=service.get_saved(db.get_db(), run_id)), 200
        result = service.save(db.get_db(), value["frozen"], correction)
        run_id = int(result["run"]["run_id"])
        value["saved"] = (run_id, correction)
    response = jsonify(data=result)
    response.status_code = 201
    response.headers["Location"] = f"/api/v1/calculation-runs/{run_id}"
    return response


@calculations_bp.get("/calculation-runs")
def history():
    limit, offset = pagination()
    filters = {}
    if "shelter_id" in request.args:
        filters["shelter_id"] = identifier(request.args["shelter_id"], "/query/shelter_id")
    if "result_state" in request.args:
        state = request.args["result_state"]
        if state not in ("computed", "partial", "unavailable"):
            raise StockError("VALIDATION_ERROR", "計算結果の状態を指定してください。", path="/query/result_state")
        filters["result_state"] = state
    for key in ("from", "to"):
        if key in request.args:
            value = request.args[key]
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value):
                    raise ValueError()
                datetime.fromisoformat(value)
            except ValueError:
                raise StockError("VALIDATION_ERROR", "日時はUTCのYYYY-MM-DDTHH:mm:ss.SSSZで指定してください。", path=f"/query/{key}") from None
            filters[key] = value
    if "from" in filters and "to" in filters and filters["from"] >= filters["to"]:
        raise StockError("VALIDATION_ERROR", "開始日時は終了日時より前にしてください。", path="/query/to")
    values, total = service.list_saved(db.get_db(), limit=limit, offset=offset, **filters)
    return list_response(values, total, limit, offset)


@calculations_bp.get("/calculation-runs/<run_id>")
def saved(run_id):
    return jsonify(data=service.get_saved(db.get_db(), identifier(run_id, "/path/run_id")))
