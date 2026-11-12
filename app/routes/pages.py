"""Jinja2で表示する画面のルート。"""

from flask import Blueprint, abort, render_template

from app import db
from app.services.items import get_item
from app.services.shelters import get_shelter
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


@pages_bp.get("/items")
def items_page():
    return render_template("items.html")


@pages_bp.get("/items/new")
def items_new_page():
    return render_template("items_form.html", mode="create", item=None)


@pages_bp.get("/items/<int:item_id>/edit")
def items_edit_page(item_id):
    item = get_item(db.get_db(), item_id)
    if item is None:
        abort(404)
    return render_template("items_form.html", mode="edit", item=item)


@pages_bp.get("/shelters")
def shelters_page():
    return render_template("shelters.html")


@pages_bp.get("/shelters/new")
def shelters_new_page():
    return render_template("shelters_form.html", mode="create", shelter=None)


@pages_bp.get("/shelters/<int:shelter_id>/edit")
def shelters_edit_page(shelter_id):
    shelter = get_shelter(db.get_db(), shelter_id)
    if shelter is None:
        abort(404)
    return render_template("shelters_form.html", mode="edit", shelter=shelter)


@pages_bp.get("/stocks")
def stocks_page():
    return render_template("stocks.html", mode="list")


@pages_bp.get("/shelters/<int:shelter_id>/warehouse-settings")
def shelter_warehouse_settings_page(shelter_id):
    shelter = get_shelter(db.get_db(), shelter_id)
    if shelter is None:
        abort(404)
    return render_template("warehouse_settings.html", shelter=shelter)


@pages_bp.get("/stocks/new")
def stocks_new_page():
    return render_template("stocks.html", mode="create")


@pages_bp.get("/stocks/<int:stock_id>")
def stocks_detail_page(stock_id):
    from flask import request
    from app.services.stocks import get_stock, restoration_context, StockError
    try:
        context = restoration_context(db.get_db(), stock_id) if request.args.get("restore") == "1" else None
        if context is None:
            get_stock(db.get_db(), stock_id)
    except StockError as error:
        if error.status == 404:
            abort(404)
        raise
    return render_template("stocks.html", mode="detail", stock_id=stock_id, restoration_context=context)
