# UnFire P1修正の実装・検証報告

2026年11月13日（JST）。対象ブランチ：`fix/solveP1-issue`。比較元HEAD：`a869178c1ed6f6adcaff81721e44279543fbf837`。

対象はAUD-01〜03。3件とも着手時点で未修正であることを確認した。コード修正と自動検証は実施済み、実ブラウザの操作・描画は検証待ち。コミット、プッシュ、PR作成、マージは実施していない。

## 修正結果

| ID | 修正状況 | 主な変更ファイル | テスト結果 |
|---|---|---|---|
| AUD-01 | 修正済み・実ブラウザ確認待ち | `app/templates/shelters_form.html`、`app/static/js/shelters-form.js`、避難所のPython・JSテスト | 目標あり／なし、名称・住所・目標の独立保存、失敗時不変と個別表示、計算初期値への反映が成功 |
| AUD-02 | 実装済み・実ブラウザ確認待ち | `app/routes/pages.py`、`calculation_conditions.html`、`calculation-conditions.js/css`、計算・避難所一覧の導線、関連テスト | null、全所属・終了品目、明示移動、確認取消、422、通信失敗、実API連携、計算反映、保存結果不変が成功 |
| AUD-03 | 修正済み | `app/services/items.py`、`tests/test_items_api.py` | 在庫なし・整数整合は200、小数在庫／割当／基準は409。拒否時は全テーブル不変、500解消 |

## 採用仕様・承認範囲

- 詳細要件定義書2.0／2026-11-01：Q13・37・50・54〜58・73、F09・13、§8・9、V04・07〜09。
- DB設計・正本DDL 2026-11-01：TX10、`stocks`、`stock_allocations`、`stock_thresholds`、需要・換算、保存計算6表。
- API設計1.0／2026-11-04：SH04/05、IT04、DG01〜04、IC01、CA01、CR01/03。今回JSON APIの契約・ルート・DTOは変更していない。
- 画面設計のS009・S010は参考とし、旧仕様より最新確定要件を優先した。AUD-02の配置は依頼者が「独立した計算条件画面を追加する（推奨）」を選択して承認。`/calculation-conditions`を新設し、備蓄計算と避難所一覧から接続した。
- `AGENTS.md`、関連`implement-feature`・`sqlite-integrity`・`write-tests`・`implement-api`手順を確認。既存の監査報告は監査時点の記録として保持した。

## 利用者の操作と修正内容

### AUD-01：通常編集と正式目標を分離

原因は、名称・住所と目標人数・日数を同じpayloadでPATCHし、SH04の許可外フィールドで422となっていたこと。

避難所編集画面を「名称・住所」と「正式目標」の2フォームに分けた。
前者は`PATCH /api/v1/shelters/{id}`へ名称・住所のみ、後者は`PUT /api/v1/shelters/{id}/targets`へ人数・日数だけを送る。
編集後は画面を保持し、それぞれの欄に成功・失敗を表示する。一方の失敗を両方成功と表示しない。
新規登録では従来どおり正式目標を任意で登録でき、未入力なら項目を省略する。
保存中の重複送信を抑止し、通信失敗・読めない応答で入力を保持して結果確認を案内する。

正式目標の保存後に備蓄計算を開くと、既存の避難所取得処理から更新後の初期値を読み込む。
計算処理や正式目標PUTの業務仕様は変更していない。

### AUD-02：計算条件を画面から管理

備蓄計算の「計算条件」、避難所一覧の「計算条件を管理」、または`/calculation-conditions`から開く。
既存の倉庫系CSSと在庫フォームの見た目を共用し、必要な表示だけ専用CSSに追加した。

1. 「需要を追加」で共通単位・分割可否・使用量・根拠・版・適用条件を登録する。名称以外の空欄はnull。需要追加による全計算への影響を画面と確認ダイアログで説明する。
2. 需要を選んで「条件を開く」と、需要条件と全所属品目の換算を編集できる。登録終了品目を省かず、全件をDG04へ一括送信する。所属行の暗黙削除や他需要からの暗黙移動を作らない。
3. 共通単位変更時は全所属品目の係数・根拠再確認を促す簡易ダイアログを出す。未確認の係数は空欄にしてnullを送れる。
4. 「品目の所属・換算」から、未所属品目の追加、換算の個別変更、他需要への移動をIC01で明示する。現在の所属・管理単位・保存先共通単位を示し、移動先と係数・根拠を確認して保存する。終了品目も保持対象として選べる。
5. 変更後は新しい試算へ反映する。過去の保存済み結果の更新・再計算・上書きは行わない。

係数や使用量は文字列のまま送り、空欄だけをnullへ変換する。`"0"`や`"1.234"`をnull・1へ補完せず、既存APIの拒否を日本語の項目名とともに表示する。
一覧は新画面内で全ページを取得する。既存のP2である他画面のページ送りは変更していない。
入力の破棄を伴う切替・再取得では確認し、拒否・通信失敗ではフォームを保持する。
更新結果が不明なら自動再送せず、条件を再取得するまで保存を止める。保存成功後の再取得失敗も「保存済み」と「再取得失敗」を区別する。

### AUD-03：実在する列と関連を使用

`stock_allocations`は`item_id`を持たないため、汎用の`WHERE item_id=?`で検索すると500になっていた。
割当数量だけは`stocks`へ`stock_id`でJOINし、`s.item_id=?`で対象品目を特定するよう変更した。
在庫・基準の参照と409 `UNIT_HAS_STOCK`は既存のまま。全検証は既存の書込トランザクション内で実施する。
他品目の小数によって対象品目の変更を拒否しないことも確認した。

## 変更ファイル

| 区分 | ファイル |
|---|---|
| 品目サービス | `app/services/items.py` |
| 避難所画面 | `app/templates/shelters_form.html`、`app/static/js/shelters-form.js` |
| 条件画面・入口 | `app/routes/pages.py`、`app/templates/calculation_conditions.html`、`app/static/js/calculation-conditions.js`、`app/static/css/calculation-conditions.css` |
| 導線 | `app/templates/calculations.html`、`app/templates/shelters.html` |
| Python回帰 | `tests/test_items_api.py`、`tests/test_shelters_api.py`、`tests/test_calculation_conditions_page.py` |
| JS回帰・連携 | `tests/shelters-form-ui.test.cjs`、`tests/calculation-conditions-ui.test.cjs`、`tests/helpers/calculation-conditions-harness.cjs`、`tests/p1-ui-api-flow.cjs` |
| 操作・結果説明 | `README.md`、本報告 |

## 検証結果

実行環境：Windows／PowerShell、Python3.15.2、SQLite3.53.4、Flask3.1.3、pytest9.2.0、Node v24.19.0。
すべてリポジトリルートで実行した。

| 検証 | 結果 |
|---|---|
| AUD-03修正前の追加回帰 | 6ケース中5失敗・1成功。失敗は今回の500を再現したもの。修正後は品目API全12件成功 |
| 追加Python | 14件：品目6、避難所6、条件画面と実HTTP連携2 |
| 全Python | **452 passed in 65.02s**。既存438＋追加14。失敗・エラー・skip 0 |
| 全JS | **25件成功**。既存14＋避難所5＋条件画面6。失敗・skip 0 |
| 実JS→実HTTP→SQLite | 成功。pytest内でlocalhostの一時サーバーを起動し、DOM代替上の実JSから実APIへ送信。終了時にサーバーを停止 |
| 正本・実行DDL | 変更なし。SHA-256はいずれも`f7ae51da54d710414639429d120a62bbb13cf8f42131fce7d6ad40b7c5c55698`。正本同一性の既存テストも成功 |
| DB構造 | 実HTTP検証前後の`sqlite_schema`全定義が一致。19表155列32FK27明示索引34トリガー、FK違反0 |
| 既存DB | 初期化・更新・補正なし。`instance/unfire.sqlite3`のSHA-256は前後とも`db14793aa2d3c19192df08ecb23a04bd24f7a291ac6b54bfc4f89a664afc5a58` |
| 差分・構文 | `git diff --check`、変更JSとテストスクリプトの`node --check`が成功 |
| 実ブラウザ | **未実施**。同作業の接続確認でブラウザアクセスホストが利用不可。DOM代替・Jinja描画・実HTTP成功を実ブラウザ確認済みとは扱わない |

Windowsの既知のpytest一時領域制約を避け、毎回UUID付きの新規OS一時ディレクトリを使用した。
プロセス内でその一時領域だけ`Path.mkdir`のmodeを通常値にした。ソース・pytest設定・既存領域のACLは変更していない。
更新検証は正本DDLから作った隔離DBのみで、既存の開発DBを使用していない。

全体実行に使った方法：

```powershell
@'
import pathlib, tempfile, uuid, pytest, sys
base = pathlib.Path(tempfile.gettempdir()) / ('unfire-p1-final-' + uuid.uuid4().hex)
original = pathlib.Path.mkdir
def mkdir(self, mode=0o777, parents=False, exist_ok=False):
    if self == base or base in self.parents:
        mode = 0o777
    return original(self, mode=mode, parents=parents, exist_ok=exist_ok)
pathlib.Path.mkdir = mkdir
sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', '--basetemp', str(base)]))
'@ | .\.venv\Scripts\python.exe -B -
node tests/calculations-ui.test.cjs
node tests/map-ui.test.cjs
node tests/stocks-movements-ui.test.cjs
node tests/warehouse-settings-ui.test.cjs
node tests/shelters-form-ui.test.cjs
node tests/calculation-conditions-ui.test.cjs
```

### 受入条件との対応

| 条件 | 確認結果 |
|---|---|
| 目標あり／なしで名称・住所編集 | Python4ケースとJS2ケースで成功。編集フォームの名称・住所だけをPATCHへ送信 |
| 正式目標だけ更新・計算初期値 | 専用PUT成功。実JS→HTTPでも50人1日から100人2日へ更新し、計算の省略時目標が100人2日となることを確認 |
| 保存失敗・部分成功 | 各APIに試験用失敗トリガーを入れた隔離DBで、先の保存を維持し、失敗操作による部分更新がないことを全表比較。JSは欄ごとの成功・失敗を分離 |
| 条件を画面上で設定 | DOM代替で実テンプレート・実JSを使い、DG/ICの設定要求はフォーム操作から生成。実APIへ接続して成功 |
| 全所属・終了品目・明示移動 | 終了品目を含む2品目一括更新、専用ICで終了品目を別需要へ移動、対応保持を確認 |
| 未設定・0・桁超過 | 空欄はnull。0／1.234は実APIで422となり、登録済み条件不変・入力保持。null係数は未設定として保存できる |
| 計算へ反映 | 架空の水600L、100人2日、使用量3→4、換算1→1.25。R600/A600からR800/A750/S50/93.8%/93人1日へ変化し、独立した期待値と一致 |
| 保存済み結果不変 | 上記変更・未設定保存・所属移動後も、変更前に保存した結果と全主要写しを実APIから取得して完全一致。既存の保存6表不変テストも成功 |
| 在庫・割当等の維持 | 実HTTP検証前後でstocks・allocations・thresholds・movements・状態／期限履歴等を比較し不変。既存の在庫・入出庫・割当・計算・GIS回帰も成功 |
| 分割可否の正常・拒否 | 在庫なし、整数在庫・割当・基準、他品目だけ小数は200。自品目の小数在庫／割当／基準は既定409、全表不変。実品目JSからの変更も成功 |

## 人間が行う手動確認

実ブラウザの画面検証と独立レビューが残るため、受入完了とは報告しない。専用の受入DBと架空データを使い、次を確認する。

1. 正式目標あり／なしの避難所編集で名称だけ・住所だけを保存する。正式目標を別に保存し、計算画面を開いて初期値を確認する。一方の通信を遮断し、別欄の成功と混同せず入力が残ることを確認する。
2. 備蓄計算と避難所一覧のリンクから計算条件画面を開く。空状態、読込中、取得失敗と再取得、狭幅の表、ラベルとキーボード操作を確認する。
3. 需要を未設定のまま追加し、追加の影響と簡易確認を読む。使用量・根拠・版・条件、共通単位、品目対応・換算を画面から設定する。0・小数第3位を拒否し、空欄は未設定になることを確認する。
4. 終了品目を含む全所属品目を一括編集する。共通単位変更時の注意と確認を読む。所属変更は専用操作で旧先→新先を確認して実行する。
5. 変更前の計算を保存し、条件を変更して再計算する。新計算に反映され、旧保存結果・根拠・帰属が変わらないことを確認する。通信断時の結果確認と、確認取消・入力保持も操作する。
6. 品目の分割可→不可を在庫なし／整数のみで実施し、小数在庫・割当・基準では409の理由が読めることを確認する。

未解決のP1仕様判断はない。P2・P3の修正、日常基準編集UI、既存一覧のページ送り、JSON共通契約の統一、CI整理、DB移行・初期データの自動投入は対象外として実施していない。
