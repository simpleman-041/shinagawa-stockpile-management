# 倉庫対応・共有割当の実装・検証結果

2026年11月12日（JST）。実装済み・実ブラウザ検証待ち。

## 利用者の操作

避難所一覧の各行に「倉庫対応・共有割当」を追加した。
`/shelters/{shelter_id}/warehouse-settings`を開くと、現在の対応倉庫・専用／共有・各倉庫の全対応先・設定状態・確認事項を表示する。
避難所編集画面からも移動できる。

倉庫を選び、区分と対応避難所全件を選択して確認後に保存する。
専用は対応先1件、共有は0件以上を許可する。有効在庫がある倉庫の変更は数量0でも拒否する。
変更時は旧対応先と新対応先の全避難所を設定中へ戻し、同内容の再保存では状態を維持する。

共有割当一覧は、対応する共有倉庫の有効在庫を20件単位で表示する。
品目・場所・期限・管理単位・総数量・全避難所の割当済み合計・未割当・自分の割当数量を確認できる。
割当数量を保存すると同じ在庫IDと避難所IDの割当を置換し、0で対象行を解除する。
期限切れ・期限未確認・終了品目の有効在庫も現物の管理対象として表示する。

倉庫対応・割当・確認事項を確認して設定状態を保存する。
倉庫区分未設定、専用の件数不正、割当の対応・数量不整合がある場合は完了を拒否する。
未登録在庫・需要基準・使用量・換算・根拠不足を表示する。基準不足だけでは設定完了を拒否しない。
対応倉庫0件での完了、共有割当0を受け付ける。

失敗時は入力を保持し、自動再送を行わない。現在値の再取得ボタンで保存結果を確認できる。
成功後は倉庫・避難所・対応・割当を再取得し、影響する旧・新対応先の状態も取り直す。

## 採用資料・担当境界

今回の実装依頼に、前回採用した要件書2.0、DB設計・DDL 2026-11-01、API設計1.0を継続適用した。
主な対応はF06・F07、Q03・14〜16・65〜69、P02、U01・U02・U07、TX05・TX06、SH06〜08・AL01/02。
画面S009にある対応倉庫と割当の確認・編集を、既存避難所一覧と編集画面から開く専用画面として実装した。
割当はAPI契約に従い在庫ID単位で保存する。

既存の設定状態APIには検証がなかったため、新サービスへ移管した。
既存サービス`put_setup_state`からの呼出しも同じ検証を経由し、既存呼出元の不存在時None・数値ID表現を保持する。
共通入口の変更はBlueprint登録、対象APIの404・405応答と画面ルート追加。
備蓄計算本体・結果保存・容量集計・基準編集画面は対象外。

## API

接頭辞は`/api/v1`。IDと数量は文字列。専用／共有を施設種別から推測せず明示する。

| 操作 | メソッド・パス | 成功 |
| --- | --- | --- |
| 現在の対応・状態・警告 | GET /shelters/{shelter_id}/warehouse-settings | ShelterWarehouseSettings、200 |
| 倉庫の区分・全対応先 | PUT /shelters/{shelter_id}/warehouse-settings/warehouses/{warehouse_id} | WarehouseSettingResult、200 |
| 設定中／完了 | PUT /shelters/{shelter_id}/warehouse-setup | Shelter、200 |
| 共有割当候補 | GET /shelters/{shelter_id}/allocations | AllocationCandidate配列、page、200 |
| 在庫ごとの割当・解除 | PUT /shelters/{shelter_id}/allocations/{stock_id} | AllocationResult、200 |

対応更新本文は`{"allocation_mode":"shared","shelter_ids":["1","2"]}`。
状態更新は`{"setup_state":"complete"}`、割当は`{"quantity":"2"}`。
確認チェックは画面で扱い、API本文に独自キーを追加しない。
一覧クエリーは`warehouse_id,limit,offset`で、API既定50件・最大200件・在庫ID昇順。

## 変更ファイル

| ファイル | 内容 |
| --- | --- |
| app/services/warehouse_settings.py | 対応・基準不足の参照、区分・対応変更、完了検証、候補一覧、割当更新 |
| app/routes/warehouse_settings.py | SH06〜08・AL01/02の入力とHTTP境界 |
| app/__init__.py、app/routes/demand_groups.py | Blueprint登録と対象404・405応答 |
| app/routes/shelters.py、app/services/shelters.py | 状態更新経路を新しい整合性検証へ接続 |
| app/routes/pages.py、app/templates/warehouse_settings.html | 設定画面の入口とJinja2画面 |
| app/static/js/warehouse-settings.js | API接続・全対応先編集・確認・割当・ページ送り・失敗時入力保持 |
| app/static/js/shelters.js、app/templates/shelters_form.html、app/static/js/shelters-form.js | 一覧・編集画面からの導線と設定完了操作の移動 |
| app/static/css/stocks.css | フィールドセット内のフォーム配置 |
| tests/test_warehouse_settings.py | 実SQLiteのAPI・業務・原子性検証68件 |
| tests/warehouse-settings-ui.test.cjs | 画面スクリプトの動作検証2件 |

## 受入条件と結果

| 条件 | 自動検証 |
| --- | --- |
| 専用1件・共有0件以上、null区分拒否、全対応先取得と置換 | 成功 |
| 旧・新対応先を設定中へ、区分だけの変更、無変更の再送、名称変更 | 成功 |
| 数量0を含む有効在庫で変更拒否、削除済み在庫だけなら変更可 | 成功 |
| 無効在庫への割当が残る破損データの変更拒否、修復せずDB不変 | 成功 |
| 有効・共有・対応先を検証、0解除にも同じ条件、未割当0再送 | 成功 |
| 全避難所合計が現在庫以下、置換・解除、小数0.1＋0.2、整数／2桁・REAL精度 | 成功 |
| 割当候補の期限切れ・未確認・終了品目・ページング、専用／無効在庫の除外 | 成功 |
| 不整合時の完了拒否、基準不足警告、対応0件・割当0で完了可能 | 成功 |
| 入出庫・論理削除が、今回設定した割当を使って拒否すること | 成功 |
| 未登録参照・不正JSON・重複キー・未知キー・重複クエリー・404/405/415 | 成功 |
| 対応・割当の新規／更新／解除・状態更新の途中失敗と遅延FKによるCOMMIT失敗 | 成功。全テーブルが操作前と一致 |
| 独立接続ロックで503 STORAGE_BUSY・retryable true・DB不変 | 成功 |
| 空状態・基準未登録表示・拒否／通信失敗時入力保持・保存後再取得・全対応先送信 | DOM代替による動作検証で成功 |

全参照は既存接続を使う読取BEGIN、更新は検証と関連更新を同一BEGIN IMMEDIATE内で実行する。
合計・上限比較は十進演算を使用し、割当の自動調整を行わない。外部キー有効化とforeign_key_checkを確認した。
検証には承認DDLから作成した一時DBを使用した。

プロジェクトルートで以下を実行し、pytestは328件成功、失敗・エラー・スキップ0件。
Nodeは新規2件と既存入出庫2件の計4件成功。変更したJavaScriptの構文確認とgit diff --checkも成功した。
実行環境はPython 3.15.2、SQLite 3.53.4、pytest 9.2.0。

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node tests/warehouse-settings-ui.test.cjs
node tests/stocks-movements-ui.test.cjs
node --check app/static/js/warehouse-settings.js
```

## 実ブラウザ検証待ち

Microsoft Edgeでの確認を試みたが、ブラウザアクセスホストが利用できず、
Windowsネイティブ操作も「現在のブラウザURLを十分な確信で判定できない」としてComputer Useに停止された。
正常表示・空状態・重要拒否・通信失敗の実ブラウザ操作確認は未実行。
Jinja2とDOM代替での検証結果を記録し、ブラウザのレイアウト・入力制約・クリック確認は確認待ちとする。
人間による独立したレビューも受入前に必要。
