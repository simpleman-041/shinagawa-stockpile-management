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
現在のFlask入口はDB用CLIと接続管理に加え、倉庫・品目・避難所のAPIと画面、
需要グループ・使用量基準・品目換算のAPIを提供しています。

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
業務上の更新はservicesへ実装し、この接続・トランザクション経路を共用します。

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
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

pytestの一時フォルダに検証専用DBを作成するため、`instance/` の開発DBは更新しません。
初期化、接続設定、制約、ロールバック、ロック失敗、再初期化拒否、CLIを検証します。
要件の対応範囲はQ34・Q35・Q71・Q74、DB設計2026年11月1日版、API設計1.0の§5.1・§8です。

需要グループAPIのテストだけを実行する場合：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_demand_groups_api.py -q
```

## 需要グループ・使用量基準・品目換算API

要件定義書2.0のQ50・Q54〜58・Q73・U03、DB設計2026年11月1日版のTX10、
API設計1.0のDG01〜04・IC01を採用しています。画面と備蓄計算本体は別の実装範囲です。

新規DBは前述の `init-db` で作成し、次のコマンドで起動できます。
既存の開発DBを初期化し直す必要はありません。

```powershell
.\.venv\Scripts\python.exe -m flask --app app run
```

全パスに `/api/v1` を付けます。本文はUTF-8の `application/json`、ID・数量・係数は文字列です。

| 操作 | パス | 成功応答 |
| --- | --- | --- |
| 一覧 | `GET /demand-groups?limit=50&offset=0` | 200、`data:DemandGroup[]` と `page:{limit,offset,total}` |
| 需要登録 | `POST /demand-groups` | 201、`data:DemandGroup`、Locationはconditions取得URL |
| 条件取得 | `GET /demand-groups/{group_id}/conditions` | 200、`data:{group,conversions}` |
| 条件一括更新 | `PUT /demand-groups/{group_id}/conditions` | 200、`data:{group,conversions}` |
| 品目対応設定・移動 | `PUT /items/{item_id}/conversion` | 初回201・更新200、`data:ItemConversion` |

`DemandGroup` は `group_id` と以下の需要登録本文の7キーを返します。
下書きでは `name` 以外をnullにできます。キー自体の省略はできません。
初期需要・基準値は自動投入しません。以下は運用値を含まない登録例です。

```json
{"name":"飲料水","calculation_unit":"L","is_divisible":true,"daily_usage":null,"source_text":null,"version_or_date":null,"conditions":null}
```

`ItemConversion` は `item_id,group_id,factor_x100,factor,source_text,version_or_date,conditions` を返します。
品目対応設定の本文は以下の5キーです。未確認の係数・根拠はそれぞれnullで保持します。

```json
{"group_id":"1","factor":null,"source_text":null,"version_or_date":null,"conditions":null}
```

- 換算の向きは「品目の管理単位1あたりの共通計算単位量」。係数は正の小数第2位までで、例えば `"1.23"` は `factor_x100:"123"` として保存・応答します。`factor_x100` は読取専用です。
- 使用量は需要ごとの1人1日量です。正の小数第2位まで、共通単位が分割不可の場合は整数値に限ります。nullと0は区別し、未設定を係数1や在庫0で補完しません。
- 条件一括更新の本文は `{"group":<需要登録本文>,"conversions":[<換算本文にitem_idを付け、group_idを除いたもの>,...]}` です。現在の所属品目を全件含め、各品目の係数と根拠を明示提出します。登録終了品目も含めてください。
- 未所属品目は一括更新で追加できます。他需要からの移動は品目対応設定で明示します。所属の欠落・重複・暗黙移動は422、欠落による削除や換算解除は行いません。
- 共通単位を変える際は全所属品目の換算を再確認し、未確認係数にはnullを指定します。画面側では変更前に簡易確認ダイアログを表示してください。APIに承認操作や `confirmed` はありません。
- 新規需要も将来の備蓄計算の対象に加わります。画面では追加時にその影響を案内してください。物理在庫と品目管理単位、保存済み計算は変更しません。
- 一覧の `limit` は1〜200（既定50）、`offset` は0以上（既定0）。主キー昇順で返し、その他の検索・並び替えクエリーは受け付けません。条件取得では所属換算全件を品目ID昇順で返します。
- エラーは `error:{code,message,fields,details,retryable}`。`fields.path` は `/group/daily_usage`、`/conversions/0/factor` 等で入力位置を示します。パス対象の不存在は404、本文の参照先不存在は422です。
- 保存は全件成功または全件取り消しです。ロック時は503 `STORAGE_BUSY` と `retryable:true`、接続・I/O障害は503 `STORAGE_UNAVAILABLE` とfalseを返します。通信断やCOMMIT結果不明ではGETで保存状態を確認してから再操作し、POSTを自動再送しないでください。

画面確認は今回の範囲に含めていません。隔離DBのテストでAPI応答・入力拒否・原子性・別接続ロック・保存済み計算6表の不変を検証します。

## 要件・設計資料

[local-specs/README.md](local-specs/README.md) を参照してください。

## 開発への参加

本プロジェクトはGitHubを利用して共同開発します。

開発を開始する前に、[CONTRIBUTING.md](CONTRIBUTING.md) を確認してください。

## 開発状況

開発中。掲載している機能は実装予定のものを含みます。
