"""倉庫に関するJSON API。"""

import math

from flask import Blueprint, jsonify, request, url_for
from werkzeug.exceptions import BadRequest

from app import db
from app.services.warehouses import (
    get_warehouse,
    list_warehouses,
    patch_warehouse,
    post_warehouse,
)


warehouses_bp = Blueprint("warehouses", __name__)

_ALLOWED_QUERY_KEYS = {"q", "coordinates", "limit", "offset"}
_WAREHOUSE_FIELDS = {
    "name",
    "facility_type",
    "address",
    "latitude",
    "longitude",
    "capacity_m3",
}
_WAREHOUSE_CREATE_REQUIRED = {"name", "facility_type", "address"}
_WAREHOUSE_NULLABLE = {"latitude", "longitude", "capacity_m3"}


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


def _query_value(name):
    values = request.args.getlist(name)
    if len(values) > 1:
        return None, _error_response(
            "VALIDATION_ERROR",
            f"クエリー {name} は1回だけ指定してください。",
            status=422,
            fields=[{"path": f"/query/{name}", "code": "DUPLICATE", "message": "重複指定はできません。"}],
        )
    return (values[0] if values else None), None


def _field_error(path, code, message):
    return [{"path": path, "code": code, "message": message}]


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
        return None, _error_response(
            "INVALID_JSON",
            "JSONを解析できません。",
            status=400,
        )
    if not isinstance(body, dict):
        return None, _error_response(
            "INVALID_JSON",
            "JSONのトップレベルにはオブジェクトを指定してください。",
            status=400,
        )
    return body, None


def _validate_text(body, field, *, required):
    if field not in body:
        if required:
            return _field_error(
                f"/body/{field}", "REQUIRED", "必須項目です。"
            )
        return None
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        return _field_error(
            f"/body/{field}", "TEXT_REQUIRED", "空でない文字列を指定してください。"
        )
    return None


def _validate_number(body, field):
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _field_error(
            f"/body/{field}", "NUMBER_REQUIRED", "数値を指定してください。"
        )
    if isinstance(value, float) and not math.isfinite(value):
        return _field_error(
            f"/body/{field}", "NUMBER_REQUIRED", "有限の数値を指定してください。"
        )
    if field == "latitude" and not -90 <= value <= 90:
        return _field_error(
            f"/body/{field}", "OUT_OF_RANGE", "緯度は-90以上90以下で指定してください。"
        )
    if field == "longitude" and not -180 <= value <= 180:
        return _field_error(
            f"/body/{field}", "OUT_OF_RANGE", "経度は-180以上180以下で指定してください。"
        )
    if field == "capacity_m3" and (value < 0 or value > 1.7976931348623157e308):
        return _field_error(
            f"/body/{field}", "OUT_OF_RANGE", "容量は0以上で指定してください。"
        )
    return None


def _validate_fields(body, *, create):
    unknown = sorted(set(body) - _WAREHOUSE_FIELDS)
    if unknown:
        return _error_response(
            "UNKNOWN_FIELD",
            f"未対応の本文フィールド {unknown[0]} は指定できません。",
            status=422,
            fields=_field_error(
                f"/body/{unknown[0]}", "UNKNOWN_FIELD", "未対応の項目です。"
            ),
        )

    if create:
        missing = sorted(_WAREHOUSE_CREATE_REQUIRED - set(body))
        for field in missing:
            return _error_response(
                "VALIDATION_ERROR",
                f"必須項目 {field} がありません。",
                status=422,
                fields=_field_error(
                    f"/body/{field}", "REQUIRED", "必須項目です。"
                ),
            )
    elif not body:
        return _error_response(
            "VALIDATION_ERROR",
            "PATCHする項目を1つ以上指定してください。",
            status=422,
            fields=_field_error("/body", "EMPTY_OBJECT", "空のオブジェクトは指定できません。"),
        )

    for field in ("name", "facility_type", "address"):
        error = _validate_text(body, field, required=create)
        if error:
            return _error_response(
                "VALIDATION_ERROR",
                "倉庫情報の入力が不正です。",
                status=422,
                fields=error,
            )
        if not create and field in body and body[field] is None:
            return _error_response(
                "VALIDATION_ERROR",
                "通常項目にはnullを指定できません。",
                status=422,
                fields=_field_error(
                    f"/body/{field}", "NULL_NOT_ALLOWED", "nullは指定できません。"
                ),
            )

    for field in _WAREHOUSE_NULLABLE:
        error = _validate_number(body, field)
        if error:
            return _error_response(
                "VALIDATION_ERROR",
                "倉庫情報の入力が不正です。",
                status=422,
                fields=error,
            )

    present_coordinates = {
        field for field in ("latitude", "longitude") if field in body
    }
    if present_coordinates and present_coordinates != {"latitude", "longitude"}:
        return _error_response(
            "VALIDATION_ERROR",
            "緯度と経度は同時に指定してください。",
            status=422,
            fields=_field_error("/body", "COORDINATE_PAIR_REQUIRED", "座標は対で指定してください。"),
        )
    return None


def _parse_non_negative_integer(name, value, *, minimum=0, maximum=None):
    if value is None:
        return (50 if name == "limit" else 0), None
    if not value.isdecimal():
        return None, _error_response(
            "VALIDATION_ERROR",
            f"クエリー {name} は10進整数で指定してください。",
            status=422,
            fields=[{"path": f"/query/{name}", "code": "INTEGER_REQUIRED", "message": "整数を指定してください。"}],
        )
    parsed = int(value)
    if parsed < minimum or (maximum is not None and parsed > maximum):
        range_text = f"{minimum}以上"
        if maximum is not None:
            range_text += f"{maximum}以下"
        return None, _error_response(
            "VALIDATION_ERROR",
            f"クエリー {name} は{range_text}で指定してください。",
            status=422,
            fields=[{"path": f"/query/{name}", "code": "OUT_OF_RANGE", "message": range_text + "の整数を指定してください。"}],
        )
    return parsed, None


@warehouses_bp.get("/warehouses")
def get_warehouses():
    unknown = set(request.args) - _ALLOWED_QUERY_KEYS
    if unknown:
        name = sorted(unknown)[0]
        return _error_response(
            "UNKNOWN_FIELD",
            f"未対応のクエリー {name} は指定できません。",
            status=422,
            fields=[{"path": f"/query/{name}", "code": "UNKNOWN_FIELD", "message": "未対応のクエリーです。"}],
        )

    q, error = _query_value("q")
    if error:
        return error
    if q == "":
        return _error_response(
            "VALIDATION_ERROR",
            "クエリー q は空にできません。",
            status=422,
            fields=[{"path": "/query/q", "code": "EMPTY", "message": "空でない文字列を指定してください。"}],
        )

    coordinates, error = _query_value("coordinates")
    if error:
        return error
    if coordinates not in (None, "known", "missing"):
        return _error_response(
            "VALIDATION_ERROR",
            "coordinates は known または missing で指定してください。",
            status=422,
            fields=[{"path": "/query/coordinates", "code": "ENUM", "message": "known または missing を指定してください。"}],
        )

    limit_raw, error = _query_value("limit")
    if error:
        return error
    limit, error = _parse_non_negative_integer("limit", limit_raw, minimum=1, maximum=200)
    if error:
        return error

    offset_raw, error = _query_value("offset")
    if error:
        return error
    offset, error = _parse_non_negative_integer("offset", offset_raw)
    if error:
        return error

    try:
        rows, total = list_warehouses(
            db.get_db(), q=q, coordinates=coordinates, limit=limit, offset=offset
        )
    except Exception:
        return _error_response(
            "INTERNAL_ERROR",
            "倉庫一覧を取得できませんでした。",
            status=500,
        )

    return jsonify(data=rows, page={"limit": limit, "offset": offset, "total": total})

@warehouses_bp.post("/warehouses")
def post_warehouses():
    body, error = _json_object()
    if error:
        return error
    error = _validate_fields(body, create=True)
    if error:
        return error

    try:
        warehouse_id = post_warehouse(
            db.get_db(),
            name=body["name"],
            facility_type=body["facility_type"],
            address=body["address"],
            latitude=body.get("latitude"),
            longitude=body.get("longitude"),
            capacity_m3=body.get("capacity_m3"),
        )
        warehouse = get_warehouse(db.get_db(), warehouse_id)
    except Exception:
        return _error_response(
            "INTERNAL_ERROR", "倉庫を登録できませんでした。", status=500
        )

    response = jsonify(data=warehouse)
    response.status_code = 201
    response.headers["Location"] = url_for(
        "warehouses.get_warehouse_detail", warehouse_id=warehouse_id
    )
    return response


@warehouses_bp.get("/warehouses/<int:warehouse_id>")
def get_warehouse_detail(warehouse_id):
    warehouse = get_warehouse(db.get_db(), warehouse_id)
    if warehouse is None:
        return _error_response(
            "NOT_FOUND", "指定された倉庫が見つかりません。", status=404
        )
    return jsonify(data=warehouse)


@warehouses_bp.patch("/warehouses/<int:warehouse_id>")
def patch_warehouses(warehouse_id):
    body, error = _json_object()
    if error:
        return error
    error = _validate_fields(body, create=False)
    if error:
        return error

    connection = db.get_db()
    warehouse = get_warehouse(connection, warehouse_id)
    if warehouse is None:
        return _error_response(
            "NOT_FOUND", "指定された倉庫が見つかりません。", status=404
        )

    changes = dict(body)
    if "latitude" in changes or "longitude" in changes:
        latitude = changes.get("latitude", warehouse["latitude"])
        longitude = changes.get("longitude", warehouse["longitude"])
        if (latitude is None) != (longitude is None):
            return _error_response(
                "VALIDATION_ERROR",
                "緯度と経度は同時に指定するか、両方nullにしてください。",
                status=422,
                fields=_field_error(
                    "/body", "COORDINATE_PAIR_REQUIRED", "座標は対で指定してください。"
                ),
            )

    try:
        patch_warehouse(connection, warehouse_id, changes)
        warehouse = get_warehouse(connection, warehouse_id)
    except Exception:
        return _error_response(
            "INTERNAL_ERROR", "倉庫を更新できませんでした。", status=500
        )
    return jsonify(data=warehouse)
