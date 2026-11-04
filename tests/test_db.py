"""DB基盤が設計どおり動き、失敗時にもデータを守ることを確認する自動テスト。

対象は要件Q34・Q35・Q71・Q74、DB設計2026年11月1日版、API設計§5.1・§8。
pytestが test_ で始まる関数を実行し、assert（期待結果の確認）が通るかを調べる。
DBはテストごとの一時フォルダに作成し、普段の開発用DBから分離する。
closing() は接続の後片付け、pytest.raises() は想定したエラーが起きることの確認に使う。
"""

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest

from app import create_app
from app import db


@pytest.fixture
def app(tmp_path):
    """一時DBを接続先にしたアプリを用意し、開発用DBへの誤接続を防ぐ。

    fixtureはテストの準備を共通化する仕組み。引数名appを持つテストへ渡される。
    tmp_pathはpytestがテストごとに用意する一時フォルダである。
    """
    return create_app({"TESTING": True, "DATABASE": tmp_path / "test.sqlite3"})


@pytest.fixture
def database(app):
    """正規の初期化処理で空のDBを作り、そのパスをテストへ渡す。

    簡略化した表ではなく実際のSQLを使い、制約やトリガーも含めて検証する。
    """
    with app.app_context():
        return db.init_db()


def test_schema_is_the_approved_ddl():
    """SQLの指紋に相当するハッシュを比較し、正本と実行用SQLの改変を検知する。"""
    source = Path(__file__).resolve().parents[1] / "local-specs/database"
    expected = "f7ae51da54d710414639429d120a62bbb13cf8f42131fce7d6ad40b7c5c55698"
    assert sha256((source / "UnFire_SQLite_Schema_20261101.sql").read_bytes()).hexdigest() == expected
    assert sha256(db.SCHEMA_PATH.read_bytes()).hexdigest() == expected


def test_initialization_creates_full_empty_schema(database):
    """設計の件数と健全性を確認し、推測した業務データが投入されていないことも調べる。"""
    with closing(db.connect_db(database)) as connection:
        assert db.check_database(connection) == {
            "tables": 19, "columns": 155, "foreign_keys": 32,
            "indexes": 27, "triggers": 34,
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # INSERT文がなければ、担当者・基準値・在庫などの初期データも存在しない。
        assert not any(line.startswith("INSERT INTO") for line in connection.iterdump())


def test_each_connection_enables_constraints(database):
    """接続設定が接続ごとに独立し、不正な参照を実際に拒否することを確認する。"""
    with closing(db.connect_db(database)) as first, closing(db.connect_db(database)) as second:
        first.execute("PRAGMA foreign_keys=OFF")
        assert second.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert second.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
        assert not second.in_transaction
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            with db.transaction(second):
                second.execute("INSERT INTO shelter_warehouses VALUES (?, ?)", (1, 1))


def test_missing_database_is_not_created(app):
    """通常接続でDBが見つからない場合、空DBを作らずエラーになることを確認する。"""
    path = Path(app.config["DATABASE"])
    with pytest.raises(sqlite3.OperationalError):
        db.connect_db(path)
    assert not path.exists()


@pytest.mark.parametrize("has_data", [False, True])
def test_reinitialization_preserves_existing_file(app, database, has_data):
    """空のDBとデータ入りDBの両方で、再初期化を拒否し内容を維持することを確認する。"""
    # parametrizeでhas_dataの値を変え、同じテストを2通りの条件で実行する。
    if has_data:
        with closing(db.connect_db(database)) as connection:
            with db.transaction(connection):
                connection.execute("INSERT INTO operators VALUES (?, ?)", (1, "Test operator"))
    before = database.read_bytes()
    with app.app_context(), pytest.raises(FileExistsError):
        db.init_db()
    assert database.read_bytes() == before


def test_even_existing_empty_file_is_preserved(app):
    """テーブルのない0バイトのファイルでも、既存ファイルとして上書きを拒否する。"""
    path = Path(app.config["DATABASE"])
    path.touch()
    with app.app_context(), pytest.raises(FileExistsError):
        db.init_db()
    assert path.read_bytes() == b""


def test_failed_initialization_removes_only_new_database(app, tmp_path, monkeypatch):
    """不正SQLで初期化を失敗させ、作成途中のDBが除去され、再実行できることを調べる。

    monkeypatchはテスト中だけ設定などを差し替える仕組み。正本SQL自体は変更しない。
    """
    bad_schema = tmp_path / "bad.sql"
    bad_schema.write_text("BEGIN; CREATE TABLE partial (id INTEGER); INVALID SQL;", encoding="utf-8")
    monkeypatch.setattr(db, "SCHEMA_PATH", bad_schema)
    with app.app_context(), pytest.raises(sqlite3.Error):
        db.init_db()
    assert not Path(app.config["DATABASE"]).exists()
    # SQLの参照先を元へ戻すと、手動でDBを消さなくても初期化をやり直せる。
    monkeypatch.undo()
    with app.app_context():
        assert db.init_db().is_file()


def test_context_reuses_connection_and_closes_with_rollback(app, database):
    """同じ処理内での接続再利用と、終了時の切断・未確定データの取消を確認する。"""
    with app.app_context():
        connection = db.get_db()
        assert db.get_db() is connection
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO operators VALUES (?, ?)", (1, "Uncommitted"))
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with app.app_context():
        assert db.get_db() is not connection
        assert db.get_db().execute("SELECT count(*) FROM operators").fetchone()[0] == 0


def test_successful_transaction_is_visible_to_another_connection(database):
    """正常終了した更新が確定し、別の接続からも読み取れることを確認する。"""
    with closing(db.connect_db(database)) as first, closing(db.connect_db(database)) as second:
        with db.transaction(first):
            first.execute("INSERT INTO operators VALUES (?, ?)", (1, "O'Brien"))
        assert second.execute("SELECT name FROM operators").fetchone()[0] == "O'Brien"


def test_statement_abort_rolls_back_previous_writes(database):
    """後のSQLが不正参照で失敗した場合、先に成功した登録も取り消すことを確認する。"""
    with closing(db.connect_db(database)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            with db.transaction(connection):
                connection.execute("INSERT INTO operators VALUES (?, ?)", (1, "Rolled back"))
                connection.execute("INSERT INTO shelter_warehouses VALUES (?, ?)", (1, 1))
        assert not connection.in_transaction
        assert connection.execute("SELECT count(*) FROM operators").fetchone()[0] == 0


def test_interruption_rolls_back(database):
    """Ctrl+Cに相当する中断でも、途中の登録を保存しないことを確認する。"""
    with closing(db.connect_db(database)) as connection:
        with pytest.raises(KeyboardInterrupt):
            with db.transaction(connection):
                connection.execute("INSERT INTO operators VALUES (?, ?)", (1, "Rolled back"))
                raise KeyboardInterrupt
        assert not connection.in_transaction
        assert connection.execute("SELECT count(*) FROM operators").fetchone()[0] == 0


def test_nested_transaction_does_not_commit_outer_work(database):
    """トランザクションの入れ子を拒否し、外側の途中更新も残らないことを確認する。"""
    with closing(db.connect_db(database)) as connection:
        with pytest.raises(RuntimeError, match="Nested"):
            with db.transaction(connection):
                connection.execute("INSERT INTO operators VALUES (?, ?)", (1, "Rolled back"))
                with db.transaction(connection):
                    pass
        assert connection.execute("SELECT count(*) FROM operators").fetchone()[0] == 0


def test_lock_failure_does_not_leave_partial_work(database):
    """別接続が更新中で書込み権を得られないとき、競合した側の更新を残さない。"""
    with closing(db.connect_db(database)) as first, closing(db.connect_db(database, timeout=0.01)) as second:
        with db.transaction(first):
            first.execute("INSERT INTO operators VALUES (?, ?)", (1, "First"))
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with db.transaction(second):
                    second.execute("INSERT INTO operators VALUES (?, ?)", (2, "Second"))
            assert not second.in_transaction
        assert [row[0] for row in second.execute("SELECT operator_id FROM operators")] == [1]


def test_read_transaction_does_not_reserve_writer_lock(database):
    """読取用BEGINの直後は書込み権を予約せず、他の接続が更新できることを確認する。

    読取側が最初のSELECTを行う前に更新するテストであり、読取中の全競合を扱うものではない。
    """
    with closing(db.connect_db(database)) as reader, closing(db.connect_db(database)) as writer:
        with db.transaction(reader, write=False):
            with db.transaction(writer):
                writer.execute("INSERT INTO operators VALUES (?, ?)", (1, "Writer"))
            assert reader.execute("SELECT count(*) FROM operators").fetchone()[0] == 1
        assert not reader.in_transaction


def test_deferred_fk_commit_failure_rolls_back_everything(database):
    """SQLは成功してもCOMMIT時に参照不整合が分かった場合、関連更新を全部取り消す。"""
    with closing(db.connect_db(database)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            with db.transaction(connection):
                connection.execute(
                    "INSERT INTO warehouses (warehouse_id, name, facility_type, address) "
                    "VALUES (?, ?, ?, ?)", (1, "Test warehouse", "Test", "Test address")
                )
                # run_idの参照検査は保存確定時まで待つため、INSERTは通るがCOMMITは失敗する。
                connection.execute(
                    "INSERT INTO calculation_warehouse_snapshots "
                    "(run_id, warehouse_id, warehouse_name) VALUES (?, ?, ?)",
                    (1, 1, "Test warehouse"),
                )
                assert connection.execute(
                    "SELECT count(*) FROM calculation_warehouse_snapshots"
                ).fetchone()[0] == 1
        assert not connection.in_transaction
        assert connection.execute("SELECT count(*) FROM warehouses").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM calculation_warehouse_snapshots").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_retention_trigger_failure_restores_preceding_update(database):
    """削除禁止トリガーで失敗した場合、その前の名前変更も取り消されることを確認する。"""
    with closing(db.connect_db(database)) as connection:
        with db.transaction(connection):
            connection.execute("INSERT INTO operators VALUES (?, ?)", (1, "Original"))
        with pytest.raises(sqlite3.IntegrityError, match="retain_master_or_stock"):
            with db.transaction(connection):
                connection.execute("UPDATE operators SET name=? WHERE operator_id=?", ("Changed", 1))
                connection.execute("DELETE FROM operators WHERE operator_id=?", (1,))
        assert connection.execute("SELECT name FROM operators").fetchone()[0] == "Original"


def test_negative_stock_is_rejected_without_changing_inventory(database):
    """負の在庫数量がDBのCHECK制約に拒否され、元の数量が維持されることを確認する。"""
    with closing(db.connect_db(database)) as connection:
        with db.transaction(connection):
            connection.execute(
                "INSERT INTO warehouses (warehouse_id, name, facility_type, address) "
                "VALUES (?, ?, ?, ?)", (1, "Test warehouse", "Test", "Test address")
            )
            connection.execute(
                "INSERT INTO items (item_id, name, category, quantity_unit, is_divisible, near_expiry_days) "
                "VALUES (?, ?, ?, ?, ?, ?)", (1, "Test item", "Test", "piece", 0, 30)
            )
            connection.execute(
                "INSERT INTO stocks (stock_id, warehouse_id, item_id, location, quantity, expiry_state) "
                "VALUES (?, ?, ?, ?, ?, ?)", (1, 1, 1, "Shelf A", 5, "none")
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            with db.transaction(connection):
                connection.execute("UPDATE stocks SET quantity=? WHERE stock_id=?", (-1, 1))
        assert connection.execute("SELECT quantity FROM stocks").fetchone()[0] == 5


def test_cli_initialization_check_and_rejection(app):
    """コマンド経由で未作成DBの検査・初期化・正常検査・再初期化拒否を確認する。"""
    # Flaskのテスト用実行機能を使い、ターミナル操作に相当する結果を調べる。
    # exit_codeは終了状態を表す数値で、0が成功、それ以外が失敗を示す。
    runner = app.test_cli_runner()
    missing = runner.invoke(args=["check-db"])
    assert missing.exit_code != 0
    assert not Path(app.config["DATABASE"]).exists()
    initialized = runner.invoke(args=["init-db"])
    assert initialized.exit_code == 0, initialized.output
    checked = runner.invoke(args=["check-db"])
    assert checked.exit_code == 0, checked.output
    assert "tables=19; columns=155; foreign_keys=32; indexes=27; triggers=34" in checked.output
    assert "foreign_key_check: 0 violations; integrity_check: ok" in checked.output
    rejected = runner.invoke(args=["init-db"])
    assert rejected.exit_code != 0
    assert "already exists" in rejected.output


def test_cli_rejects_uninitialized_file(app):
    """空ファイルに接続できても、必要な表がなければ検査コマンドが失敗することを確認する。"""
    Path(app.config["DATABASE"]).touch()
    result = app.test_cli_runner().invoke(args=["check-db"])
    assert result.exit_code != 0
    assert "does not match" in result.output


def test_configurable_path_and_startup_does_not_create_db(tmp_path, monkeypatch):
    """環境変数で接続先を変えられ、日本語や記号を含む場所でも初期化・接続できる。

    アプリの生成だけではDBが作られず、初期化コマンドで初めて作られることも確認する。
    """
    path = tmp_path / "別のフォルダ" / "test #1.sqlite3"
    monkeypatch.setenv("UNFIRE_DATABASE", str(path))
    application = create_app()
    assert application.config["DATABASE"] == str(path)
    assert not path.exists()
    result = application.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    with closing(db.connect_db(path)) as connection:
        assert db.check_database(connection)["tables"] == 19
