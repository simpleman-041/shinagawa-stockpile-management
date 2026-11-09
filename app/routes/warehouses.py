"""倉庫に関するJSON API。"""

from flask import Blueprint, jsonify, request

from app import db
from app.services.warehouses import list_warehouses


warehouses_bp = Blueprint("warehouses", __name__)

_ALLOWED_QUERY_KEYS = {"q", "coordinates", "limit", "offset"}


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
