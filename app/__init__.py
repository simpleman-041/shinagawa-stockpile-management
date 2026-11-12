"""Flaskアプリを組み立て、DB機能を使える状態にする入口。

DB接続先の設定、接続の後片付け、DB管理コマンドの登録をここに集める。
create_app() ごとに独立したアプリを作れるため、テストでは開発用DBと分離できる。
DBファイルの作成は init-db コマンドが担当する。
"""

import os
from pathlib import Path

from flask import Flask


def create_app(test_config=None):
    """設定を読み込み、需要条件を含むAPI・画面・DB機能を登録したアプリを返す。

    test_config は設定を上書きする辞書。テスト時に一時DBを指定するために使う。
    アプリの組み立てとDB初期化を分け、起動するだけでDBを変更しないようにする。
    """
    # instance はローカルDBなどの置き場。Gitで共有するコードと分けて扱う。
    app = Flask(__name__, instance_relative_config=True)
    # 環境変数で接続先を指定できる。指定がなければ instance 内のDBを使う。
    app.config.from_mapping(
        DATABASE=os.environ.get(
            "UNFIRE_DATABASE", str(Path(app.instance_path) / "unfire.sqlite3")
        ),
    )
    if test_config is not None:
        # テスト用の接続先を優先し、普段のデータを保護する。
        app.config.update(test_config)

    from . import db

    # アプリを作ってから、そのアプリへ後片付け処理と管理コマンドを登録する。
    db.init_app(app)

    from .routes.warehouses import warehouses_bp
    from .routes.items import items_bp
    from .routes.shelters import shelters_bp
    from .routes.pages import pages_bp
    from .routes.demand_groups import demand_groups_bp, register_routing_errors

    app.register_blueprint(warehouses_bp, url_prefix="/api/v1")
    app.register_blueprint(items_bp, url_prefix="/api/v1")
    app.register_blueprint(shelters_bp, url_prefix="/api/v1")
    app.register_blueprint(pages_bp)
    app.register_blueprint(demand_groups_bp, url_prefix="/api/v1")
    register_routing_errors(app)
    from .routes.stocks import init_app as init_stocks
    init_stocks(app)
    from .routes.movements import movements_bp
    app.register_blueprint(movements_bp, url_prefix="/api/v1")
    from .routes.warehouse_settings import warehouse_settings_bp
    app.register_blueprint(warehouse_settings_bp, url_prefix="/api/v1")
    return app
