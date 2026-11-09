"""Jinja2で表示する画面のルート。"""

from flask import Blueprint, render_template


pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/warehouses")
def warehouses_page():
    return render_template("warehouses.html")
