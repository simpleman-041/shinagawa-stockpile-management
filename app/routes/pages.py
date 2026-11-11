"""Jinja2で表示する画面のルート。"""

from flask import Blueprint, abort, render_template

from app import db
from app.services.warehouses import get_warehouse


pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/warehouses")
def warehouses_page():
    return render_template("warehouses.html")


@pages_bp.get("/warehouses/new")
def warehouses_new_page():
    return render_template(
        "warehouses_form.html",
        mode="create",
        warehouse=None,
    )


@pages_bp.get("/warehouses/<int:warehouse_id>/edit")
def warehouses_edit_page(warehouse_id):
    warehouse = get_warehouse(db.get_db(), warehouse_id)
    if warehouse is None:
        abort(404)

    return render_template(
        "warehouses_form.html",
        mode="edit",
        warehouse=warehouse,
    )
