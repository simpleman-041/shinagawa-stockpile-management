"""DG01〜DG04・IC01のHTTP境界。採用API契約1.0の型・精度を検証する。"""

import json
import re
import sqlite3
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request, url_for
from werkzeug.exceptions import BadRequest

from app import db
from app.services import demand_groups as service
from app.services.demand_groups import DemandGroupError


demand_groups_bp = Blueprint("demand_groups", __name__)
_MAX_ID = 9223372036854775807
_MAX_SAFE_INTEGER = 9007199254740991
_DECIMAL = re.compile(r"(0|[1-9][0-9]*)(?:\.([0-9]+))?")
_CONVERSION_INPUT = {"factor", "source_text", "version_or_date", "conditions"}
_READ_ONLY = {"group_id", "item_id", "factor_x100"}


def _pointer(path, key):
    """項目名の特殊文字をエスケープしてJSON Pointerの入力位置を作る。"""
    return f"{path}/{key.replace('~', '~0').replace('/', '~1')}"


def _error(code, message, *, status, fields=None, details=None):
    """契約共通のJSONエラーを作り、DBロック時だけ再試行可能とする。"""
    return jsonify(error={
        "code": code, "message": message, "fields": fields or [],
        "details": details or {}, "retryable": code == "STORAGE_BUSY",
    }), status


@demand_groups_bp.errorhandler(DemandGroupError)
def _contract_error(error):
    """入力検証や業務検証のエラーを、指定されたHTTP応答へ変換する。"""
    return _error(error.code, error.message, status=error.status, fields=error.fields, details=error.details)


@demand_groups_bp.errorhandler(Exception)
def _unexpected_error(error):
    """本文切断・DB障害等を分類し、内部例外を伏せたエラーを返す。"""
    if isinstance(error, BadRequest):
        return _error("INVALID_JSON", "要求本文を読み取れません。JSONを確認してください。", status=400)
    if isinstance(error, sqlite3.IntegrityError):
        return _error("DATA_INTEGRITY_ERROR", "DBの整合性を確認してください。", status=500)
    if isinstance(error, sqlite3.Error):
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return _error("STORAGE_BUSY", "DBが使用中です。更新結果を確認してから再操作してください。", status=503)
        if code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL,
                    sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM):
            return _error("STORAGE_UNAVAILABLE", "DBを利用できません。接続先と保存先を確認してください。", status=503)
    if isinstance(error, OSError):
        return _error("STORAGE_UNAVAILABLE", "保存先を利用できません。復旧後に再確認してください。", status=503)
    current_app.logger.error("需要条件APIで予期しないエラーが発生しました。")
    return _error("INTERNAL_ERROR", "処理に失敗しました。更新結果を確認してください。", status=500)


def register_routing_errors(app):
    """Blueprint決定前の404/405だけを、今回のパスに限定してJSON化する。"""
    def handle(error):
        """対象APIの404・405をJSON化し、他のパスは既定の応答を保つ。"""
        path = request.path
        is_group = path == "/api/v1/demand-groups" or path.startswith("/api/v1/demand-groups/")
        is_conversion = re.fullmatch(r"/api/v1/items/[^/]+/conversion(?:/.*)?", path)
        is_stock = re.match(r"^/api/v1/(?:stocks|stock-merges|stock-alerts|operators)(?:/|$)", path)
        if is_stock:
            from .stocks import error_response
            code = "METHOD_NOT_ALLOWED" if error.code == 405 else "RESOURCE_NOT_FOUND"
            response, status = error_response(code, "APIのパスとHTTPメソッドを確認してください。", error.code)
            if error.code == 405:
                response.headers["Allow"] = ", ".join(sorted(error.valid_methods or []))
            return response, status
        if not (is_group or is_conversion):
            return error
        code = "METHOD_NOT_ALLOWED" if error.code == 405 else "RESOURCE_NOT_FOUND"
        message = "許可されたHTTPメソッドを使用してください。" if error.code == 405 else "指定されたAPIが見つかりません。"
        response, status = _error(code, message, status=error.code)
        if error.code == 405:
            response.headers["Allow"] = ", ".join(sorted(error.valid_methods or []))
        return response, status

    app.register_error_handler(404, handle)
    app.register_error_handler(405, handle)


def _bounded_integer(value, *, path, maximum):
    """構文検証済みの数字列を上限と比較し、安全に整数へ変換する。"""
    # int()の巨大文字列制限や、URLのint変換による先頭0の消失を避ける。
    significant = value.lstrip("0") or "0"
    bound = str(maximum)
    if len(significant) > len(bound) or (len(significant) == len(bound) and significant > bound):
        raise DemandGroupError("NUMBER_NOT_REPRESENTABLE", "整数の表現範囲を超えています。", path=path)
    return int(significant)


def _identifier(value, path):
    """IDが先頭0のない正の整数文字列で、SQLiteの範囲内か検証する。"""
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise DemandGroupError("VALIDATION_ERROR", "IDは先頭0のない正の整数文字列にしてください。", path=path)
    return _bounded_integer(value, path=path, maximum=_MAX_ID)


def _exact_fields(body, required, *, path=""):
    """必須キーとの一致を調べ、省略・未知項目・読取専用項目を拒否する。"""
    if not isinstance(body, dict):
        raise DemandGroupError("VALIDATION_ERROR", "オブジェクトを指定してください。", path=path)
    unknown = sorted(set(body) - set(required))
    if unknown:
        field = unknown[0]
        code = "READ_ONLY_FIELD" if field in _READ_ONLY else "UNKNOWN_FIELD"
        raise DemandGroupError(code, "この項目は指定できません。", path=_pointer(path, field))
    missing = sorted(set(required) - set(body))
    if missing:
        raise DemandGroupError("VALIDATION_ERROR", "必須項目を指定してください。未設定値はnullを指定します。", path=f"{path}/{missing[0]}")


def _text(value, path, *, nullable=True):
    """nullの許否と空文字・UTF-8を検証し、文字列を正規化せず返す。"""
    if value is None and nullable:
        return value
    if not isinstance(value, str) or not value.strip() or not value.strip(" ").split("\x00", 1)[0]:
        raise DemandGroupError("VALIDATION_ERROR", "空でない文字列を指定してください。", path=path)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise DemandGroupError("VALIDATION_ERROR", "UTF-8で表せる文字列を指定してください。", path=path) from None
    return value


def _positive_decimal(value, path):
    """未設定のnullを保ち、正の小数第2位までの文字列をDecimalへ変換する。"""
    if value is None:
        return None
    match = _DECIMAL.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise DemandGroupError("VALIDATION_ERROR", "正の10進文字列を指定してください。", path=path)
    if len(match.group(2) or "") > 2:
        raise DemandGroupError("DECIMAL_PRECISION", "小数第2位までで指定してください。", path=path)
    decimal = Decimal(value)
    if decimal <= 0:
        raise DemandGroupError("VALIDATION_ERROR", "0より大きい値を指定してください。", path=path)
    return decimal


def _group_input(body, *, path=""):
    """需要条件の7項目を検証し、使用量を十進数としてサービスへ渡す。"""
    _exact_fields(body, service.GROUP_FIELDS, path=path)
    group = {field: _text(body[field], f"{path}/{field}", nullable=field != "name")
             for field in ("name", "calculation_unit", "source_text", "version_or_date", "conditions")}
    divisible = body["is_divisible"]
    if divisible is not None and not isinstance(divisible, bool):
        raise DemandGroupError("VALIDATION_ERROR", "分割可否はtrue、false、nullのいずれかを指定してください。", path=f"{path}/is_divisible")
    group["is_divisible"] = divisible
    group["daily_usage"] = _positive_decimal(body["daily_usage"], f"{path}/daily_usage")
    return group


def _conversion_input(body, *, path=""):
    """キー検証済みの換算入力を調べ、係数を正確な100倍整数へ変換する。"""
    factor = _positive_decimal(body["factor"], f"{path}/factor")
    factor_x100 = None
    if factor is not None:
        integer, _, fraction = body["factor"].partition(".")
        factor_x100 = _bounded_integer(integer + fraction.ljust(2, "0"), path=f"{path}/factor", maximum=_MAX_ID)
    return {
        "factor_x100": factor_x100,
        **{field: _text(body[field], f"{path}/{field}") for field in ("source_text", "version_or_date", "conditions")},
    }


def _json_object():
    """Content-TypeとUTF-8を確認し、重複キーのないJSONオブジェクトを読む。"""
    if request.mimetype != "application/json":
        raise DemandGroupError("UNSUPPORTED_MEDIA_TYPE", "Content-Typeにapplication/jsonを指定してください。", status=415)

    def object_pairs(pairs):
        """JSONの各階層でキーの重複を検出しながら辞書を作る。"""
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate key")
            obj[key] = value
        return obj

    def invalid_constant(value):
        """NaNやInfinityなど、JSON契約にない定数を解析時点で拒否する。"""
        raise ValueError("non-finite number")

    try:
        body = json.loads(request.get_data().decode("utf-8"), object_pairs_hook=object_pairs,
                          parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise DemandGroupError("INVALID_JSON", "重複キーのないUTF-8のJSONオブジェクトを指定してください。", status=400) from None
    if not isinstance(body, dict):
        raise DemandGroupError("INVALID_JSON", "JSONのルートはオブジェクトにしてください。", status=400)
    return body


@demand_groups_bp.before_request
def _request_contract():
    """各APIの許可クエリーと重複を確認し、GET・HEADの本文を拒否する。"""
    allowed = {"limit", "offset"} if request.endpoint == "demand_groups.get_groups" else set()
    for name in request.args:
        if name not in allowed:
            raise DemandGroupError("UNKNOWN_FIELD", "未対応のクエリーです。", path=_pointer("/query", name))
        if len(request.args.getlist(name)) != 1:
            raise DemandGroupError("VALIDATION_ERROR", "クエリーは重複指定できません。", path=f"/query/{name}")
    if request.method in ("GET", "HEAD") and request.get_data():
        raise DemandGroupError("INVALID_JSON", "GETには本文を指定できません。", status=400)


def _pagination(name, default, minimum, maximum):
    """一覧の件数・開始位置を解析し、省略時の既定値と許可範囲を適用する。"""
    raw = request.args.get(name)
    if raw is None:
        return default
    path = f"/query/{name}"
    if re.fullmatch(r"[0-9]+", raw) is None:
        raise DemandGroupError("VALIDATION_ERROR", "10進整数を指定してください。", path=path)
    value = _bounded_integer(raw, path=path, maximum=_MAX_SAFE_INTEGER)
    if not minimum <= value <= maximum:
        raise DemandGroupError("VALIDATION_ERROR", "指定可能な範囲を確認してください。", path=path)
    return value


@demand_groups_bp.get("/demand-groups")
def get_groups():
    """DG01：需要グループ一覧とページ分割前の総件数を返す。"""
    limit = _pagination("limit", 50, 1, 200)
    offset = _pagination("offset", 0, 0, _MAX_SAFE_INTEGER)
    groups, total = service.list_groups(db.get_db(), limit=limit, offset=offset)
    return jsonify(data=groups, page={"limit": limit, "offset": offset, "total": total})


@demand_groups_bp.post("/demand-groups")
def post_group():
    """DG02：下書きを含む需要を登録し、201と条件取得先のLocationを返す。"""
    group = _group_input(_json_object())
    created = service.create_group(db.get_db(), group)
    response = jsonify(data=created)
    response.status_code = 201
    response.headers["Location"] = url_for("demand_groups.get_group_conditions", group_id=created["group_id"])
    return response


@demand_groups_bp.get("/demand-groups/<group_id>/conditions")
def get_group_conditions(group_id):
    """DG03：指定需要の条件と、登録終了品目を含む全所属換算を返す。"""
    group_id = _identifier(group_id, "/path/group_id")
    return jsonify(data=service.get_conditions(db.get_db(), group_id))


@demand_groups_bp.put("/demand-groups/<group_id>/conditions")
def put_group_conditions(group_id):
    """DG04：需要と全所属換算の入力を解析し、原子的な一括更新を依頼する。"""
    group_id = _identifier(group_id, "/path/group_id")
    body = _json_object()
    _exact_fields(body, {"group", "conversions"})
    group = _group_input(body["group"], path="/group")
    if not isinstance(body["conversions"], list):
        raise DemandGroupError("VALIDATION_ERROR", "品目換算は配列で指定してください。", path="/conversions")
    conversions = []
    for index, entry in enumerate(body["conversions"]):
        path = f"/conversions/{index}"
        _exact_fields(entry, _CONVERSION_INPUT | {"item_id"}, path=path)
        conversions.append({"item_id": _identifier(entry["item_id"], f"{path}/item_id"),
                            **_conversion_input(entry, path=path)})
    return jsonify(data=service.replace_conditions(db.get_db(), group_id, group, conversions))


@demand_groups_bp.put("/items/<item_id>/conversion")
def put_item_conversion(item_id):
    """IC01：品目の需要対応・換算を設定し、初回201・更新200を返す。"""
    item_id = _identifier(item_id, "/path/item_id")
    body = _json_object()
    _exact_fields(body, _CONVERSION_INPUT | {"group_id"})
    group_id = _identifier(body["group_id"], "/group_id")
    conversion = _conversion_input(body)
    result, created = service.set_item_conversion(db.get_db(), item_id, group_id, conversion)
    return jsonify(data=result), 201 if created else 200
