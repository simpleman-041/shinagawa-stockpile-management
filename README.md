## プロジェクト概要

UnFireは、平常時の防災備蓄管理を支援するWebシステムです。

倉庫・品目・在庫数量・使用期限・保管場所・倉庫容量などの情報を一元管理し、避難所ごとの備蓄充足状況を可視化します。

職員が備蓄品の補充・入替・配置を検討するために必要な情報を提供することを目的としています。

本プロジェクトは大学の授業における6人チームでの試作開発です。

注意：このリポジトリは無料プランでルールセットを使うために一般公開されています。開発メンバーは個人情報や必要以上に大学の情報を書き込まないようにしてください！
## 主な機能

- 倉庫・品目・在庫情報の登録、編集、管理
- 備蓄品の入庫・出庫による数量更新
- 使用期限と期限接近状況の確認
- 倉庫ごとの容量使用率の表示
- 在庫の検索と絞り込み
- 避難所別の備蓄人数・日数の目安の表示
- 目標人数・日数に対する充足率・不足量の表示
- Leafletによる倉庫位置と備蓄状況の地図表示

## 使用技術

| 分類 | 技術 |
|---|---|
| バックエンド | Python、Flask |
| テンプレート | Jinja2 |
| フロントエンド | HTML、CSS、Bootstrap、JavaScript |
| 地図表示 | Leaflet |
| データベース | SQLite |
| DBアクセス | sqlite3 |

開発速度と学習コストの低さを重視して選定しました。

## ディレクトリ構成

```text
app/
├── routes/       # Flaskのルーティング
├── services/     # 業務ロジック
├── templates/    # Jinja2テンプレート
└── static/
    ├── css/      # CSS
    └── js/       # JavaScript

database/         # DB定義・初期化関連
tests/            # テスト
local-specs/      # 要件・画面・DB・API設計の参照資料
instance/         # ローカルDB（Git管理対象外）
```

## 開発環境のセットアップ

以下のコマンドはプロジェクト直下で、PowerShellから実行します。
仮想環境がない場合は先に `py -m venv .venv` を実行してください。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app init-db
.\.venv\Scripts\python.exe -m flask --app app check-db
```

`init-db` は `instance/unfire.sqlite3` を新規作成します。既存ファイルがある場合は、
空のファイルでも処理を拒否します。アプリ起動時や通常の接続時にはDBを作成しません。
初期の担当者・在庫・基準値などの業務データは投入しません。
現在のFlask入口はDB用CLIと接続管理を提供しており、画面と業務APIは未実装です。

`check-db` の正常時は、外部キー・再帰トリガーの有効化、外部キー違反0件、
`integrity_check: ok` に加え、19テーブル・155列・32外部キー・27明示索引・34トリガーを表示します。
これはDB構造の件数と健全性の確認であり、割当上限など全業務ルールの保証ではありません。

別の新規DBで試す場合は、接続先を指定できます。既存DBを変更・移行する機能はありません。

```powershell
$env:UNFIRE_DATABASE = Join-Path $PWD "instance\trial.sqlite3"
.\.venv\Scripts\python.exe -m flask --app app init-db
.\.venv\Scripts\python.exe -m flask --app app check-db
Remove-Item Env:UNFIRE_DATABASE
```

2026年11月4日の動作確認環境はPython 3.15.2、組込みSQLite 3.53.4、Flask 3.1.3です。
SQLite用の追加Pythonパッケージは不要です。

## DBを使う実装

Flaskのリクエスト又はアプリケーションコンテキスト内では、`app.db.get_db()` で接続を取得します。
同じコンテキストで接続を再利用し、終了時に未完了の更新をロールバックして接続を閉じます。
全接続で `foreign_keys=ON` と `recursive_triggers=ON` を設定・確認します。

```python
from app.db import get_db, transaction

# 書込みはBEGIN IMMEDIATE。業務検証と関連更新を同じブロックに置く。
with transaction(get_db()) as connection:
    # 確認・更新SQLでは値をプレースホルダーに渡す。
    connection.execute("INSERT INTO operators (operator_id, name) VALUES (?, ?)", (1, "テスト担当者"))

# 複数の読取りを同一時点で扱う場合はBEGIN。
with transaction(get_db(), write=False) as connection:
    rows = connection.execute("SELECT operator_id, name FROM operators").fetchall()
```

`transaction` の正常終了でCOMMITし、例外・中断・COMMIT時の遅延外部キー違反では全体をROLLBACKします。
ブロック内で手動COMMITや `executescript` を実行せず、トランザクションを入れ子にしないでください。
コンテキスト外で使う `connect_db(path)` の接続は呼出元が必ず閉じます。
業務上の更新は今後servicesへ実装し、この接続・トランザクション経路を共用します。

初期化に使う [database/schema.sql](database/schema.sql) は、
[提供SQL](local-specs/database/UnFire_SQLite_Schema_20261101.sql) の内容を変更せず複製したものです。
元SQL自身にBEGIN/COMMITがあるため、初期化は専用の新規接続で行います。
失敗時は今回新規作成したDBファイルだけを除去し、修正後に再実行できます。
スキーマ変更時は正本・実行用SQL・検証の期待値を一緒に見直してください。

接続とトランザクション制御の技術参照：
[Python sqlite3](https://docs.python.org/3/library/sqlite3.html)、
[FlaskのDB接続管理](https://flask.palletsprojects.com/en/stable/tutorial/database/)。

## 自動テスト

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

pytestの一時フォルダに検証専用DBを作成するため、`instance/` の開発DBは更新しません。
初期化、接続設定、制約、ロールバック、ロック失敗、再初期化拒否、CLIを検証します。
要件の対応範囲はQ34・Q35・Q71・Q74、DB設計2026年11月1日版、API設計1.0の§5.1・§8です。

## 要件・設計資料

[local-specs/README.md](local-specs/README.md) を参照してください。

## 開発への参加

本プロジェクトはGitHubを利用して共同開発します。

開発を開始する前に、[CONTRIBUTING.md](CONTRIBUTING.md) を確認してください。

## 開発状況

開発中。掲載している機能は実装予定のものを含みます。
