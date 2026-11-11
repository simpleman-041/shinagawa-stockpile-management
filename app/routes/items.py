"""品目に関するJSON API。"""

import math
import re
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request, url_for
from werkzeug.exceptions import BadRequest

from app import db
from app.services.items import ItemConflict, close_item, get_item, list_items, patch_item, post_item


items_bp = Blueprint("items", __name__)

_ALLOWED_QUERY_KEYS = {"q", "registration_state", "limit", "offset"}
_ITEM_FIELDS = {
    "name",
    "category",
    "quantity_unit",
    "unit_volume_m3",
    "is_divisible",
    "near_expiry_days",
}
_REQUIRED_CREATE_FIELDS = {
    "name",
    "category",
    "quantity_unit",
    "is_divisible",
    "near_expiry_days",
}
_DECIMAL_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$")
_MAX_REAL = Decimal("1.7976931348623157e308")


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


def _validate_text(body, field, *, required):
    if field not in body:
        return _field(f"/body/{field}", "REQUIRED", "必須項目です。") if required else None
    if not isinstance(body[field], str) or not body[field].strip():
        return _field(f"/body/{field}", "TEXT_REQUIRED", "空でない文字列を指定してください。")
    return None


def _validate_decimal(body, field):
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str) or not _DECIMAL_PATTERN.fullmatch(value):
        return _field(
            f"/body/{field}",
            "DECIMAL_REQUIRED",
            "小数第2位までの10進文字列を指定してください。",
        )
    try:
        decimal_value = Decimal(value)
    except InvalidOperation:
        return _field(f"/body/{field}", "DECIMAL_REQUIRED", "有効な数値を指定してください。")
    if decimal_value < 0 or decimal_value > _MAX_REAL:
        return _field(f"/body/{field}", "OUT_OF_RANGE", "0以上の値を指定してください。")
    try:
        float_value = float(decimal_value)
    except OverflowError:
        return _field(f"/body/{field}", "OUT_OF_RANGE", "値が大きすぎます。")
    if not math.isfinite(float_value):
        return _field(f"/body/{field}", "OUT_OF_RANGE", "有限の値を指定してください。")
    return None


def _validate_body(body, *, create):
    unknown = sorted(set(body) - _ITEM_FIELDS)
    if unknown:
        return None, _error_response(
            "UNKNOWN_FIELD",
            f"未対応の本文フィールド {unknown[0]} は指定できません。",
            status=422,
            fields=[_field(f"/body/{unknown[0]}", "UNKNOWN_FIELD", "未対応の項目です。")],
        )
    if create:
        missing = sorted(_REQUIRED_CREATE_FIELDS - set(body))
        if missing:
            return None, _error_response(
                "VALIDATION_ERROR",
                f"必須項目 {missing[0]} がありません。",
                status=422,
                fields=[_field(f"/body/{missing[0]}", "REQUIRED", "必須項目です。")],
            )
    elif not body:
        return None, _error_response(
            "VALIDATION_ERROR",
            "PATCHする項目を1つ以上指定してください。",
            status=422,
            fields=[_field("/body", "EMPTY_OBJECT", "空のオブジェクトは指定できません。")],
        )

    for field in ("name", "category", "quantity_unit"):
        error = _validate_text(body, field, required=create)
        if error:
            return None, _error_response(
                "VALIDATION_ERROR", "品目情報の入力が不正です。", status=422, fields=[error]
            )

    if "unit_volume_m3" in body:
        error = _validate_decimal(body, "unit_volume_m3")
        if error:
            return None, _error_response(
                "VALIDATION_ERROR", "品目情報の入力が不正です。", status=422, fields=[error]
            )

    if "is_divisible" in body and not isinstance(body["is_divisible"], bool):
        return None, _error_response(
            "VALIDATION_ERROR",
            "分割可否にはtrueまたはfalseを指定してください。",
            status=422,
            fields=[_field("/body/is_divisible", "BOOLEAN_REQUIRED", "真偽値を指定してください。")],
        )

    if "near_expiry_days" in body:
        value = body["near_expiry_days"]
        if isinstance(value, bool) or not isinstance(value, int):
            error = _field("/body/near_expiry_days", "INTEGER_REQUIRED", "整数を指定してください。")
        elif not 1 <= value <= 3650:
            error = _field("/body/near_expiry_days", "OUT_OF_RANGE", "1以上3650以下で指定してください。")
        else:
            error = None
        if error:
            return None, _error_response(
                "VALIDATION_ERROR", "品目情報の入力が不正です。", status=422, fields=[error]
            )

    normalized = dict(body)
    if "unit_volume_m3" in normalized and normalized["unit_volume_m3"] is not None:
        normalized["unit_volume_m3"] = float(Decimal(normalized["unit_volume_m3"]))
    return normalized, None


def _query_value(name):
    values = request.args.getlist(name)
    if len(values) > 1:
        return None, _error_response(
            "VALIDATION_ERROR",
            f"クエリー {name} は1回だけ指定してください。",
            status=422,
            fields=[_field(f"/query/{name}", "DUPLICATE", "重複指定はできません。")],
        )
    return (values[0] if values else None), None


def _pagination(name, raw, default, minimum, maximum=None):
    if raw is None:
        return default, None
    if not raw.isdecimal():
        return None, _error_response(
            "VALIDATION_ERROR",
            f"クエリー {name} は10進整数で指定してください。",
            status=422,
            fields=[_field(f"/query/{name}", "INTEGER_REQUIRED", "整数を指定してください。")],
        )
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        return None, _error_response(
            "VALIDATION_ERROR",
            f"クエリー {name} の範囲が不正です。",
            status=422,
            fields=[_field(f"/query/{name}", "OUT_OF_RANGE", "指定可能な範囲を確認してください。")],
        )
    return value, None


@items_bp.get("/items")
def get_items():
    unknown = set(request.args) - _ALLOWED_QUERY_KEYS
    if unknown:
        name = sorted(unknown)[0]
        return _error_response(
            "UNKNOWN_FIELD",
            f"未対応のクエリー {name} は指定できません。",
            status=422,
            fields=[_field(f"/query/{name}", "UNKNOWN_FIELD", "未対応のクエリーです。")],
        )

    q, error = _query_value("q")
    if error:
        return error
    if q == "":
        return _error_response(
            "VALIDATION_ERROR", "クエリー q は空にできません。", status=422,
            fields=[_field("/query/q", "EMPTY", "空でない文字列を指定してください。")],
        )
    state, error = _query_value("registration_state")
    if error:
        return error
    if state not in (None, "active", "closed"):
        return _error_response(
            "VALIDATION_ERROR", "registration_state はactiveまたはclosedで指定してください。", status=422,
            fields=[_field("/query/registration_state", "ENUM", "activeまたはclosedを指定してください。")],
        )
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
        rows, total = list_items(
            db.get_db(), q=q, registration_state=state, limit=limit, offset=offset
        )
    except Exception:
        return _error_response("INTERNAL_ERROR", "品目一覧を取得できませんでした。", status=500)
    return jsonify(data=rows, page={"limit": limit, "offset": offset, "total": total})


@items_bp.post("/items")
def post_items():
    body, error = _json_object()
    if error:
        return error
    values, error = _validate_body(body, create=True)
    if error:
        return error
    try:
        item_id = post_item(db.get_db(), **values)
        item = get_item(db.get_db(), item_id)
    except Exception:
        return _error_response("INTERNAL_ERROR", "品目を登録できませんでした。", status=500)
    response = jsonify(data=item)
    response.status_code = 201
    response.headers["Location"] = url_for("items.get_item_detail", item_id=item_id)
    return response


@items_bp.get("/items/<int:item_id>")
def get_item_detail(item_id):
    item = get_item(db.get_db(), item_id)
    if item is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された品目が見つかりません。", status=404)
    return jsonify(data=item)


@items_bp.patch("/items/<int:item_id>")
def patch_items(item_id):
    body, error = _json_object()
    if error:
        return error
    changes, error = _validate_body(body, create=False)
    if error:
        return error
    try:
        item = patch_item(db.get_db(), item_id, changes)
    except ItemConflict as conflict:
        return _error_response(
            conflict.code, conflict.message, status=409, details=conflict.details
        )
    except Exception:
        return _error_response("INTERNAL_ERROR", "品目を更新できませんでした。", status=500)
    if item is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された品目が見つかりません。", status=404)
    return jsonify(data=item)


@items_bp.post("/items/<int:item_id>/closure")
def close_items(item_id):
    body, error = _json_object()
    if error:
        return error
    if body != {}:
        return _error_response(
            "UNKNOWN_FIELD",
            "登録終了APIの本文は空のオブジェクトにしてください。",
            status=422,
            fields=[_field("/body", "EMPTY_OBJECT_REQUIRED", "{}を指定してください。")],
        )
    try:
        item = close_item(db.get_db(), item_id)
    except Exception:
        return _error_response("INTERNAL_ERROR", "品目を登録終了できませんでした。", status=500)
    if item is None:
        return _error_response("RESOURCE_NOT_FOUND", "指定された品目が見つかりません。", status=404)
    return jsonify(data=item)
