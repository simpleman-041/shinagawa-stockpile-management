"""避難所に関するJSON API。"""

from flask import Blueprint, jsonify, request, url_for
from werkzeug.exceptions import BadRequest

from app import db
from app.services.shelters import (
    get_shelter,
    list_shelters,
    patch_shelter,
    post_shelter,
    put_setup_state,
    put_targets,
)


shelters_bp = Blueprint("shelters", __name__)
_SHELTER_FIELDS = {"name", "address", "target_people", "target_days"}
_PATCH_FIELDS = {"name", "address"}
_ALLOWED_QUERY_KEYS = {"q", "limit", "offset"}


def _error_response(code, message, *, status, fields=None, details=None):
    return jsonify(
        error={
            "code": code,
            "message": message,
            "fields": fields or [],
            "details": details or {},
            "retryable": False,
        }
    ), status


def _field(path, code, message):
    return {"path": path, "code": code, "message": message}


def _json_object():
    if not request.is_json:
        return None, _error_response(
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type に application/json を指定してください。",
            status=415,
        )
    try:
        body = request.get_json()
    except BadRequest:
        return None, _error_response("INVALID_JSON", "JSONを解析できません。", status=400)
    if not isinstance(body, dict):
        return None, _error_response(
            "INVALID_JSON",
            "JSONのトップレベルにはオブジェクトを指定してください。",
            status=400,
        )
    return body, None


def _text_error(body, field, *, required):
    if field not in body:
        return _field(f"/body/{field}", "REQUIRED", "必須項目です。") if required else None
    if not isinstance(body[field], str) or not body[field].strip():
        return _field(f"/body/{field}", "TEXT_REQUIRED", "空でない文字列を指定してください。")
    return None


def _positive_integer_error(body, field):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return _field(f"/body/{field}", "INTEGER_REQUIRED", "1以上の整数を指定してください。")
    if value < 1 or value > 9007199254740991:
        return _field(f"/body/{field}", "OUT_OF_RANGE", "1以上の整数を指定してください。")
    return None


def _validate_create(body):
    unknown = sorted(set(body) - _SHELTER_FIELDS)
    if unknown:
        return _error_response(
            "UNKNOWN_FIELD",
            f"未対応の本文フィールド {unknown[0]} は指定できません。",
            status=422,
            fields=[_field(f"/body/{unknown[0]}", "UNKNOWN_FIELD", "未対応の項目です。")],
        )
    for field in ("name", "address"):
        error = _text_error(body, field, required=True)
        if error:
            return _error_response("VALIDATION_ERROR", "避難所情報の入力が不正です。", status=422, fields=[error])
    people_present = "target_people" in body
    days_present = "target_days" in body
    if people_present != days_present:
        return _error_response(
            "VALIDATION_ERROR",
            "正式目標の人数と日数は両方指定してください。",
            status=422,
            fields=[_field("/body", "TARGET_PAIR_REQUIRED", "人数と日数は対で指定してください。")],
        )
    if people_present:
        for field in ("target_people", "target_days"):
            error = _positive_integer_error(body, field)
            if error:
                return _error_response("VALIDATION_ERROR", "正式目標の入力が不正です。", status=422, fields=[error])
    return None


def _validate_patch(body):
    unknown = sorted(set(body) - _PATCH_FIELDS)
    if unknown:
        return _error_response(
            "UNKNOWN_FIELD",
            f"未対応の本文フィールド {unknown[0]} は指定できません。",
            status=422,
            fields=[_field(f"/body/{unknown[0]}", "UNKNOWN_FIELD", "未対応の項目です。")],
        )
    if not body:
        return _error_response(
            "VALIDATION_ERROR", "編集する項目を1つ以上指定してください。", status=422,
            fields=[_field("/body", "EMPTY_OBJECT", "空のオブジェクトは指定できません。")],
        )
    for field in _PATCH_FIELDS:
        if field in body:
            error = _text_error(body, field, required=True)
            if error:
                return _error_response("VALIDATION_ERROR", "避難所情報の入力が不正です。", status=422, fields=[error])
    return None


def _query_value(name):
    values = request.args.getlist(name)
    if len(values) > 1:
        return None, _error_response(
            "VALIDATION_ERROR", f"クエリー {name} は1回だけ指定してください。", status=422,
            fields=[_field(f"/query/{name}", "DUPLICATE", "重複指定はできません。")],
        )
    return (values[0] if values else None), None


def _pagination(name, raw, default, minimum, maximum=None):
    if raw is None:
        return default, None
    if not raw.isdecimal():
        return None, _error_response(
            "VALIDATION_ERROR", f"クエリー {name} は整数で指定してください。", status=422,
            fields=[_field(f"/query/{name}", "INTEGER_REQUIRED", "整数を指定してください。")],
        )
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        return None, _error_response(
            "VALIDATION_ERROR", f"クエリー {name} の範囲が不正です。", status=422,
            fields=[_field(f"/query/{name}", "OUT_OF_RANGE", "指定可能な範囲を確認してください。")],
        )
    return value, None


@shelters_bp.get("/shelters")
def get_shelters():
    unknown = set(request.args) - _ALLOWED_QUERY_KEYS
    if unknown:
        name = sorted(unknown)[0]
        return _error_response(
            "UNKNOWN_FIELD", f"未対応のクエリー {name} は指定できません。", status=422,
            fields=[_field(f"/query/{name}", "UNKNOWN_FIELD", "未対応のクエリーです。")],
        )
    q, error = _query_value("q")
    if error:
        return error
    if q == "":
        return _error_response("VALIDATION_ERROR", "クエリー q は空にできません。", status=422)
    limit_raw, error = _query_value("limit")
    if error:
        return error
    limit, error = _pagination("limit", limit_raw, 50, 1, 200)
    if error:
        return error
    offset_raw, error = _query_value("offset")
    if error:
        return error
    offset, error = _pagination("offset", offset_raw, 0, 0)
    if error:
        return error
    try:
        rows, total = list_shelters(db.get_db(), q=q, limit=limit, offset=offset)
    except Exception:
        return _error_response("INTERNAL_ERROR", "避難所一覧を取得できませんでした。", status=500)
    return jsonify(data=rows, page={"limit": limit, "offset": offset, "total": total})


@shelters_bp.post("/shelters")
def post_shelters():
    body, error = _json_object()
    if error:
        return error
    error = _validate_create(body)
    if error:
        return error
    try:
        shelter_id = post_shelter(
            db.get_db(),
            name=body["name"],
            address=body["address"],
            target_people=body.get("target_people"),
            target_days=body.get("target_days"),
        )
        shelter = get_shelter(db.get_db(), shelter_id)
    except Exception:
        return _error_response("INTERNAL_ERROR", "避難所を登録できませんでした。", status=500)
    response = jsonify(data=shelter)
    response.status_code = 201
    response.headers["Location"] = url_for("shelters.get_shelter_detail", shelter_id=shelter_id)
    return response


@shelters_bp.get("/shelters/<int:shelter_id>")
def get_shelter_detail(shelter_id):
    shelter = get_shelter(db.get_db(), shelter_id)
    if shelter is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された避難所が見つかりません。", status=404)
    return jsonify(data=shelter)


@shelters_bp.patch("/shelters/<int:shelter_id>")
def patch_shelters(shelter_id):
    body, error = _json_object()
    if error:
        return error
    error = _validate_patch(body)
    if error:
        return error
    try:
        shelter = patch_shelter(db.get_db(), shelter_id, body)
    except Exception:
        return _error_response("INTERNAL_ERROR", "避難所を更新できませんでした。", status=500)
    if shelter is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された避難所が見つかりません。", status=404)
    return jsonify(data=shelter)


@shelters_bp.put("/shelters/<int:shelter_id>/targets")
def put_shelter_targets(shelter_id):
    body, error = _json_object()
    if error:
        return error
    if set(body) != {"target_people", "target_days"}:
        return _error_response(
            "UNKNOWN_FIELD", "正式目標には人数と日数だけを指定してください。", status=422,
            fields=[_field("/body", "TARGET_FIELDS_REQUIRED", "人数と日数を指定してください。")],
        )
    for field in ("target_people", "target_days"):
        error = _positive_integer_error(body, field)
        if error:
            return _error_response("VALIDATION_ERROR", "正式目標の入力が不正です。", status=422, fields=[error])
    try:
        shelter = put_targets(
            db.get_db(),
            shelter_id,
            target_people=body["target_people"],
            target_days=body["target_days"],
        )
    except Exception:
        return _error_response("INTERNAL_ERROR", "正式目標を更新できませんでした。", status=500)
    if shelter is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された避難所が見つかりません。", status=404)
    return jsonify(data=shelter)


@shelters_bp.put("/shelters/<int:shelter_id>/warehouse-setup")
def put_shelter_setup(shelter_id):
    body, error = _json_object()
    if error:
        return error
    if set(body) != {"setup_state"} or body["setup_state"] not in {"editing", "complete"}:
        return _error_response(
            "VALIDATION_ERROR", "setup_stateはeditingまたはcompleteで指定してください。", status=422,
            fields=[_field("/body/setup_state", "ENUM", "editingまたはcompleteを指定してください。")],
        )
    try:
        shelter = put_setup_state(db.get_db(), shelter_id, setup_state=body["setup_state"])
    except Exception:
        return _error_response("INTERNAL_ERROR", "設定状態を更新できませんでした。", status=500)
    if shelter is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された避難所が見つかりません。", status=404)
    return jsonify(data=shelter)
