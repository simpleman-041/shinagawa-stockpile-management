"""SQLiteの接続・初期化・検査をまとめ、各機能が共通で使うための部品。

接続時の設定を統一し、途中失敗で更新が一部だけ保存されるのを防ぐ。
Flaskからは get_db() で接続を取得し、transaction() の with 文で更新をまとめる。
DBの新規作成と状態確認は init-db / check-db コマンドから実行する。
接続方針はAPI設計書§5.1、DBの構造は2026年11月1日版DDLに従う。
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext


# スキーマは「表・列・制約などの構造」のこと。作業フォルダが変わっても
# 同じSQLを読めるよう、このPythonファイルの位置を基準に絶対パスを作る。
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
# 作成途中のDBなどを正常と報告しないため、設計上の件数と比較する。
EXPECTED_SCHEMA_COUNTS = {
    "tables": 19, "columns": 155, "foreign_keys": 32, "indexes": 27, "triggers": 34
}


def connect_db(database, *, timeout=5.0):
    """既存DBへ接続し、必要な制約を有効にした接続オブジェクトを返す。

    database はDBファイルの場所、timeout は他の更新が終わるまで待つ秒数。
    指定ミスで空DBを作らないよう、ファイルがなければ失敗させる。
    返した接続は呼出元が閉じる。Flask経由なら close_db() が担当する。
    """
    # mode=rw は既存ファイルの読み書き専用。新規作成は許可しない。
    # as_uri() は日本語・空白・#などを含むパスをURIとして安全に表現する。
    uri = Path(database).resolve().as_uri() + "?mode=rw"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=timeout,
        # Python任せの暗黙のBEGINを止め、transaction() で開始時点を決める。
        # 明示的に開始した更新には commit()/rollback() を使える設定にする。
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
        isolation_level=None,
    )
    try:
        # 検索結果を row["name"] のように列名でも読めるようにする。
        connection.row_factory = sqlite3.Row
        # PRAGMAはSQLiteの設定・検査用命令。外部キーは表同士の参照を守る。
        # 再帰トリガーは、自動処理から発生した操作でも関連トリガーを動かす設定。
        # 接続ごとに、トランザクション開始前に設定する必要がある。
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA recursive_triggers = ON")
        # 命令を送るだけでなく、設定値が1（有効）か読み戻して確かめる。
        if (
            connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1
            or connection.execute("PRAGMA recursive_triggers").fetchone()[0] != 1
        ):
            raise RuntimeError("Required SQLite constraints could not be enabled.")
        return connection
    except BaseException:
        # 設定失敗や操作中断でも接続を残さず、エラーは呼出元へ伝える。
        connection.close()
        raise


def get_db():
    """現在のFlaskの処理で共有する接続を取得し、接続の重複を防ぐ。

    最初の呼出しで接続し、以後は同じ接続を返す。
    Flaskのアプリケーションコンテキスト（設定や一時データを使える範囲）内で
    呼び出す。通常はリクエスト処理や、登録済みのDB管理コマンドから使う。
    """
    # g は現在のコンテキスト専用の保管場所。全利用者で共有する変数ではない。
    if "db" not in g:
        g.db = connect_db(current_app.config["DATABASE"])
    return g.db


def close_db(error=None):
    """Flaskの処理終了時に、未確定の更新を取り消して接続を閉じる。

    接続しなかった処理でも呼べるよう、接続がある場合だけ後片付けする。
    error はFlaskが渡す例外情報。ここでは受け取るだけで、例外の有無にかかわらず
    未確定の更新は取り消す。後片付けの時点で勝手に保存しないための処理。
    """
    connection = g.pop("db", None)
    if connection is not None:
        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            # rollbackが失敗しても、接続を閉じる処理は必ず試みる。
            connection.close()


# デコレーターは関数に追加の仕組みを付けるもの。ここではwith文で使える形にする。
@contextmanager
def transaction(connection, *, write=True):
    """with 文内のDB操作を、全部保存するか全部取り消すかの単位にまとめる。

    connection は共通処理で取得した接続。write=True は更新用、False は読取用。
    正常終了でCOMMIT（保存確定）、例外や中断でROLLBACK（未確定の更新を取消）する。
    呼出側は手動COMMITせず、業務上の確認と関連更新を同じブロックに置く。
    """
    # 内側だけが保存されるなどの混乱を防ぐため、開始済みの処理への入れ子は拒否する。
    if connection.in_transaction:
        raise RuntimeError("Nested transactions are not supported.")
    # 更新用は最初に書込み権を確保し、競合で取得できなければエラーを返す。
    # 読取用のBEGINは書込み権を予約しない（更新SQL自体を禁止する設定ではない）。
    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        # yieldの間に呼出側のwithブロックが実行され、終了するとここへ戻ってくる。
        yield connection
        # 外部キーの中には、SQL実行時ではなく保存確定時に検査されるものもある。
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            # SQL失敗だけでなく、Ctrl+Cなどの中断やCOMMIT時の失敗も取り消す。
            connection.rollback()
        raise


def check_database(connection):
    """接続設定・DBの健全性・構造の件数を検査し、件数の辞書を返す。

    検査が通らなければ例外を出し、正常と報告しない。データは更新しない。
    割当上限などの全業務ルールや、同じ件数を持つ別の構造まで保証する検査ではない。
    """
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("Foreign key enforcement is disabled.")
    if connection.execute("PRAGMA recursive_triggers").fetchone()[0] != 1:
        raise RuntimeError("Recursive triggers are disabled.")
    # 存在しない親レコードを参照している行がないかを調べる。
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Foreign key violations were found.")
    # DB内部の構造などを検査する。正常なら「ok」という結果が1行だけ返る。
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError("SQLite integrity_check failed.")
    # sqlite_schemaには表・索引・トリガーの定義が入っている。
    # PRAGMAの表形式の結果を使い、表名をSQL文字列へ直接埋め込まず件数を調べる。
    counts = {
        "tables": connection.execute(
            "SELECT count(*) FROM sqlite_schema WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0],
        "columns": connection.execute(
            "SELECT count(*) FROM sqlite_schema AS s, pragma_table_info(s.name) "
            "WHERE s.type='table' AND s.name NOT LIKE 'sqlite_%'"
        ).fetchone()[0],
        "foreign_keys": connection.execute(
            # 複数列の外部キーも1本と数えるため、制約の先頭列（seq=0）だけ数える。
            "SELECT count(*) FROM sqlite_schema AS s, pragma_foreign_key_list(s.name) AS fk "
            "WHERE s.type='table' AND s.name NOT LIKE 'sqlite_%' AND fk.seq=0"
        ).fetchone()[0],
        "indexes": connection.execute(
            # SQLiteが自動生成した索引を除き、明示的に定義した索引だけ数える。
            "SELECT count(*) FROM sqlite_schema WHERE type='index' AND sql IS NOT NULL"
        ).fetchone()[0],
        "triggers": connection.execute(
            "SELECT count(*) FROM sqlite_schema WHERE type='trigger'"
        ).fetchone()[0],
    }
    if counts != EXPECTED_SCHEMA_COUNTS:
        raise RuntimeError("Database schema does not match the 2026-11-01 design.")
    return counts


def init_db():
    """正本と同じSQLから新規DBを作り、成功したら作成先のPathを返す。

    DDLは表や制約を作るSQLのこと。既存DBへの移行や上書きには使わない。
    新規ファイルだけを対象にし、途中失敗時はそのファイルを除去することで、
    既存データの保護と、修正後に初期化をやり直せる状態を確保する。
    """
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    database = Path(current_app.config["DATABASE"]).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    # xbは「ファイルが存在しない場合だけ新規作成する」モード。
    # 存在確認と通常の書込みを別々にする方法と違い、同時実行時も既存ファイルを守れる。
    with database.open("xb"):
        pass
    connection = None
    try:
        connection = connect_db(database)
        # executescriptは複数のSQLを実行する。開始済みの更新を意図せず確定しないよう、
        # 業務処理の接続と分ける。SQL自身にBEGIN/COMMITがあるためtransaction()で囲まない。
        connection.executescript(schema)
        check_database(connection)
    except BaseException:
        if connection is not None:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()
                connection = None
        # xbで新規作成できたファイルだけがここへ到達する。既存DBは削除対象にならない。
        database.unlink()
        raise
    finally:
        if connection is not None:
            connection.close()
    return database


# コマンド名を付け、実行中にFlaskの設定（current_app）を使えるようにする。
@click.command("init-db")
@with_appcontext
def init_db_command():
    """新規DBを作成するCLI（コマンドライン操作）の入口。

    flask --app app init-db から呼ばれる。既存ファイルがある場合は拒否し、
    失敗時はエラー、成功時は作成先を表示して、初期化の成否を利用者に伝える。
    """
    try:
        database = init_db()
    except FileExistsError as error:
        # Pythonの例外を、ターミナル向けのエラー表示と異常終了へ変換する。
        raise click.ClickException(
            "Database already exists; initialization refused. Choose a new path "
            "with UNFIRE_DATABASE."
        ) from error
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Initialized database: {database}")


# 検査コマンドにも、名前とFlaskのアプリケーションコンテキストを付ける。
@click.command("check-db")
@with_appcontext
def check_db_command():
    """DBへの接続と健全性を検査し、ターミナルに結果を表示するCLIの入口。

    flask --app app check-db から呼ばれる。読取用トランザクションで検査をまとめ、
    エラー時は正常結果を表示せず、失敗として終了する。
    """
    try:
        with transaction(get_db(), write=False) as connection:
            counts = check_database(connection)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Database: {Path(current_app.config['DATABASE']).resolve()}")
    click.echo(f"SQLite: {sqlite3.sqlite_version}")
    click.echo("foreign_keys=1; recursive_triggers=1")
    click.echo("foreign_key_check: 0 violations; integrity_check: ok")
    click.echo("; ".join(f"{name}={count}" for name, count in counts.items()))


def init_app(app):
    """作成済みのFlaskアプリへ、DB機能を登録する。

    app は create_app() が作ったアプリ。接続の後片付けを自動化し、
    init-db / check-db をコマンドとして呼べるようにする。ここではDBを作成しない。
    """
    # コンテキスト終了時に、Flaskがclose_dbを呼ぶよう予約する。
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(check_db_command)
