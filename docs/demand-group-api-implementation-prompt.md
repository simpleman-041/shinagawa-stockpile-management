# 需要グループ・使用量基準・品目換算：調査結果と実装依頼プロンプト

調査日：2026年11月11日（JST）

## 今回確認した依頼範囲

- 今回の成果物は調査結果と、後で実装を依頼するためのプロンプト。機能実装は行っていない。
- 後の実装対象はAPI・DB保存処理・テスト。画面、備蓄計算本体、計算結果の保存APIは対象外。
- 依頼者は要件定義書2.0、DB設計2026年11月1日版、API設計1.0を今回の実装仕様として採用すると回答した。
- 他担当が作業中の箇所、触らせたくないファイル・機能はないとの回答。
- 画面の不足は別途提案を確認して決める。今回、画面設計の確定をAPI実装の前提に追加しない。

## 調査結果

### 現在の実装

調査時のブランチは `feature/item-demand-group/m05m06`、HEADは `a21c77f`。着手時の作業ツリーに変更はなかった。リモートの最新状態は取得していない。

| 項目 | 現状と実装への意味 |
| --- | --- |
| 構成 | Flask / Jinja2 / sqlite3。`app/__init__.py` の `create_app()` でBlueprintを登録 |
| 既存機能 | 倉庫・品目・避難所のAPI、サービス、画面がある。需要グループ・品目換算のAPIとサービスはない |
| 品目との接続 | `app/routes/items.py` と `app/services/items.py` に一覧・作成・取得・編集・登録終了がある。換算専用APIは未実装 |
| DB | `demand_groups` と `item_conversions` は `database/schema.sql` に定義済み。新規テーブルや `usage_standards` の追加は不要 |
| 使用量基準 | `demand_groups` に共通単位、分割可否、1人1日使用量、出典、版または更新日、適用条件を保存 |
| 換算 | `item_conversions` に品目と需要の対応、係数100倍整数、出典、版または更新日、適用条件を保存。主キーが `item_id` のため1品目1需要 |
| 共通DB処理 | `app/db.py` の `get_db()` と `transaction()` を利用。書込は `BEGIN IMMEDIATE`、読取は `BEGIN`、接続ごとに外部キー・再帰トリガーを有効化 |
| 共通HTTP処理 | 既存の各routesに個別の入力・応答処理がある。全API共通の検証モジュールが存在する前提では進められない |
| 保存済み結果 | 計算用6表は定義済みで更新・削除禁止。今回の条件更新から触れない |

要件、DB設計、DDLのSHA-256はAPI設計書§1.1の値と一致した。正本DDLと実行用 `database/schema.sql` も同一である。

### 必要な作業

1. DG01〜DG04、IC01の5操作について、採用済み設計と入力・出力・拒否条件を照合する。
2. 需要条件と全所属換算を同一トランザクションで保存するサービスを追加する。
3. 5操作を提供するBlueprintを追加し、既存アプリに登録する。
4. null、数値精度、所属全件更新、所属先変更、登録終了品目、途中失敗を対象にテストを追加する。
5. 既存テストを含めて検証し、画面担当向けにAPIの利用方法と確認ダイアログの責任範囲を記録する。

スキーマ変更、運用値の投入、画面追加を伴わず着手できる範囲である。使用量・換算係数の実値は今回確認していない。未確認値はnullで保存する契約があり、実値の収集はこの実装の着手条件ではない。

### 調査時の検証

- 実行環境：Python 3.15.2、SQLite 3.53.4、Flask 3.1.3、pytest 9.2.0。
- 既存テスト：46件成功。
- 成功したコマンド：`.\.venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider`。
- 制限環境ではpytestの一時フォルダにアクセス拒否が発生したため、成功結果は権限制限を外した実行によるもの。隔離一時DBを使用し、開発DBは変更していない。
- 画面操作、実運用データの確認、新機能の動作検証は行っていない。既存テストの成功は未実装APIの品質を保証しない。

## 実装依頼プロンプト

以下の引用ブロック全体を、後の実装依頼に使用してください。

```text
C:\Projects\shinagawa-stockpile-management で、需要グループ・使用量基準管理と、品目の需要グループ対応・換算設定を実装してください。

【目的と承認済み範囲】
職員が後から画面経由で設定できるよう、API・DB保存処理・自動テストまでを完成させてください。画面・JavaScriptの実装は別担当です。
今回の依頼者は、下記3資料をこの機能の実装仕様として採用済みです。「API設計書が契約案と記載されている」という理由だけで同じ採用確認を繰り返す必要はありません。
他担当が作業中の箇所や、変更禁止の機能・ファイルはないと確認済みです。
調査時点からの差分は改めて確認し、新たに判明した仕様の不足・矛盾だけを、根拠・影響・推奨案・人間の判断事項とともに提示してください。独立した確定範囲は進めてください。

【適用するルールと正本】
ルートのAGENTS.md、CONTRIBUTING.mdと、適用範囲の追加指示に従ってください。
機能全体にはimplement-feature、APIにはimplement-api、DB操作にはsqlite-integrity、テストにはwrite-testsを適用してください。
調査時の実ファイルは次のとおりです。SKILL.mdという名前に限定せず確認してください。
- .agents/skills/implement-feature/SKILL (2).md
- .agents/skills/implement-api/SKILL.md
- .agents/skills/sqlite-integrity/SKILL (5).md
- .agents/skills/write-tests/SKILL (6).md

採用資料：
- local-specs/requirements/要件定義書.md：版2.0、2026-11-01。主に§8、Q50、Q54〜58、Q72・73、P04、U03・04。
- local-specs/database/UnFire_DB_Design_20261101.docx：特に§3、§8 TX10、§9、需要・換算の列定義。
- local-specs/api/UnFire_API_Design_20261104.md：版1.0、特に§2、§3.1、§4のDG01〜04・IC01、GroupConditions、§5 TX10、§10.9・10.10。
- local-specs/database/UnFire_SQLite_Schema_20261101.sql と database/schema.sql：同一内容の採用済みDDL。

最新要件・最終判断を優先し、DB設計、DDL、API設計を照合してください。古い資料や現在のコードの挙動で最新仕様を上書きしないでください。

【最初に確認する現行構成】
git status、現在のブランチ・HEAD・developとの差分、関連する既存変更を確認してください。調査時は feature/item-demand-group/m05m06、HEAD a21c77f でした。ブランチの切替や他人の変更の破棄を無条件に行わないでください。
app/__init__.py、app/db.py、app/routes/items.py、app/services/items.py、tests/test_items_api.py、tests/test_db.py を確認してください。
既存の倉庫・品目・避難所APIと各画面を維持し、必要最小限の登録変更で追加してください。既存APIの検証処理を流用する際も、今回の正本の契約を満たすか確認してください。

【実装する5操作】
API接頭辞は /api/v1 です。
1. DG01 GET /demand-groups
   需要グループ一覧。追加の検索条件は設けず、共通limit・offset、主キー昇順、page付き応答に従う。
2. DG02 POST /demand-groups
   GroupWriteで作成。201、data:DemandGroup、Locationは当該グループのconditions取得URL。
3. DG03 GET /demand-groups/{group_id}/conditions
   data:{group:DemandGroup, conversions:ItemConversion[]}。登録終了品目も含め、所属品目の換算を全件返す。
4. DG04 PUT /demand-groups/{group_id}/conditions
   group:GroupWrite と conversions配列で需要条件・全所属換算を原子的に更新し、GroupConditionsを200で返す。
5. IC01 PUT /items/{item_id}/conversion
   group_id と ConversionWriteの全キーを受け取り、品目の需要対応を設定・置換する。新規対応は201、更新は200、data:ItemConversion。

この5操作以外のCRUDを補完しないでください。特に需要削除、換算解除、独自のGET /items/{id}/conversion、承認APIを追加しないでください。

【入力と保存の要点】
GroupWriteの必須集合は次の7キーです：
name, calculation_unit, is_divisible, daily_usage, source_text, version_or_date, conditions
nameは空でない文字列。他6項目はそれぞれ仕様の型またはnull。未設定値もキーを省略せずnullで送ります。
ConversionWriteの必須集合は次の4キーです：
factor, source_text, version_or_date, conditions
全て未確認ならnullを許し、空文字では代替しません。
DG04のconversionsの各要素はitem_idとConversionWriteの全キー、IC01はgroup_idとConversionWriteの全キーを受け取ります。

- 使用量基準はdemand_groupsへ、品目ごとの換算と根拠はitem_conversionsへ保存する。usage_standardsテーブルは追加しない。
- 1品目1需要。需要への対応は明示登録だけとし、品目名・分類・単位の類似から推定しない。
- 換算の向きは「品目の管理単位1あたり、共通計算単位でfactor」。管理単位や物理在庫数量を換算値で書き換えない。
- factorは正、小数第2位まで。入力は十進文字列、Decimal等で正確に検証して100倍INTEGERへ保存する。nullを1へ補完しない。factor_x100の投稿は拒否する。
- daily_usageは正、小数第2位まで。共通単位が分割不可なら整数値のみ。REAL保存前の表現可能性もAPI設計書§2.2に従って検証する。
- 係数100倍値はSQLite signed 64-bit範囲内。IDも同範囲の正の10進整数文字列。bool、数値JSONによるID・Dec、符号、指数、先頭0、不正桁、非有限値を契約に従って拒否する。黙って丸めない。
- 応答ではIDとfactor_x100を整数文字列、factorを2桁の十進文字列、nullable項目を明示null、is_divisibleをbooleanまたはnullで返す。
- 出典、版または更新日、適用条件は需要基準と品目換算それぞれに保存する。未完の編集中保存を許し、根拠欠落を仮値で埋めない。
- DG04は現在の所属品目を全件含める。欠落は422 INCOMPLETE_CONVERSION_SET。欠落を削除扱いにしない。重複item_idを含む不正集合も拒否する。
- DG04で未所属品目の追加は可能。他グループに所属する品目の移動はIC01で明示する。
- 需要単位変更時は現在所属する全品目について換算を再確認する。DG04で係数を明示提出し、未確認ならnullを指定する契約を守り、旧係数を暗黙に引き継がない。サーバーは所属集合と値を再検証する。独自の確認フラグや承認処理は追加しない。
- 登録終了品目の対応・換算も維持・編集できる。登録終了だけを理由に取得・設定から除外しない。
- 新需要グループは将来の計算で対象に含まれる。計算側が全グループを対象とする契約を変えず、根拠不足のグループを黙って除外する設計にしない。
- 名前の一意制約、需要名の独自enum、推定した業務上限など、資料にない制約を追加しない。

【HTTPとトランザクション】
routesはHTTP境界、servicesは業務検証と保存に分けてください。
app.db.get_db() と transaction() を共用し、関連する存在・所属・値の検証と全更新を同一接続のBEGIN IMMEDIATE内で行ってください。補助関数でcommitせず、入れ子トランザクション、書込途中の別接続、INSERT OR REPLACEでの削除再作成を避けてください。
DG03の需要と全換算、DG01のcountと一覧はそれぞれ同じ読取トランザクションで取得してください。
途中例外・COMMIT失敗・制約違反では全更新をrollbackしてください。

JSONの重複キー、不正JSON、オブジェクトでない本文は400。未知・重複クエリー、未知キー、読取専用キー、必須欠落、型・精度・範囲違反は対応する422で返してください。
パス対象の不存在は404 RESOURCE_NOT_FOUND、本文中の参照先不存在は422 REFERENCE_NOT_FOUNDとして区別してください。
Content-Type不正、404・405、ストレージロック・接続/I/O障害、内部障害も採用契約に対応させてください。STORAGE_BUSYだけretryable:trueです。既存の各routesの例外処理をそのまま正解としてコピーしないでください。
エラーはerror:{code,message,fields,details,retryable}、本文fields.pathはJSON Pointer、クエリーは/query/...、パスは/path/...とします。SQLや内部例外を応答に出さないでください。
新規APIの404・405がHTMLにならないよう、必要な範囲で処理してください。画面の404等や対象外APIまで一括改修する場合は、必要性と影響を先に示してください。

【今回の対象外】
画面・JS・CSS、計算条件の簡易確認ダイアログ、在庫数量・管理単位の変更、物理在庫統合、倉庫対応・共有割当、日常管理基準、備蓄計算本体、計算結果保存・履歴API、認証・権限・承認ワークフロー、運用初期値投入、既存DBの移行、DDL変更。
需要条件・換算の保存と、「計算結果の保存」は別機能です。今回は前者だけです。
Q56の簡易確認ダイアログは画面担当の責任として引継ぎ、API側に承認エンドポイントやconfirmedフィールドを足さないでください。画面未実装を理由に今回のAPI実装を止めないでください。
使用量、換算係数、出典等の実運用値は採用未確認です。食料・飲料水・携帯トイレも推測値でseedしないでください。架空値はテスト専用fixtureに限定してください。
保存済み計算6表・履歴を変更せず、条件変更を過去結果に遡及適用しないでください。

【変更ファイルの目安】
- 新規 app/routes/demand_groups.py：5操作用Blueprint。IC01もここで登録する案とし、既存itemsルートと重複させない。
- 新規 app/services/demand_groups.py：一覧、条件取得、需要作成、一括更新、品目対応設定。
- app/__init__.py：Blueprint登録を最小限追加。
- 新規 tests/test_demand_groups_api.py：HTTP契約・保存結果のテスト。
- 必要に応じ tests/test_demand_groups_service.py：原子性等のサービス・DBテスト。
- README.md：今回提供するAPIと実行・検証方法を実態に合わせて最小限追記。
これは構成案です。責務を守れる通常の実装詳細は自律的に選んでください。共通部品の広範囲な再編や依存追加は、この機能のために必要かを先に説明してください。

【受入条件と検証】
承認DDLを使うtmp_path等の隔離DBとFlaskテストクライアントで、少なくとも次を確認してください。
1. 一覧0件、複数件、主キー順、limit/offset/total、全nullable項目を含む応答。
2. 需要作成、nullを含む編集中保存、取得、201とLocation。既存行を再取得して値が永続化したこと。
3. 換算の新規201・更新200、未所属からの対応、IC01による別需要への移動、移動前後のDG03の所属集合。
4. factor "0.01"→1、"1.23"→123、応答factor "1.23"とfactor_x100 "123"。null保持、0・負数・3桁小数・64-bit超過を拒否しDB不変。
5. 使用量の正値・精度・表現範囲、共通単位が分割不可の場合の小数拒否。is_divisible:nullやfalseを混同しない。
6. DG04で需要と複数品目の根拠を一括更新。既存所属の欠落・重複、他需要所属の混入を拒否し、部分更新が残らない。
7. 共通単位の変更、全所属品目の明示換算、未確認係数null、登録終了品目を含む取得・更新。
8. 不正JSON、重複JSONキー、本文ルート不正、必須欠落、未知・読取専用キー、型不正、空白だけのText、不在パスと不在参照ID、未知・重複クエリー、Content-Type、未提供メソッド。
9. 書込途中に失敗するケースで需要条件と全換算が操作前のまま。独立接続でロック拒否時に部分保存がないこと。FKが有効で不正参照を拒否すること。
10. 承認DDLに適合する保存済み計算の最小fixtureを作り、需要条件・換算変更の前後で保存済み写しが変わらないこと。現在のitemsやstocksも変更しないこと。
11. 既存の品目・倉庫・避難所・DBテストの回帰。失敗を期待値の変更・skip・削除で隠さない。
追加テストを先に実行し、問題を解消してから既存テストを含む全体を実行してください。調査時の既存テストは46件成功でした。新しい差分や失敗がなければ同じ全体テストを繰り返す必要はありません。
画面・ブラウザは今回の対象外なので、ブラウザ確認済みとは報告しないでください。

【完了報告】
実装した5操作と利用結果、変更ファイル、対象外、採用仕様・依頼者判断、受入条件ごとの検証結果、実行コマンドと成功/失敗/未実行件数、既存機能への影響をまとめてください。
画面担当向けに、DTO・nullの扱い、換算の向き、全件PUT、移動操作、需要追加の計算対象への影響、変更前の簡易確認ダイアログを引き継いでください。
未解決の仕様矛盾や必須検証の未実行があれば、その範囲を「仕様確認待ち」「検証待ち」と明記し、今回のAPI範囲の完了と画面を含む機能全体の完了を区別してください。
```
