"""SH01〜05。通常編集と正式目標を分離するAPI1.0契約。"""

from flask import Blueprint, jsonify, url_for

from app import db
from app.routes.master_contract import configure, found, pagination, positive_integer, read_body, search_text, text
from app.services import shelters as service
from app.services.stocks import StockError

shelters_bp = Blueprint("shelters", __name__)
configure(shelters_bp, {"get_shelters": {"q", "limit", "offset"}})
_READONLY = {"shelter_id", "setup_state"}


def _dto(row):
    value = dict(found(row))
    value["shelter_id"] = str(value["shelter_id"])
    return value


@shelters_bp.get("/shelters")
def get_shelters():
    limit, offset = pagination()
    rows, total = service.list_shelters(db.get_db(), q=search_text(), limit=limit, offset=offset)
    return jsonify(data=[_dto(row) for row in rows], page={"limit": limit, "offset": offset, "total": total})


@shelters_bp.post("/shelters")
def post_shelters():
    values = read_body({"name", "address"}, {"target_people", "target_days"}, _READONLY)
    for key in ("name", "address"):
        text(values[key], f"/{key}")
    people, days = values.get("target_people"), values.get("target_days")
    if (people is None) != (days is None):
        raise StockError("VALIDATION_ERROR", "正式目標は人数・日数の両方を設定するか、両方未設定にしてください。", path="/target_people")
    if people is not None:
        positive_integer(people, "/target_people")
        positive_integer(days, "/target_days")
    connection = db.get_db()
    shelter_id = service.post_shelter(connection, **values)
    response = jsonify(data=_dto(service.get_shelter(connection, shelter_id)))
    response.status_code = 201
    response.headers["Location"] = url_for("shelters.get_shelter_detail", shelter_id=shelter_id)
    return response


@shelters_bp.get("/shelters/<shelter_id>")
def get_shelter_detail(shelter_id):
    return jsonify(data=_dto(service.get_shelter(db.get_db(), shelter_id)))


@shelters_bp.patch("/shelters/<shelter_id>")
def patch_shelters(shelter_id):
    values = read_body(optional={"name", "address"}, readonly=_READONLY)
    if not values:
        raise StockError("VALIDATION_ERROR", "編集する項目を指定してください。")
    for key in values:
        text(values[key], f"/{key}")
    return jsonify(data=_dto(service.patch_shelter(db.get_db(), shelter_id, values)))


@shelters_bp.put("/shelters/<shelter_id>/targets")
def put_shelter_targets(shelter_id):
    values = read_body({"target_people", "target_days"})
    for key in values:
        positive_integer(values[key], f"/{key}")
    return jsonify(data=_dto(service.put_targets(db.get_db(), shelter_id, **values)))
