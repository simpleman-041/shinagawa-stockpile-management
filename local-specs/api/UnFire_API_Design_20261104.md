# UnFire 平常時備蓄管理支援システム API設計書

作成日：2026年11月4日（JST）  
版：1.0  
成果物区分：添付3資料に基づく実装用API契約案。完成アプリの実装・受入試験・教員適合の完了を表すものではない。

2026-11-13採用記録：依頼者の明示回答により、基本3マスター（WH01〜04・IT01〜05・SH01〜05）と日常基準（TH01/02）に本書§2の共通契約を正式採用した。ID・小数の文字列、厳密JSON、エラー、HTTPコード、必須・省略・nullを含む。DBのPK/FK型は変更しない。TH01も共通一覧契約のlimit/offsetとpageを返す。倉庫詳細に日常基準の登録・更新UIを配置し、解除は今回対象外とすることも同回答で承認された。他の未確定事項や実ブラウザ受入の完了は表さない。

本書は、6人の実装担当者が同じエンドポイント、JSON、入力検証、計算式、業務トランザクションを用いるための契約である。確定判断89件と19テーブルの設計を維持し、画面だけでなくAPIで禁止操作を拒否する。計算実行、正式目標更新、結果保存を分け、保存結果は計算時点の主要根拠とともに不変とする。

主要箇所：[共通契約](#common-contract) · [入力型](#input-types) · [API一覧](#api-list) · [業務トランザクション](#transactions) · [計算仕様](#calculation-rules) · [保存仕様](#saved-results) · [19表155列](#database-fields) · [未確定事項](#open-issues) · [89件対応表](#traceability)

## 1. 設計根拠と確定区分

### 1.1 参照資料の同一性

参照チャット「API設計書の確認」（6aea5151-2564-83e8-b545-fabe5feb01fe）に添付された実ファイルを取得し、本文・表・DDLを照合した。作業フォルダにある似たファイル名から添付版の同一性を推定していない。以下のハッシュは今回読み込んだ添付実体のSHA-256である。

| 記号 | 添付ファイル | 版と参照箇所 | SHA-256 |
|---|---|---|---|
| R | 要件定義書.md | 版2.0、本編§1〜15、付録A〜D、89件の回答記録 | `7dfc666ac610b742a8f546f6a56abc29a4cc0f8cb353b96369e1cd1d449b3dcc` |
| D | UnFire_DB_Design_20261101(2).docx | 2026年11月1日版、§5〜11・14〜15、付録A | `67bc2aee1b44a574843755ec66e31f357d0388e060ee2a1dc81fe95924ad3606` |
| S | UnFire_SQLite_Schema_20261101(1).sql | 20261101、新規DB専用DDL全体 | `f7ae51da54d710414639429d120a62bbb13cf8f42131fce7d6ad40b7c5c55698` |

### 1.2 優先順位と設計判断

業務判断はRの最終回答と後続P・U、物理構造・操作契約の具体化はD、実際の列・制約・トリガーはSを照合して用いる。R付録の旧仕様で最新本編を取り消さない。Dが明示した後続の追加確定条件は維持する。DとSが業務要件と衝突する場合にDDLだけを理由に業務を変更してはならない。

| 区分 | 本書での意味 | 主な内容 |
|---|---|---|
| 確定業務要件 | Rの89件およびDに明記された後続確定条件 | 専用全量／共有明示割当、統合前取消禁止、終了品目復元禁止、不変の手動保存 |
| 既存の技術具体化 | Dで具体化済み、APIでも維持 | 同じ保管場所のみ統合、統合世代、期間警告両端包含、計算版、凍結オブジェクト、GIS静的ファイル |
| 本APIの技術具体化 | 業務の意味を変えない通信・サービス設計 | URL、メソッド、IDと小数のJSON表現、ページング、エラーコード、トークン、再送処理 |
| 暫定適用 | 資料が暫定とする範囲 | 日常管理基準比較では期限未確認を除外 |
| 未確定・外部確認 | 本書で採用値・承認完了を捏造しない | 実基準値、GIS実データ、教員の木構造指摘、実業務との一致。§12参照 |

Rの異保管場所統合に関する留保は、D§8 TX03・§14の「今回禁止と確定」によって解消している。本書では未確定へ戻さない。Q04は最終C、Q32は最終A、Q02はA・Bの複数回答を維持する。

### 1.3 対象と対象外

対象は倉庫・品目・在庫、入出庫・条件付き取消、期限・論理削除復元・統合、避難所対応・共有割当、日常管理基準・容量、需要グループと換算、当日備蓄計算・手動保存・履歴、参考GISである。初期需要は食料・飲料水・携帯トイレ。担当者は事前登録一覧の選択だけを提供する。

ロット番号、品目保存期間、品目単体の基本備蓄量、任意処理日、認証・権限管理、承認ワークフロー、担当者管理、倉庫削除・無効化、統合取消、登録終了品目復帰、保存結果の更新・削除・無効化、専用2件比較、全倉庫合計・地域別在庫集計、人口からの目標人数推定、自動割当調整、発災後予測・配送・自動通知・オフライン同期は提供しない。APIの未掲載操作を汎用CRUDで補完してはならない。

<a id="common-contract"></a>

## 2. 共通通信契約

### 2.1 URLとJSON

APIの基点は `/api/v1`。§4のパスにはこの接頭辞を付ける。静的GISファイルは§9の独立パスで配信する。APIの要求・応答はUTF-8の `application/json`、GETは本文なし。日時を要求から任意指定する経路はない。未知のパスは404、既知パスへの未提供メソッドは405とし、許可メソッドを `Allow` に示す。

JSONオブジェクトの重複キー、不正JSON、配列やスカラーを本文のルートにした要求は400。未知の本文フィールド・未知のクエリー・同じクエリーの重複は422。読み取り専用値の投稿も422とし無視しない。クライアントはキー順に依存せず、列名と同じsnake_caseを使用する。POST/PATCH/PUTの許可フィールドは§4の集合だけである。

### 2.2 基本型とNULL

| 型 | JSON表現・入力契約 | DBとの変換 |
|---|---|---|
| ID | 正の10進整数文字列。例 `"12"`。先頭0・符号なし。SQLite signed 64-bitの正範囲内 | INTEGERへ損失なく変換。全ての `*_id` に適用 |
| I | JSON整数。日数・人数・世代・件数等。小数、文字列、bool不可 | INTEGER。通信で安全に表せる整数（絶対値≦9007199254740991）を検証。これは技術表現限界であり業務上限の追加ではない。演算結果が超える場合も丸めずエラー |
| B | JSON boolean | DBの0/1に変換。NULL可フラグだけnullを許す |
| Dec | 10進文字列。例 `"1.23"`。符号・指数・空白・カンマ・NaN・Infinity不可 | 数量等は十進検証後にREALへ。係数だけ100倍INTEGERへ |
| Text | JSON文字列。必須値はSQLiteのtrim後に空でないことを最低条件とする | 入力を勝手に正規化・切詰めしない。任意テキストは未入力をnullへ明示変換し空白だけの値を拒否 |
| Date | 実在するグレゴリオ暦の `YYYY-MM-DD` | TEXT。書式CHECKだけに任せない |
| Instant | UTCの `YYYY-MM-DDTHH:mm:ss.SSSZ`、24文字 | サーバー生成TEXT。検索境界もこの形式 |
| Coordinate | 有限JSON数値。緯度−90〜90、経度−180〜180 | REAL。数量の2桁制約は座標に適用しない。緯度経度は両方null又は両方数値 |

IDを文字列にする理由はブラウザーの大きなINTEGERの丸めを防ぐため。ID文字列に数量としての意味はない。`factor_x100` はINTEGERの正範囲を損失なく扱う10進整数文字列として出力する。係数の入力には `factor`（Dec、正値2桁）を用い、`factor_x100` の投稿は認めない。

Dec入力の構文は `^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$`。分割不可の数量・割当・日常基準・当該単位の使用量は小数部分が0の整数値に限定する。`"1"` と `"1.00"` はどちらも整数1として受理し、`"1.5"` は拒否する。容量・容積は2桁まで。数量・容量・容積・日常基準は非負、入出庫量・使用量・係数は正。割当の0は解除でありDBへ0行を残さない。桁超過を丸めて受理しない。REALへの保存と最短往復十進文字列への復帰で入力の十進値を再現できない極端値や、係数100倍の64-bit超過を422とする。推定した業務最大値を追加しない。

応答Decは指数なし・小数第2位までの十進文字列。計算量・容量率は2桁、充足率は1桁、係数factorは2桁で表示し、例 `"100.00"` / `"75.0"` / `"1.00"`。座標は数値。丸めを許すのは計算・表示で指定した箇所だけ。`null` と `"0.00"` と `[]` は同義ではない。

POSTでは必須フィールドを省略不可。任意の未設定フィールドを省略した場合だけ本書のnull又はDDLの初期状態へ設定する。応答では定義したフィールドを省略せずnullを明示する。PATCHは省略＝維持、null＝NULLへの明示変更（NULL可列のみ）、空オブジェクトは422。PUTは§4の必須集合を全て置換し、省略を暗黙削除にしない。日時・ID・履歴名写し・世代はサーバー生成で、担当者名を要求から受け取らない。

### 2.3 成功応答と一覧

単一応答は `{"data": <定義したDTO>}`、一覧は `{"data": [<DTO>], "page": {"limit": 50, "offset": 0, "total": 0}}`。リソースを新規作成したPOSTは201と `Location`、更新・取消・試算・プレビューは200。§4に別記する場合を除き空成功や204は使わない。

一覧GETの共通任意クエリーは `limit`（Iの10進表記、1〜200、既定50）、`offset`（0以上、既定0）。totalは全フィルター適用後・ページ分割前の件数。空一覧は200と `data:[]`。並びは通常主キー昇順、履歴・保存計算は日時降順＋ID降順、複合キーは定義列順の昇順。任意sortの追加はしない。新規POSTのLocationはWH02ならWH03、IT02ならIT03、SH02ならSH03、ST02ならST03、MV02ならMV04、DG02ならDG03、CR01ならCR03のURLを指す。

一覧のcountと行は同じ読取トランザクションで取得する。ページ間の変更を固定する機能は追加しない。

qは任意の非空文字列を名称・住所等にリテラル部分一致で検索する。SQLはパラメーター化し、LIKEの `%` と `_` は利用者文字としてエスケープする。複数条件はAND、qの対象複数列はOR。既定値・検索対象は各APIで固定する。日時検索は `from` を含み `to` を含まない半開区間、両方指定時はfrom＜to。検索対象は登録日時又は計算日時であり保存日時へすり替えない。

### 2.4 エラー応答

```json
{
  "error": {
    "code": "ALLOCATION_EXCEEDS_STOCK",
    "message": "更新後の数量が割当合計を下回ります。",
    "fields": [{"path": "/quantity", "code": "BELOW_ALLOCATED_TOTAL", "message": "先に割当を減らすか、出庫数量を減らしてください。"}],
    "details": {"stock_id": "1", "result_quantity": "7.00", "allocated_total": "8.00"},
    "retryable": false
  }
}
```

全失敗でこの形を用い、fieldsは0件なら `[]`、detailsは0件なら `{}`。fields.pathは本文のJSON Pointer、クエリーは `/query/limit`、パスは `/path/stock_id` とする。原因・修正方法を日本語で示す。画面は非成功応答・通信失敗でフォームを初期化しない。SQL文字列・内部スタックを応答へ出さない。計算できない業務データがあることは通常の計算結果200で表し、HTTP失敗と混同しない。

| HTTP | code | 条件と修正方法 |
|---|---|---|
| 400 | INVALID_JSON | 構文・重複キー・本文ルート不正。JSONを修正 |
| 415 | UNSUPPORTED_MEDIA_TYPE | 書込みのContent-Typeはapplication/jsonを指定 |
| 404 | RESOURCE_NOT_FOUND | パスのリソースなし。対象を選び直す。本文中の参照ID不存在は422 REFERENCE_NOT_FOUND |
| 405 | METHOD_NOT_ALLOWED | 存在するリソースの未提供操作。許可操作を使用 |
| 409 | STOCK_NOT_ACTIVE / INVALID_STOCK_STATE | 削除・統合状態等が操作条件外。詳細を再確認 |
| 409 | ITEM_CLOSED / UNIT_HAS_STOCK / CLOSED_ITEM_CANNOT_REOPEN | 終了品目の禁止操作、既存在庫の単位変更。新品目を登録 |
| 409 | ALLOCATION_EXCEEDS_STOCK / NEGATIVE_STOCK | 更新後数量又は割当が不正。割当・数量を修正 |
| 409 | ALLOCATIONS_EXIST / WAREHOUSE_IN_USE | 統合・削除中割当、区分対応変更時の有効在庫（0行含む）又は有効割当。先に許可された調整 |
| 409 | INVALID_WAREHOUSE_LINKS / WAREHOUSE_MODE_UNSET | 専用1件、共有条件、割当先対応が不正。設定画面で修正 |
| 409 | MOVEMENT_ALREADY_CANCELLED / MERGE_GENERATION_MISMATCH | 二重取消又は統合前取引。直接取消しない |
| 409 | STOCK_CANDIDATES_AMBIGUOUS | 通常登録の一致候補が複数。対象在庫を選択するか許可条件を満たす手動統合 |
| 409 | MERGE_CONDITION_MISMATCH / MERGE_EXPIRY_UNCONFIRMED | 元先条件不一致又は未確認期限。条件を確認 |
| 409 | PREVIEW_CHANGED / PREVIEW_UNAVAILABLE | 統合プレビューが変更・喪失。再プレビューが必要 |
| 409 | CALCULATION_TOKEN_UNAVAILABLE / TOKEN_ALREADY_SAVED | 凍結計算を取得できない、又は同一トークンの異なる訂正元で再保存。保持結果・保存履歴を確認 |
| 409 | CALCULATION_GROUPS_EMPTY / TARGET_NOT_SET | 対象需要なし、目標未登録で試算条件省略。条件を設定 |
| 409 | NO_CHANGE | 期限訂正が現値と同じ。変更履歴を追加しない |
| 422 | VALIDATION_ERROR / UNKNOWN_FIELD / READ_ONLY_FIELD / REFERENCE_NOT_FOUND | 必須、型、範囲、精度、日付、未知値、本文参照ID等の修正 |
| 422 | DECIMAL_PRECISION / INTEGER_REQUIRED / NUMBER_NOT_REPRESENTABLE | 入力精度・型・保存表現範囲を修正。黙示丸めなし |
| 422 | INVALID_CORRECTION / INCOMPLETE_CONVERSION_SET | 訂正元の存在・ID順、計算条件の置換集合が不正 |
| 500 | DATA_INTEGRITY_ERROR / SNAPSHOT_INVALID / INTERNAL_ERROR | 既存データ整合不良、凍結物の不正、予期しない障害。成功扱いにせず原因調査 |
| 503 | STORAGE_BUSY / STORAGE_UNAVAILABLE / GIS_DATA_UNAVAILABLE | ロック・I/O・接続・GIS未配置。入力を保持し復旧後に再確認 |

形式エラーを全て409にせず、業務状態競合を全て422にしない。既知のDDL例外は§8の業務エラーへ対応付け、未対応CHECK・FK違反はROLLBACK後500とする。APIによる事前検証漏れを成功に変換しない。retryableはSTORAGE_BUSYだけtrue、他はfalse。trueでもPOSTを自動再送しない。通信断・COMMIT結果不明では履歴を照合してから再操作する。exactly-onceを保証する新規永続採番・要求台帳は追加しない。

## 3. DTOとフィールド定義の読み方

§10はDDLの全19テーブル・155列を、そのまま読取りDTOのフィールド集合として定義する。NULL可否、enum、CHECK、複合キーとFKも併記する。DTO名と表名の対応は次表のとおり。DTOにない汎用attributesや任意JSONを追加しない。

| DTO | 元テーブル | 補足 |
|---|---|---|
| Operator | operators | 事前登録IDと名称 |
| Warehouse | warehouses | 施設種別と計算区分を分離 |
| Shelter | shelters | 正式目標と設定状態 |
| Item | items | 期限接近日数・分割可否・登録状態 |
| Stock | stocks | 統合情報と世代を含む。数量の直接更新不可 |
| ShelterWarehouse | shelter_warehouses | 対応関係の唯一の正本 |
| Allocation | stock_allocations | 保存された正数量行。解除0行は返さない |
| Threshold | stock_thresholds | 行なし＝未設定、値0＝設定済み0 |
| DemandGroup | demand_groups | 未設定の基準列はnull |
| ItemConversion | item_conversions | 全DB列に加えfactor:Dec?＝factor_x100÷100を返す |
| Movement | stock_movements | 登録・取消時の担当者名の写し |
| StateEvent | stock_state_events | 削除・復元の追記記録 |
| ExpiryChange | stock_expiry_changes | 前後期限・職員・日時 |
| Run | calculation_runs | 保存済みヘッダー |
| GroupResult | calculation_group_results | 需要別結果と当時の基準 |
| ItemSnapshot | calculation_item_snapshots | 品目・換算の当時値 |
| WarehouseSnapshot | calculation_warehouse_snapshots | 当時の倉庫区分 |
| WarehouseLinkSnapshot | calculation_warehouse_links | 当時の全対応先集合 |
| StockSnapshot | calculation_stock_snapshots | 主要数量と期限・算入理由 |

末尾 `?` はnull可、`[]` は配列、`{a:T,b:U}` はキー集合を固定したオブジェクト。ID列はID、DB INTEGERフラグはB、それ以外のINTEGERはI（factor_x100を除く）、REALはDec（座標を除く）に変換する。DB型TEXTは列の意味に応じたText／Date／Instant／enumとなる。

<a id="input-types"></a>

### 3.1 書込み入力型

以下は本文ルート又は明示された入れ子で使う型。表で「任意」とした項目だけ省略可。表記のないキーは不可。各 `*_id` パスには対応する実在IDが必要。

| 入力型 | 必須フィールド | 任意フィールドと省略時 |
|---|---|---|
| WarehouseCreate | name:Text, facility_type:Text, address:Text | latitude:Coordinate?=null, longitude:Coordinate?=null, capacity_m3:Dec?=null。allocation_modeは投稿不可・初期null |
| WarehousePatch | 下記許可集合から1項目以上 | name, facility_type, address, latitude, longitude, capacity_m3。区分・対応は専用APIだけ。片座標だけのPATCHも適用後に両値の対を検証 |
| ItemCreate | name:Text, category:Text, quantity_unit:Text, is_divisible:B, near_expiry_days:I | unit_volume_m3:Dec?=null。registration_stateはサーバーがactive |
| ItemPatch | 許可集合から1項目以上 | name, category, quantity_unit, unit_volume_m3, is_divisible, near_expiry_days。registration_stateの直接更新不可 |
| ShelterCreate | name:Text, address:Text | target_people:I?=null, target_days:I?=null。両方null又は両方1以上。setup_stateはediting |
| ShelterPatch | name:Text又はaddress:Textの1つ以上 | 他のキー不可 |
| TargetPut | target_people:I, target_days:I | なし。両方1以上。正式目標を更新する専用操作 |
| WarehouseSettingPut | allocation_mode:dedicated\|shared, shelter_ids:ID[] | なし。倉庫の最終対応先全件。重複不可。null区分への解除機能は設けない |
| SetupPut | setup_state:editing\|complete | なし。完了確認は§5.4に従う |
| AllocationPut | quantity:Dec | なし。0は対象割当行の解除 |
| StockCreate | warehouse_id:ID, item_id:ID, location:Text, initial_quantity:Dec, expiry_state:dated\|none\|unconfirmed, expiry_date:Date? | operator_id:ID（initial_quantity>0では必須）, reason:Text?=null。0登録で入庫履歴なし、reasonはnull又は省略のみ |
| StockPatch | location:Text | なし。数量、倉庫、品目、期限、状態、統合世代は投稿不可 |
| MovementCreate | kind:in\|out, quantity:Dec, operator_id:ID | reason:Text?=null。日時・担当者名・世代は自動 |
| Actor | operator_id:ID | なし |
| ConfirmedActor | operator_id:ID, confirmed:B（trueのみ） | なし。削除・復元の画面確認を表す技術フィールド。承認フローではない |
| ExpiryPut | expiry_state:dated\|none\|unconfirmed, expiry_date:Date?, operator_id:ID | なし。datedは実在日付必須、他はnull必須 |
| MergePreviewRequest | source_stock_id:ID, target_stock_id:ID | なし |
| MergeExecuteRequest | preview_token:Text, operator_id:ID, confirmed:B（trueのみ） | なし。元先や合計数量の再投稿不可 |
| ThresholdPut | minimum_quantity:Dec | なし。品目の管理単位で検証 |
| GroupWrite | name:Text, calculation_unit:Text?, is_divisible:B?, daily_usage:Dec?, source_text:Text?, version_or_date:Text?, conditions:Text? | なし。未設定値も明示nullで送る。需要基準不足の編集中保存を許可 |
| ConversionWrite | factor:Dec?, source_text:Text?, version_or_date:Text?, conditions:Text? | なし。係数と根拠は未確認ならnull。空文字で代替しない |
| GroupConditionsPut | group:GroupWrite, conversions:{item_id:ID, factor:Dec?, source_text:Text?, version_or_date:Text?, conditions:Text?}[] | なし。現在の所属品目を全件含める。新規所属の追加可、欠落は422、他グループからの移動はIC01で明示する |
| ItemConversionPut | group_id:IDおよびConversionWriteの全キー | なし。1品目1需要。既存の対応を置換可。保存済み写しへ遡及しない |
| CalculationRequest | shelter_id:ID | target_people:Iとtarget_days:Iは両方同時に省略可。省略時は登録済み正式目標。指定時は両方1以上。base_dateの投稿不可 |
| SaveRunRequest | calculation_token:Text | correction_of_run_id:ID?=null。クライアント結果・根拠・saved_atは投稿不可 |

履歴を伴うActorの担当者IDは事前一覧の実在を確認する。選択担当者と認証された操作者を同一視しない。Actorを持たない更新へ独自の担当者監査表を追加しない。

## 4. エンドポイント一覧と個別契約

各行の本文型・応答型は§3・§4.2・§10の完全なキー集合を参照する。GET一覧の共通ページングは§2.3に従う。「一覧」以外の集約・詳細・凍結配列は完全な集合を返しページングしない。書込み行は§5・§8の対応TXを必ず同一トランザクションで実行する。

<a id="api-list"></a>

### 4.1 操作一覧

| API ID | メソッドとパス | クエリー又は本文 | 成功時dataとHTTP | DB操作／根拠 |
|---|---|---|---|---|
| OP01 | `GET /operators` | 一覧。追加フィルターなし | Operator[]、200 | operators参照、Q09 Q17 |
| WH01 | `GET /warehouses` | 一覧。q任意（名称OR住所）、coordinates任意:known\|missing | Warehouse[]、200 | warehouses、F01 Q27 |
| WH02 | `POST /warehouses` | WarehouseCreate | Warehouse、201 | warehouses新規、F01 |
| WH03 | `GET /warehouses/{warehouse_id}` | なし | Warehouse、200 | warehouses、F01 |
| WH04 | `PATCH /warehouses/{warehouse_id}` | WarehousePatch | Warehouse、200 | 通常項目だけ更新、F01 Q32 |
| WH05 | `GET /warehouses/{warehouse_id}/summary` | なし | WarehouseSummary、200 | 倉庫単位集計、Q19 Q66 |
| IT01 | `GET /items` | 一覧。q任意（名称）、registration_state任意:active\|closed。省略時両方 | Item[]、200 | items、Q50〜53 |
| IT02 | `POST /items` | ItemCreate | Item、201 | TX10、Q05〜07 Q47 |
| IT03 | `GET /items/{item_id}` | なし | Item、200 | items、Q50 |
| IT04 | `PATCH /items/{item_id}` | ItemPatch | Item、200 | TX10、Q46〜50 |
| IT05 | `POST /items/{item_id}/closure` | 空オブジェクト {} | Item、200 | TX10、active→closedのみ、Q51〜53 |
| SH01 | `GET /shelters` | 一覧。q任意（名称OR住所） | Shelter[]、200 | shelters、Q33 |
| SH02 | `POST /shelters` | ShelterCreate | Shelter、201 | shelters、F09 |
| SH03 | `GET /shelters/{shelter_id}` | なし | Shelter、200 | shelters、Q13 Q33 |
| SH04 | `PATCH /shelters/{shelter_id}` | ShelterPatch | Shelter、200 | 通常名称住所、F09 |
| SH05 | `PUT /shelters/{shelter_id}/targets` | TargetPut | Shelter、200 | 正式目標だけ、Q13 |
| SH06 | `GET /shelters/{shelter_id}/warehouse-settings` | なし | ShelterWarehouseSettings、200 | 対応と状態、Q14 Q16 U07 |
| SH07 | `PUT /shelters/{shelter_id}/warehouse-settings/warehouses/{warehouse_id}` | WarehouseSettingPut | WarehouseSettingResult、200 | TX06、Q68 U01 U02 |
| SH08 | `PUT /shelters/{shelter_id}/warehouse-setup` | SetupPut | Shelter、200 | 設定状態だけ、P02 Q69 |
| AL01 | `GET /shelters/{shelter_id}/allocations` | 一覧。warehouse_id任意 | AllocationCandidate[]、200 | 関連shared倉庫のactive在庫、Q14 Q65 |
| AL02 | `PUT /shelters/{shelter_id}/allocations/{stock_id}` | AllocationPut | AllocationResult、200 | TX05、Q15 Q65 |
| ST01 | `GET /stocks` | 一覧。warehouse_id, item_id任意。state:active\|deleted\|merged（既定active）。expiry_status:valid\|near\|expired\|none\|unconfirmed任意。q任意（品目名OR保管場所） | StockView[]、200 | stocks＋現在品目参照、Q30 Q41 Q45 |
| ST02 | `POST /stocks` | StockCreate | StockRegistrationResult、新IDなら201・既存再利用なら200 | TX01、通常入庫、未確認は別行 |
| ST03 | `GET /stocks/{stock_id}` | なし。状態を問わず参照可能 | StockView、200 | 履歴参照・復元前確認、Q29〜31 |
| ST04 | `PATCH /stocks/{stock_id}` | StockPatch | StockView、200 | activeの保管場所編集だけ、R付録A§6.1 |
| ST05 | `POST /stocks/{stock_id}/logical-deletion` | ConfirmedActor | StockStateResult、200 | TX04、Q30 |
| ST06 | `POST /stocks/{stock_id}/restoration` | ConfirmedActor | StockStateResult、200 | TX04、Q31 P01 |
| ST07 | `PUT /stocks/{stock_id}/expiry` | ExpiryPut | StockExpiryResult、200 | TX07、Q41〜43 |
| ST08 | `POST /stock-merges/preview` | MergePreviewRequest | MergePreview、200 | 読取検証、Q38 |
| ST09 | `POST /stock-merges` | MergeExecuteRequest | MergeResult、200 | TX03、Q28 Q29 Q38〜40 |
| MV04 | `GET /stock-movements/{movement_id}` | なし。取消済み・対象在庫の削除統合後も参照 | Movement、200 | 元履歴の個別参照、Q08 Q10 |
| MV01 | `GET /stock-movements` | 一覧。stock_id, state:active\|cancelled, kind:in\|out, from, to任意。日時はregistered_at | Movement[]、200 | stock_movements、Q08 Q10 |
| MV02 | `POST /stocks/{stock_id}/movements` | MovementCreate | MovementResult、201 | TX01、Q08〜10 Q15 Q52 |
| MV03 | `POST /stock-movements/{movement_id}/cancellation` | Actor | MovementResult、200 | TX02、Q04 Q10 |
| HX01 | `GET /stocks/{stock_id}/state-events` | 一覧。追加フィルターなし | StateEvent[]、200 | stock_state_events、Q31 |
| HX02 | `GET /stocks/{stock_id}/expiry-changes` | 一覧。追加フィルターなし | ExpiryChange[]、200 | stock_expiry_changes、Q43 |
| TH01 | `GET /warehouses/{warehouse_id}/thresholds` | 一覧。設定済み行だけ | Threshold[]、200 | stock_thresholds、Q06 |
| TH02 | `PUT /warehouses/{warehouse_id}/thresholds/{item_id}` | ThresholdPut | Threshold、新規201・更新200 | 倉庫×品目単位、Q06 |
| DG01 | `GET /demand-groups` | 一覧。追加フィルターなし | DemandGroup[]、200 | demand_groups、Q54〜58 |
| DG02 | `POST /demand-groups` | GroupWrite | DemandGroup、201 | TX10、初期需要基準登録、Q55 |
| DG03 | `GET /demand-groups/{group_id}/conditions` | なし | GroupConditions、200 | 需要と全所属換算、Q55 |
| DG04 | `PUT /demand-groups/{group_id}/conditions` | GroupConditionsPut | GroupConditions、200 | TX10、一括条件更新、Q50 Q56 |
| IC01 | `PUT /items/{item_id}/conversion` | ItemConversionPut | ItemConversion、新規201・更新200 | TX10、1品目1需要、Q54 Q73 |
| CA01 | `POST /calculations` | CalculationRequest | CalculationPreview、200。DB保存なし | TX08、Q11〜13 Q58 U06 |
| CA02 | `GET /calculations/{calculation_token}` | なし | CalculationPreview、200。現DB再計算なし | サーバー凍結物参照、Q64 |
| CR01 | `POST /calculation-runs` | SaveRunRequest | SavedCalculation、新規201・同一保存再応答200 | TX09、Q59〜64 U05 |
| CR02 | `GET /calculation-runs` | 一覧。shelter_id, result_state:computed\|partial\|unavailable, from, to任意。日時はcalculated_at | Run[]、200 | calculation_runs履歴、Q60 |
| CR03 | `GET /calculation-runs/{run_id}` | なし | SavedCalculation、200 | 保存6表だけから当時値、Q61〜64 |
| EX01 | `GET /stock-alerts` | なし | StockAlerts、200 | 有効在庫行数、Q45 |
| GIS01 | `GET /gis/warehouses` | なし | GISWarehouses、200 | DB倉庫位置と未確認別一覧、Q23 Q27 |
| GIS02 | `GET /gis/datasets/current` | なし | GISDataset、200 | 検証済み静的版の参照、Q20〜26 |

### 4.2 集約・操作結果DTO

次表のキーを全て返す。ここで宣言した補助値はDBに追加する列ではなく、現在参照又は指定計算からの導出値である。配列内のID順は§2.3に従う。

| DTO | 完全なキー集合と意味 |
|---|---|
| StockView | stock:Stock, item_name:Text, quantity_unit:Text, item_registration_state:active\|closed, allocated_total:Dec, unallocated_quantity:Dec, expiry_status:valid\|near\|expired\|none\|unconfirmed, base_date:Date。品目名等は現在値 |
| StockRegistrationResult | stock:StockView, reused_existing:B, movement:Movement?。新規0行はmovement:null。既存再利用0も数量を変えずmovement:null |
| MovementResult | stock:StockView, movement:Movement。取消でも元movementのstateをcancelledにした同じ記録を返す |
| StockStateResult | stock:StockView, event:StateEvent |
| StockExpiryResult | stock:StockView, change:ExpiryChange |
| ShelterWarehouseSettings | shelter:Shelter, warehouses:Warehouse[], links:ShelterWarehouse[], issues:Issue[]。対象避難所の現在対応倉庫と、その倉庫の全対応先リンクを含む |
| WarehouseSettingResult | warehouse:Warehouse, links:ShelterWarehouse[], affected_shelters:Shelter[]。linksは当該倉庫の更新後全件、affected_sheltersは旧先∪新先 |
| AllocationCandidate | stock:StockView, selected_allocation:Dec。割当行がない在庫も0で返す。期限切れ・未確認も物理在庫の管理として表示 |
| AllocationResult | stock_id:ID, shelter_id:ID, quantity:Dec, allocated_total:Dec, unallocated_quantity:Dec。解除時quantityは0、DB行なし |
| GroupConditions | group:DemandGroup, conversions:ItemConversion[]。所属品目全件、登録終了品目も除外しない |
| Issue | code:Text, message:Text, paths:Text[]。不足・矛盾の対象を特定する。code集合は§6.3 |
| MergePreview | preview_token:Text, source:StockView, target:StockView, after_source_quantity:Dec（0）, after_target_quantity:Dec, after_target_generation:I, cancellation_notice:Text。状態もsource.stock.state=activeからmergedになると案内文へ明記 |
| MergeResult | source:StockView, target:StockView。sourceはmerged、数量0、統合先・日時・担当者IDを保持 |
| WarehouseSummary | warehouse:Warehouse, base_date:Date, capacity:CapacitySummary, items:WarehouseItemSummary[]。itemsは当該倉庫のactive在庫又は設定済み基準に登場する品目の和集合 |
| CapacitySummary | state:computed\|unavailable, used_volume_m3:Dec?, capacity_m3:Dec?, usage_rate:Dec?, level:available\|full\|over\|unknown, issues:Issue[]。率は2桁表示 |
| WarehouseItemSummary | item_id:ID, item_name:Text, quantity_unit:Text, physical_quantity:Dec, allocated_total:Dec, unallocated_quantity:Dec, dated_usable_quantity:Dec, no_expiry_quantity:Dec, expired_quantity:Dec, unconfirmed_quantity:Dec, near_expiry_quantity:Dec, minimum_quantity:Dec?, daily_usable_quantity:Dec, below_minimum:B?。各品目内だけ集計 |
| StockAlerts | base_date:Date, expired_count:I, near_expiry_count:I, unconfirmed_count:I, filters:{expired:{state:active,expiry_status:expired},near:{state:active,expiry_status:near},unconfirmed:{state:active,expiry_status:unconfirmed}}。filtersをST01へそのまま渡せる |
| CalculationPreview | calculation_token:Text, header:CalculationHeader, groups:PreviewGroup[], items:PreviewItem[], warehouses:PreviewWarehouse[], warehouse_links:PreviewWarehouseLink[], stocks:PreviewStock[], issues:Issue[] |
| CalculationHeader | Runの列のうちrun_id、saved_at、correction_of_run_idを除く全13列。計算時点のshelter_name・setup_stateを固定 |
| PreviewGroup | GroupResultからrun_idを除く全列 |
| PreviewItem | ItemSnapshotからrun_idを除く全列 |
| PreviewWarehouse | WarehouseSnapshotからrun_idを除く全列 |
| PreviewWarehouseLink | WarehouseLinkSnapshotからrun_idを除く全列 |
| PreviewStock | StockSnapshotからrun_idを除く全列 |
| SavedCalculation | run:Run, groups:GroupResult[], items:ItemSnapshot[], warehouses:WarehouseSnapshot[], warehouse_links:WarehouseLinkSnapshot[], stocks:StockSnapshot[], correction_run_ids:ID[]。訂正先は自分を訂正元とする保存runのID全件 |
| GISWarehouses | located:Warehouse[], unlocated:Warehouse[], stock_data_kind:sample。locatedは両座標あり、unlocatedは両方null。全倉庫を一度に返す |
| GISDataset | dataset_id:Text, manifest_url:Text, areas_url:Text, population_url:Text, legend:{population_date:Date, unit:people_per_km2, classes:{lower:Dec,upper:Dec,color:Text}[], unknown_color:Text}。静的版に整合する密度凡例 |

StockViewのexpiry_statusはdatedかつ期限＜JST当日ならexpired、0≦残日数≦near_expiry_daysならnear、それ以外のdatedはvalid。ST01のvalidはnearを含めない。noneとunconfirmedは対応状態そのもの。期限判定日は一覧取得開始時に固定し、0数量のactive行も警告「件数」に含める。near_expiry_quantityはdated_usable_quantityの内数であり二重加算しない。

CapacitySummaryは容量NULL・0又はactive在庫の品目容積NULLならstate:unavailable、usage_rate:null、level:unknown。容積欠損があればused_volume_m3:null、容量だけ不明なら計算できたused_volume_m3は返せる。全情報ありならusage_rate＝使用量÷容量×100、大小判定には表示率を使わず、同量full、超過over、未満available。issuesで不足品目ID・容量パスを示す。

WarehouseItemSummaryのdated_usable_quantityは期限内dated、no_expiry_quantityはnone、daily_usable_quantityはその和（unconfirmedを含めない暫定方針）。minimum_quantityがnullならbelow_minimum:null。共有・専用を問わずallocated_totalは実際の割当行合計で、専用の暗黙算入を割当行として捏造しない。unallocated_quantityは物理数量−明示割当合計という物理管理値であり、専用在庫の「供給先が未確定」という意味ではない。

### 4.3 操作別の境界条件

| API | 必須の追加検証と禁止 |
|---|---|
| WH02/04 | facility_typeからallocation_modeを推測しない。名称住所編集ではsetup_stateを戻さない。座標未確認登録可。容量0は登録可・率計算不可 |
| IT02/04/05 | near_expiry_days必須1〜3650、初期値なし。既存在庫は全stateを含め単位変更禁止。分割可否変更は全既存数量・割当・基準を再検証。終了済みclose再送は200で同じItem、復帰不可。名称・日数等の通常編集は終了状態でも可 |
| SH02/05 | 目標人数日数は対で扱う。正式目標更新は計算・保存に副作用なし |
| SH07/08 | 専用1件、共有0件以上、区分変更条件、設定中復帰は§5.4。完了でも計算条件欠損を0にしない |
| AL02 | active、shared、倉庫との対応、入力精度、全割当合計≦現在庫。専用への割当行を作らない。0解除にも同じactive・shared・対応の検証を適用し、正常な未割当0の再送は200で行なしを維持する。対象不存在又は非activeなら拒否 |
| ST02 | active品目だけ。dated/noneの同倉庫・品目・場所・期限状態日付のactive一致行を検索。1件なら再利用、複数なら409 STOCK_CANDIDATES_AMBIGUOUSと候補IDを返して対象選択又は手動統合を案内。未確認期限は毎回別行。数量0だけの新規登録可 |
| ST04 | activeのみ。保管場所変更で他行と同条件になっても自動統合しない。倉庫間移動を同じ在庫のwarehouse_id書換えで実現しない |
| ST05/06 | 削除はactiveかつ割当行0、復元はdeletedかつ品目active。復元先は現在の倉庫区分・対応。mergedは不可、数量・過去記録は変更しない。現在の帰属が未設定でも推測補完しない |
| ST07 | active、実在日付、状態日付の対応。変化なしは409 NO_CHANGE。終了品目の有効在庫でも期限訂正可。訂正で同条件行ができても自動統合しない |
| ST08/09 | 異なるID、双方active、同倉庫・同品目・同単位・同場所・同期限状態日付、unconfirmed不可、元先双方割当行0。統合時点にも再検証。詳細は§5.2 |
| MV02/03 | 数量正、active在庫、出庫・取消後は0以上かつ割当合計以上。終了品目の入庫だけ拒否、出庫と条件を満たす取消は許可。取消は元世代一致必須 |
| TH02 | 当該品目単位の整数／2桁。倉庫×品目の行を新設又は更新。0は有効な基準。品目登録本文へ混在させない |
| DG02/04/IC01 | 基準未完はnullで登録可。不明の係数を1へ補完しない。需要単位変更時は所属全品目を再確認、未確認係数はnull。計算条件画面の簡易確認ダイアログを必須とするが承認APIは追加しない |
| CA01/CR01 | 条件不足は理由付き部分結果として計算・保存可。空の需要集合は保存トリガーと整合せず409。任意基準日拒否。保存時に現DBの計算条件を再取得しない |
| HX01/02/MV01 | 削除・統合後も元stock_idの履歴を参照。履歴を統合先IDへ付替えない。個別参照MV04も同様。過去取引への倉庫区分表示を追加する場合は「現在の区分」と明記し、当時値と表示しない |

APIに削除・復元の理由必須、承認者、棚卸し専用モード、異品目への振替等を追加しない。誤統合の個別訂正は既存の許可された入出庫・在庫登録等で行い、元履歴消去・統合先追跡取消・統合元の再有効化にしない。

<a id="transactions"></a>

## 5. 業務トランザクション契約

### 5.1 共通原則と入出庫

全接続でトランザクション開始前に `PRAGMA foreign_keys=ON` と `PRAGMA recursive_triggers=ON` を設定し、foreign_keysの値1を確認する。書込みは `BEGIN IMMEDIATE`、同じ接続で現在行取得→入力・業務検証→関連更新→最終検証→COMMIT。途中の例外・キャンセル・遅延FK失敗では全体ROLLBACKし成功を返さない。RAISE(ABORT)は文だけを中止するため、以前の更新をCOMMITしてはならない。読取集約と計算はBEGINで一貫した時点を読む。

| TX | API | 同時に行う処理 | 終了時の不変条件 |
|---|---|---|---|
| TX01 | ST02 / MV02 | active品目・在庫・単位を確認。新規在庫はquantity=0から作成。正の初期量又は入出庫量は数量更新とMovement追記を一括実行。担当者名と世代を固定 | quantity≧0、quantity≧割当合計。数量0登録に架空の0入庫履歴を追加しない |
| TX02 | MV03 | active取引・active在庫・世代一致を検証。in取消は減算、out取消は加算。元取引をcancelledにし取消担当者名IDと時刻を追記 | 数量非負・割当以上、元取引の本体は不変、取消は1回 |
| TX03 | ST09 | プレビューと条件を再確認。先数量に元を加算し先世代+1。元はquantity=0、state=merged、統合先・担当者・日時を記録 | 元先の数量合計保存、元先履歴ID不変、統合元以後更新不可 |
| TX04 | ST05 / ST06 | stateのみ変更し、StateEventを追記 | 数量・期限不変、復元はactive品目のみ、過去計算不変 |
| TX05 | AL02 | 対応・shared・activeを検証。対象割当を追加又は更新、0ならDELETE | 全割当合計≦現在庫、未割当は差分、自動調整なし |
| TX06 | SH07 | 旧対応先集合を取得。区分と当該倉庫の全対応先を置換。旧先∪新先をeditingへ更新 | dedicatedは最終1件、sharedは0以上。有効在庫・割当なし |
| TX07 | ST07 | 現在期限を取得し差分検証。在庫期限更新とExpiryChange追記 | 前後値・職員・日時を記録。履歴なしの期限変更不可 |
| TX08 | CA01 | 読取BEGINで条件・数量・基準・帰属を収集し、基準日と計算日時を固定。十進計算とサーバー凍結 | DBにrunを作成しない。保存までDBトランザクションを開かない |
| TX09 | CR01 | 凍結結果の完全性と訂正元を検証。計算6表へ子先・親最後の順でINSERT | 全件保存又は0件、過去runを変更しない |
| TX10 | IT02/04/05、DG02/04、IC01 | 品目・需要条件・換算の関連検証と更新。需要単位変更時は全所属係数を再確認 | 在庫単位不変、終了復帰なし、写しへ遡及なし |

WH02/04・SH02/04/05・SH08・TH02・ST04も同じ書込み基本契約を使用する。ST04は場所だけの更新であり、在庫数量の補正を兼ねない。履歴のない汎用SQL更新APIは設けない。

ST02の既存再利用はDB UNIQUEへ任せない。期限訂正等で同じ条件の行が複数存在し得るため、検索と増加処理を同じBEGIN IMMEDIATE内で行う。候補複数の場合は数量を変更せず候補IDを返す。利用者が既存在庫を選択した後はMV02で明示入庫する。

### 5.2 統合プレビューと確定

ST08は読取トランザクションで元先のStockView、数量、識別条件、世代、割当行なしを確認し、サーバー内の不変プレビューを `preview_token` へ関連付ける。プレビューはDB更新しない。UIは元先、統合後の元merged・数量0、先合計と新世代、統合取消なし・元先の統合前取引を直接取消不可という制限を表示し、確認後ST09を呼ぶ。

ST09ではBEGIN IMMEDIATE内で同条件を再検証し、プレビューが参照した元先の値（ID、識別条件、数量、state、世代、品目の単位・登録状態、割当有無）が変わっていれば409 PREVIEW_CHANGEDとしてROLLBACKする。名称等、表示した解釈に必要な情報が変わっても再表示する。プレビュー済みだから検証を省略してはならない。

統合先の世代は受入れのたび1増やす。統合元の既存取引は在庫stateで、統合先の旧取引は世代不一致で取消拒否する。統合後に先へ登録した取引は新世代を保持し、通常条件を満たせば取消可。同一ミリ秒の取引でも日時の大小だけで判定しない。統合先が後で別の統合元となる場合も、過去リンクを付替えない。

preview_tokenは推測困難な不透明値（128bit以上の乱数）、サーバーの当該プロセス内で保持する。再起動・喪失時は再プレビューを案内する。保存前変更検出をしないQ64の対象は計算であり、統合確定時の再検証を禁止するものではない。統合確定トークンの二重実行は数量を再加算しない。成功を記憶している同一トークン再送は同じ元先IDの現在StockViewを200で返し、再実行しない。

### 5.3 削除・復元・取消

ST05/06の画面は直前のST03で数量・期限・統合状態を表示し、復元では現在の倉庫区分・全対応先をSH06等で確認する。confirmed:trueはこの確認を表す。元画面値でDBを上書きせず、書込時に現在状態と禁止条件を再検証する。削除・復元の履歴はStateEventに追記し、既存記録を変更しない。

MV03の取消対象はパスの元取引そのもの。新たな逆取引として履歴を二重登録せず、元の登録情報を残して取消情報だけ追記する。正しい取引の再登録はMV02の別操作。削除済み・統合元は取消不可。終了品目でも出庫取消による数量増加は「新規入庫」と区別して許可条件を検証する。

### 5.4 倉庫対応変更と設定完了

SH07は避難所を起点とする画面から、1倉庫のallocation_modeと全shelter_idsを一括更新する。倉庫側に別の専用避難所IDを作らない。更新対象倉庫にquantity=0を含むactive在庫行が1つでもあるか、有効な正数量割当があれば409 WAREHOUSE_IN_USE。無効行だけなら変更可能で、過去取引・保存写しは変更しない。整合性を破る無効行への割当が直接DB編集等で残る場合は500 DATA_INTEGRITY_ERRORとして調査対象とし、勝手に消去しない。

dedicatedは最終対応先ちょうど1件、sharedは0以上。新規倉庫はallocation_mode:nullで登録できるが、設定画面ではdedicated又はsharedを選択し、nullをdedicatedと推測しない。変更がなければ更新もeditingへの復帰も行わない。区分だけ変えた場合も旧先∪新先をeditingにする。名称・住所・容量等の通常編集には再確認を適用しない。

SH08でcompleteにする前に、現在の対応倉庫と区分・専用件数・割当整合を検証し、未登録数量や基準不足を画面へ表示する。基準が未完でも倉庫対応の設定完了と計算可能は別概念であり、全基準の完成を完了操作の新しい条件にしない。矛盾する対応は409 INVALID_WAREHOUSE_LINKS。completeかつ対応0件は確認済み対象在庫0、editingかつ0件は未確定。共有の割当0は正常0。完了時にも暗黙の倉庫・数量行・割当を生成しない。

<a id="calculation-rules"></a>

## 6. 備蓄計算と判定

### 6.1 対象取得と主要写し

CA01はDBのdemand_groups全行を対象需要集合とする技術具体化とし、名称からの選択や任意の要求側group_idsを導入しない。初期は食料・飲料水・携帯トイレの需要条件を実値確認後に登録する。需要0件は409 CALCULATION_GROUPS_EMPTYであり、空結果を保存しない。各品目はitem_conversionsの明示対応1件に従い同需要へ集約する。対応名の類似や現在の品目名から自動推定しない。追加の需要グループを登録すると計算対象に加わるため、条件管理画面でその影響を案内する。

基準日base_dateは読取開始時のJST当日、calculated_atはその時点のUTC。日付境界をまたいでもこの1回の計算内では固定する。要求にbase_dateがあれば未知又は読取専用フィールドとして422。登録済み目標の省略利用か、両方明示した一時試算を選び、正式目標は変更しない。

| データ | 対象集合と保持する範囲 |
|---|---|
| groups | 対象需要全件。需要名・単位・分割可否・使用量・出典・版・条件と結果 |
| items | 対象需要に明示対応する全品目。登録終了品目も含む。在庫0件の品目も写しを残す |
| warehouses | 対象避難所に対応する全倉庫。在庫0件でも保持。区分nullも欠損状態として保持 |
| warehouse_links | 上記各倉庫の当時の全対応先集合。他避難所名も当時値で保持し専用件数を再現 |
| stocks | 対象倉庫・対象品目のactive在庫。期限切れ・未確認・共有未割当・数量0も対象選定理由とともに保持。deleted/mergedは写し対象外 |

在庫写しにはstock_quantity、全避難所割当合計allocated_total、対象避難所割当selected_allocationを保持する。保管場所・住所・容量・他避難所別割当明細を複製せず、完全な在庫バックアップへ拡張しない。関係表の不整合、基準不足は理由付き結果で表す。数量負数・割当合計超過などSの写しCHECKを満たさない既存DB破損は500 DATA_INTEGRITY_ERRORとし、値を切詰めて保存可能に偽装しない。

### 6.2 期限と算入

| selection_reason | 条件 | 在庫写しincluded_quantity |
|---|---|---|
| unresolved | 倉庫区分・対応の矛盾等で当該在庫の帰属が確認できない | 0。確認可能な別在庫は参考量へ保持 |
| expired | 帰属が確認でき、datedかつexpiry_date＜base_date | 0 |
| unallocated | 帰属が確認できるsharedでselected_allocation=0 | 0 |
| dedicated | 正常な専用1避難所・期限内又はnone/unconfirmed | stock_quantity全量 |
| shared | 正常な共有対応・期限内又はnone/unconfirmed・選択割当あり | selected_allocation |

理由の優先順は上表順。dedicatedのselected_allocationとallocated_totalは通常0であり、暗黙全量を割当行へ変換しない。全量算入を倉庫の対応件数や施設種別から推定しない。

unknown_expiry_warningはunconfirmedかつ実際の暫定算入数量>0のときtrue。需要とヘッダーのhas_unknown_expiryは当該算入警告のOR。期限未確認だけでresult_stateをpartialにせず、他条件が揃えばcomputedと警告を両立する。期限不要は警告なし。

expires_in_periodはdatedでbase_date≦expiry_date≦base_date＋target_days−1日ならtrue。対象数量の算入可否とは別の期限事実を示し、注意の表示は算入数量がある在庫について行う。期限当日は有効、翌日から除外。期間中の消費・期限到来・補給による再配分・時系列予測は行わない。

### 6.3 情報不足と状態の決定

Issue.codeは `SETUP_EDITING`、`WAREHOUSE_MODE_MISSING`、`DEDICATED_LINK_COUNT_INVALID`、`ALLOCATION_LINK_INVALID`、`ITEM_CONVERSION_MISSING`、`CONVERSION_FACTOR_MISSING`、`CONVERSION_SOURCE_MISSING`、`GROUP_UNIT_MISSING`、`GROUP_DIVISIBILITY_MISSING`、`DAILY_USAGE_MISSING`、`USAGE_SOURCE_MISSING`、`STOCK_UNREGISTERED`、`ROUNDED_DENOMINATOR_ZERO`、`CAPACITY_MISSING`、`CAPACITY_ZERO`、`UNIT_VOLUME_MISSING`、`GIS_POPULATION_MISSING`、`GIS_AREA_MISSING` を使用する。sourceには出典・版または日付・条件の不足を含みpathsで該当列を区別する。新たな不足分類が必要なら契約を改版し、実装者独自のenumを無断追加しない。

計算不能理由はAPIではIssue配列で提示し、保存のunavailable_reason列にはコードと対象・日本語理由をコード順・対象ID順の決定的順序で連結した非空テキストを保存する。利用者は理由を読める必要がある。保存列を未定義のJSON列へ変更しない。保存閲覧はこの当時テキストを表示し、現在の欠損を検索して理由を作り直さない。

| 状態 | 結果の扱い |
|---|---|
| 設定editing | 全対象需要の正式指標は不可。確認済み換算数量はreference_quantity。総合人数日数null |
| completeで正常対応0件 | 数量A=0として計算可。ただし需要・単位・使用量・明示品目対応等の基準が揃う必要あり |
| shared対応あり・割当なし | 正常A=0。未割当を自動算入しない |
| dedicatedの当該需要にactive在庫が1行もない | STOCK_UNREGISTERED。欠落を確認済み0としない。確認済み0は対応品目の数量0有効行で表すというDの具体化を維持 |
| 期限切れ行だけ存在 | 登録済みで使用可能A=0として扱う |
| 一部倉庫の帰属不整合 | 影響需要の正式指標は不可、確認できた別倉庫分は参考量。影響しない需要は計算可 |
| 使用量・単位・分割可否・出典・版・条件・所属品目係数根拠の不足 | 該当需要をunavailable。根拠の揃う所属品目だけで正式率を出さない |

品目未対応は名前から補わない。需要に所属品目が0件ならITEM_CONVERSION_MISSING。初期対象需要への対応がない品目を別の需要と二重要求せず、条件管理で対応登録を案内する。

GroupResultがcomputedならunavailable_reason:null、required_quantity、included_quantity、covered_quantity、shortage_quantity、coverage_rate、people、daysは全て非null。unavailableならこれら8値は全てnull、理由必須。reference_quantityは換算が確認できた数量（確認済み0なら0、1つも確定できなければnull）を独立に保持する。

全需要computedならヘッダーresult_state:computed、総合人数・日数はそれぞれ最小、同率を含む全制約需要のlimits_people/limits_daysをtrueにする。一部だけcomputedならpartial、全需要不可ならunavailable。後二者はmin_people/min_days:null、ヘッダー不可理由必須、全需要の制約フラグfalse。SのCHECKに合わせる。部分不可や全不可でも空需要でなければ保存できる。

### 6.4 精度と計算順

計算版はDと同じ `unfire-20261101-r1`。REAL読出しを最短の往復可能十進文字列へ戻し、十進演算を行う。Q2は小数第2位ROUND_HALF_UP、Q1は第1位ROUND_HALF_UP。言語既定の偶数丸めを無条件に使わない。

1. 各在庫のconverted_quantity＝Q2(included_quantity×factor_x100÷100)。係数未確認ならnull。
2. stock_id数値昇順にQ2で合算し需要別Aとする。文字列IDの辞書順で並べない。
3. R＝Q2(N×D×u)。共通計算単位が分割不可ならRを整数へ切上げる。
4. 充足量C＝min(A,R)、不足量S＝Q2(max(R−A,0))。
5. 充足率coverage_rate＝Q1(A÷R×100)。100%超を保持し表示する。充足判断はA・R・不足量で行い表示率を使わない。
6. 人数people＝floor(A÷Q2(D×u))、日数days＝floor(A÷Q2(N×u))。最終商を先にQ2へ丸めない。丸め後分母0は計算不可。
7. 整数単位の必要調達量表示はceil(S)、分割可ならS。GroupResult.shortage_quantityから表示時に導出し、品目別の購入・配分を自動決定しない。
8. 総合人数・日数と制約需要は§6.3で決定する。異なる需要単位の数量を足さない。

数量・必要量・換算量はDBの対応REAL列へ保存する。入力時の桁超過拒否と、演算途中での指定丸めを混同しない。整数結果・日付加算・十進演算の技術表現範囲を超える要求は422 NUMBER_NOT_REPRESENTABLE、既存データによる計算不能は理由を提示する。微小不足0.004→0.00を特別補正・検出しない既知制限を維持する。容量率の表示はQ2、満杯超過の判定は丸め前の使用容量と容量の比較で行う。

<a id="saved-results"></a>

## 7. 計算凍結と保存履歴

### 7.1 計算トークン

CA01は表示データと同時に、主要根拠全件・算術結果・当時計算条件をサーバー内の不変オブジェクトとして保持し、推測困難なcalculation_token（128bit以上の乱数）を返す。ブラウザーが返送した結果値やスナップショットJSONは保存入力として受理しない。CA02はその保持物を返し、現DBを再計算しない。画面の主要結果常時表示・根拠展開は同じ応答内のheader/groupsと各写し配列で実現する。

本APIの技術選択は単一サーバープロセスのメモリー保持。勝手な時間切れTTLは設けず、プロセス再起動・保持物喪失時は409 CALCULATION_TOKEN_UNAVAILABLE、未保存であることを画面に示し再計算を案内する。未保存結果の再起動耐性・端末間共有・永続ドラフト機能は追加しない。保存済み履歴はSQLiteに残る。運用時はこの保持方式を全実装で統一する。

### 7.2 保存手順

CR01は保存ボタンの明示操作でのみ呼ぶ。保存前の在庫・条件変更検出、最新値での再計算強制、当日から日付が変わったことによる古い凍結結果の保存拒否は行わない。保存前に変更があっても、元のbase_date・calculated_at・目標・名称・条件・帰属・数量をそのまま保存し、saved_atだけ保存時点のUTCで付ける。

1. サーバーの凍結物が存在し、必要な需要・品目・倉庫・対応・在庫の集合、重複、親子参照、状態、丸め、結果式、警告の完全性を検証する。現在マスターから名称・数量・基準を引き直さない。
2. BEGIN IMMEDIATE内でrun_id＝COALESCE(MAX(run_id),0)+1を確保する。ID上限超過は成功にしない。
3. 任意のcorrection_of_run_idは保存済みの既存IDであり新run_idより小さいことを確認する。自己・将来参照・循環を作らない。同一避難所限定という業務条件を追加しない。
4. calculation_group_results → calculation_item_snapshots → calculation_warehouse_snapshots → calculation_warehouse_links → calculation_stock_snapshotsの順に、新run_idを付けて子行をINSERTする。
5. 最後にcalculation_runsヘッダーをINSERTし、saved_at≧calculated_at、遅延FK、全件数、算術整合を確認してCOMMITする。時計逆行でsaved_at＜calculated_atなら失敗を示し時刻設定を確認し、計算時刻を改ざんしない。
6. REPLACE・UPSERT・更新による修復は行わない。ヘッダー作成後の子追加をSのsealedトリガーが拒否する。途中失敗は全ROLLBACK。

データ変更検出をしないことは、不正な凍結物・不正な訂正元・保存先FK違反を無検証で許可するという意味ではない。現DBへの問い合わせはID参照保護・訂正元存在・採番のためだけに行い、当時の計算内容を再構築しない。

### 7.3 二重押下と再送

同一プロセス内でcalculation_tokenごとの保存処理を直列化し、成功したrun_idと訂正元指定を記憶する。同じtoken・同じ訂正元の再送は既存runを200で返し、新runを増やさない。訂正元だけ変えた再送は409 TOKEN_ALREADY_SAVED。最初の保存成功は201とLocation。同じ結果を別の計算として保存したい場合に、未定義の強制複製フラグを追加しない。

COMMIT失敗が確定した場合はROLLBACKしtokenを未保存のまま保持して修正・再試行可能にする。通信切断等で成功か不明の場合は、無条件自動再送せずCR02で日時・避難所等を照合する。再起動後にtokenとrunの対応が失われる制限は残る。保存済み内容の不変性とは別である。一般の入出庫POSTにこの計算tokenを転用しない。

### 7.4 履歴表示

CR02はcalculated_atで絞り込み、saved_atとの混同を避ける。CR03の結果・名称・基準・倉庫区分・帰属・数量・警告は保存6表から返す。現在マスターの名称で上書きせず、計算式版と当時の理由を表示する。訂正元はrun.correction_of_run_id、訂正先は保存ヘッダーの逆参照correction_run_idsで閲覧可能にする。元結果の無効化・削除という意味を付与しない。期間経過による自動削除も提供しない。

## 8. DB制約とサービス検証の分担

Sを変更せず使用する。DDLは新規DB専用で、旧DBへ直接適用する移行スクリプトではない。本APIのための追加テーブル・列・認証情報・要求台帳は作らない。

| 層 | 保証する内容 | APIの責務 |
|---|---|---|
| PK/FK・NOT NULL | 正ID、複合主キー、参照先存在、全FKのRESTRICT | 全接続で有効化。本文参照IDを先に検証し422。FK失敗で部分保存しない |
| CHECK | 状態enum、数値の型・非負、期限状態と日付、取消情報、結果状態とNULL、写し数量上限等 | 十進文字列・2桁・分割不可・実在日付・意味上の整合はサービスで追加検証 |
| トリガー | 不変履歴、保存6表の更新削除不可、保存後子追加不可、統合元更新不可、終了復帰不可、在庫のある単位変更不可 | 事前に同じ禁止を判定し理解できるエラー。トリガーがあるからAPI検証を省略しない |
| アプリの複数行検証 | 割当合計、専用1件、区分変更条件、世代、終了入庫禁止、統合、式・写し集合 | 同一書込トランザクション内で現在値を読み再検証 |
| UI | 確認、入力保持、主要結果・詳細展開、警告・一覧導線 | APIの禁止判定に代用しない。成功応答後だけ完了表示と関連画面再取得 |

SのFKは32本、明示索引27本。DEFERRABLE INITIALLY DEFERREDの計算子FKにより子先保存を実現する。SQLite暗黙索引を27本に含めない。DDLと契約の全列対応は§10、全89件は§13。

### 8.1 DDL例外コードの対応

| SのRAISEメッセージ | サービス側の解釈・HTTP |
|---|---|
| immutable_record / sealed_calculation | 通常APIに変更経路を設けない。保存中に発生したら500 SNAPSHOT_INVALIDと全ROLLBACK |
| invalid_correction | 422 INVALID_CORRECTION |
| missing_group_results | API事前検証では409 CALCULATION_GROUPS_EMPTY。挿入途中の想定外発生は500 SNAPSHOT_INVALID |
| retain_movement / retain_master_or_stock | 物理削除APIなし。内部で発生したら500 INTERNAL_ERROR |
| movement_cancel_only | 二重取消なら409 MOVEMENT_ALREADY_CANCELLED、登録本体変更なら実装不備として500 |
| merged_stock_frozen | 409 STOCK_NOT_ACTIVE |
| closed_item_cannot_reopen | 409 CLOSED_ITEM_CANNOT_REOPEN |
| unit_has_stock | 409 UNIT_HAS_STOCK |

SQLITE_BUSYは503 STORAGE_BUSY、I/O・接続失敗は503 STORAGE_UNAVAILABLE。ABORT、COMMIT時の遅延FK違反、アプリ検証エラーのどれでも全ROLLBACK。応答を先に成功として送らない。DB直接編集では割当超過等を迂回できる既知制限を維持し、通常操作は全て本サービスを通す。

### 8.2 更新後の画面反映

在庫更新・割当合計・上限比較も、読出しREALの最短往復十進値から十進演算で行い、2進浮動小数の直接比較や任意の許容誤差で負数・割当超過を許さない。容量は数量×単位容積の十進積と合計を丸めず計算し、used_volume_m3とusage_rateの表示だけQ2にする。満杯・超過は表示前の合計と容量で判定する。

入出庫・取消・統合・削除復元・期限変更・場所変更の成功後、画面はST01/ST03、WH05、EX01、関係するAL01を必要に応じて再取得する。倉庫・品目の容量値編集ではWH05、接近日数編集ではEX01と在庫表示を再取得する。区分・対応変更では影響避難所のSH06/SH03を再取得する。保存済みCR03や未保存の凍結計算CA02は再計算・置換しない。新条件の結果が必要なら利用者がCA01を実行する。

## 9. GIS読取契約

GISの人口・区域はD§11で選択した静的ファイル方式。19テーブルに人口表を追加しない。GIS01はDBから全倉庫をlocated/unlocatedへ分けて返し、人口レイヤーの取得失敗や切替で倉庫ピンを消さない。ピン選択はWH03/WH05の横概要パネルへつなぎ、詳細は既存倉庫詳細画面を使用する。供給区域・地域在庫量を新設しない。

| 配信経路 | 形式と必須契約 |
|---|---|
| `GET /api/v1/gis/datasets/current` | 検証済み固定版のGISDataset。未収集・未配置・不整合版なら503 GIS_DATA_UNAVAILABLE。架空人口へ置換しない |
| `GET /gis/{dataset_id}/manifest.json` | application/json。以下のManifest本体、共通dataで包まない |
| `GET /gis/{dataset_id}/areas.geojson` | application/geo+json。FeatureCollection、各Feature.id=area_code、properties={area_name,area_km2}。geometryは町丁目境界のPolygon又はMultiPolygon |
| `GET /gis/{dataset_id}/population.csv` | text/csv;charset=utf-8。ヘッダーarea_code,population,population_date。区域コードは先頭0を保持する文字列 |

Manifestの技術的キー集合は `{dataset_id:Text, version:Text, population_date:Date, boundary_version:Text, area_code_system:Text, sources:{url:Text,usage_terms:Text}[], area_definition:Text, area_unit:"km2", crs:"EPSG:4326", sha256:{areas_geojson:Text,population_csv:Text}}`。Dで指定された意味項目をこのキーで固定する。実URL・出典・日付・区域版・利用条件は採用実データの確認後に設定し、本書で捏造しない。dataset_idはディレクトリ区切りを含まない不透明な版識別子で、要求パスを任意ファイル読取りに使わない。

GeoJSONの座標順は経度・緯度、DBはlatitude/longitude列を区別する。人口は非負整数、面積は正値又は欠損（0は無効）。コード重複・人口欠落・境界版不一致・SHA-256・座標系を差替え前に検証する。区域と人口は同一版のコードで結合し、人口欠損・面積欠損／0は密度不明として別色。人口は実人口で、在庫は架空サンプルと明記し実在庫と表示しない。

人口密度＝同区域人口÷面積km²。Dの技術具体化に従い、検証済み版の最大密度Mで5等幅階級。境界は0,M/5,…,M、最初の4階級は下端を含み上端を含まない、最終階級は両端を含む。全区域の既知密度が0なら0の1階級だけ。未知色は `#BDBDBD`、5階級の色は低密度から `#EFF3FF,#BDD7E7,#6BAED6,#3182BD,#08519C`。これは凡例の技術具体化であり業務判断基準ではない。階級判定は丸め前密度で行い、GISDatasetの境界Decは表示用2桁。境界丸めで同値となる場合も画面の階級判定は未丸め値で一貫させる。画面の判定境界は同じ静的版の人口・面積から未丸め最大密度を計算して導出し、表示用の丸め済みlower/upperを判定へ逆利用しない。凡例には実境界値の表示精度と人口基準日・出典を示す。全て密度不明ならclasses:[]で未知色だけとする。

人口レイヤーON/OFFは画面状態であり書込APIなし。開発担当者が版ファイルを一括差替え、currentを有効版へ切替える。人口・境界の編集・アップロードAPIや外部人口APIへの常時追従機能を設けない。実位置・人口・境界の取得と検証は本書作成では実施していない。

<a id="database-fields"></a>

## 10. 全19テーブルのJSONとDDL対応

以下はSから抽出した全155列。各DTOの読取キーはこの集合。末尾のDB定義は省略したチェックの推測ではなく添付DDLの列宣言そのもの（空白だけ整形）。FK・PK等の表制約も各表直下に記す。要求で更新できる集合は§3.1のほうが狭く、列が存在することは更新APIがあることを意味しない。CHECK内のNULL許容とNOT NULLを併せて参照する。

### 10.1 Operator と operators

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| operator_id | ID | 不可 | 担当者ID | `operator_id INTEGER NOT NULL CHECK (operator_id>0)` |
| name | Text / 定義enum | 不可 | 担当者名 | `name TEXT NOT NULL CHECK (length(trim(name))>0)` |

表制約：

```sql
PRIMARY KEY (operator_id)
```

### 10.2 Warehouse と warehouses

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |
| name | Text / 定義enum | 不可 | 倉庫名 | `name TEXT NOT NULL CHECK (length(trim(name))>0)` |
| facility_type | Text / 定義enum | 不可 | 施設種別 | `facility_type TEXT NOT NULL CHECK (length(trim(facility_type))>0)` |
| address | Text / 定義enum | 不可 | 住所 | `address TEXT NOT NULL CHECK (length(trim(address))>0)` |
| latitude | Coordinate | 可 | 緯度 | `latitude REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90))` |
| longitude | Coordinate | 可 | 経度 | `longitude REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180))` |
| capacity_m3 | Dec | 可 | 保管可能容量m3 | `capacity_m3 REAL CHECK (capacity_m3 IS NULL OR (typeof(capacity_m3) IN ('real','integer') AND capacity_m3>=0 AND capacity_m3<=1.7976931348623157e308))` |
| allocation_mode | Text / 定義enum | 可 | 計算区分 | `allocation_mode TEXT CHECK (allocation_mode IS NULL OR (allocation_mode IN ('dedicated','shared')))` |

表制約：

```sql
PRIMARY KEY (warehouse_id)
CHECK ((latitude IS NULL)=(longitude IS NULL))
```

### 10.3 Shelter と shelters

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| shelter_id | ID | 不可 | 避難所ID | `shelter_id INTEGER NOT NULL CHECK (shelter_id>0)` |
| name | Text / 定義enum | 不可 | 避難所名 | `name TEXT NOT NULL CHECK (length(trim(name))>0)` |
| address | Text / 定義enum | 不可 | 住所 | `address TEXT NOT NULL CHECK (length(trim(address))>0)` |
| target_people | I | 可 | 正式目標人数 | `target_people INTEGER CHECK (target_people IS NULL OR (typeof(target_people)='integer' AND target_people>=1))` |
| target_days | I | 可 | 正式目標日数 | `target_days INTEGER CHECK (target_days IS NULL OR (typeof(target_days)='integer' AND target_days>=1))` |
| setup_state | Text / 定義enum | 不可 | 倉庫設定状態 | `setup_state TEXT NOT NULL DEFAULT 'editing' CHECK (setup_state IN ('editing','complete'))` |

表制約：

```sql
PRIMARY KEY (shelter_id)
CHECK ((target_people IS NULL)=(target_days IS NULL))
```

### 10.4 Item と items

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| item_id | ID | 不可 | 品目ID | `item_id INTEGER NOT NULL CHECK (item_id>0)` |
| name | Text / 定義enum | 不可 | 品目名 | `name TEXT NOT NULL CHECK (length(trim(name))>0)` |
| category | Text / 定義enum | 不可 | 分類 | `category TEXT NOT NULL CHECK (length(trim(category))>0)` |
| quantity_unit | Text / 定義enum | 不可 | 管理単位 | `quantity_unit TEXT NOT NULL CHECK (length(trim(quantity_unit))>0)` |
| unit_volume_m3 | Dec | 可 | 管理単位当たり容積m3 | `unit_volume_m3 REAL CHECK (unit_volume_m3 IS NULL OR (typeof(unit_volume_m3) IN ('real','integer') AND unit_volume_m3>=0 AND unit_volume_m3<=1.7976931348623157e308))` |
| is_divisible | B | 不可 | 数量分割可否 | `is_divisible INTEGER NOT NULL CHECK (is_divisible IN (0,1))` |
| near_expiry_days | I | 不可 | 期限接近日数 | `near_expiry_days INTEGER NOT NULL CHECK (typeof(near_expiry_days)='integer' AND near_expiry_days>=1)` |
| registration_state | Text / 定義enum | 不可 | 登録状態 | `registration_state TEXT NOT NULL DEFAULT 'active' CHECK (registration_state IN ('active','closed'))` |

表制約：

```sql
PRIMARY KEY (item_id)
CHECK (near_expiry_days<=3650)
```

### 10.5 Stock と stocks

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| stock_id | ID | 不可 | 在庫ID | `stock_id INTEGER NOT NULL CHECK (stock_id>0)` |
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |
| item_id | ID | 不可 | 品目ID | `item_id INTEGER NOT NULL CHECK (item_id>0)` |
| location | Text / 定義enum | 不可 | 保管場所 | `location TEXT NOT NULL CHECK (length(trim(location))>0)` |
| quantity | Dec | 不可 | 現在庫数量 | `quantity REAL NOT NULL CHECK (typeof(quantity) IN ('real','integer') AND quantity>=0 AND quantity<=1.7976931348623157e308)` |
| expiry_state | Text / 定義enum | 不可 | 期限状態 | `expiry_state TEXT NOT NULL CHECK (expiry_state IN ('dated','none','unconfirmed'))` |
| expiry_date | Date | 可 | 使用期限。実在日付をアプリ検証 | `expiry_date TEXT CHECK (expiry_date IS NULL OR (length(expiry_date)=10 AND expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'))` |
| state | Text / 定義enum | 不可 | 在庫状態 | `state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','deleted','merged'))` |
| merged_into_stock_id | ID | 可 | 統合先在庫ID | `merged_into_stock_id INTEGER` |
| merged_at | Instant | 可 | 統合日時。UTC固定ミリ秒ISO 8601。システムが生成 | `merged_at TEXT CHECK (merged_at IS NULL OR (length(merged_at)=24 AND merged_at GLOB '????-??-??T??:??:??.???Z'))` |
| merged_by | I | 可 | 統合担当者ID | `merged_by INTEGER` |
| merge_generation | I | 不可 | 統合世代 | `merge_generation INTEGER NOT NULL DEFAULT 0 CHECK (typeof(merge_generation)='integer' AND merge_generation>=0)` |

表制約：

```sql
PRIMARY KEY (stock_id)
CHECK (((expiry_state='dated' AND expiry_date IS NOT NULL) OR (expiry_state IN ('none','unconfirmed') AND expiry_date IS NULL)))
CHECK ((state='merged' AND merged_into_stock_id IS NOT NULL AND merged_at IS NOT NULL AND merged_by IS NOT NULL AND quantity=0) OR (state IN ('active','deleted') AND merged_into_stock_id IS NULL AND merged_at IS NULL AND merged_by IS NULL))
CHECK (merged_into_stock_id IS NULL OR merged_into_stock_id<>stock_id)
FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (merged_into_stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (merged_by) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.6 ShelterWarehouse と shelter_warehouses

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| shelter_id | ID | 不可 | 避難所ID | `shelter_id INTEGER NOT NULL CHECK (shelter_id>0)` |
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |

表制約：

```sql
PRIMARY KEY (shelter_id, warehouse_id)
FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.7 Allocation と stock_allocations

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| stock_id | ID | 不可 | 在庫ID | `stock_id INTEGER NOT NULL CHECK (stock_id>0)` |
| shelter_id | ID | 不可 | 避難所ID | `shelter_id INTEGER NOT NULL CHECK (shelter_id>0)` |
| quantity | Dec | 不可 | 割当数量 | `quantity REAL NOT NULL CHECK (typeof(quantity) IN ('real','integer') AND quantity>0 AND quantity<=1.7976931348623157e308)` |

表制約：

```sql
PRIMARY KEY (stock_id, shelter_id)
FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.8 Threshold と stock_thresholds

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |
| item_id | ID | 不可 | 品目ID | `item_id INTEGER NOT NULL CHECK (item_id>0)` |
| minimum_quantity | Dec | 不可 | 基本備蓄量 | `minimum_quantity REAL NOT NULL CHECK (typeof(minimum_quantity) IN ('real','integer') AND minimum_quantity>=0 AND minimum_quantity<=1.7976931348623157e308)` |

表制約：

```sql
PRIMARY KEY (warehouse_id, item_id)
FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.9 DemandGroup と demand_groups

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| group_id | ID | 不可 | 需要グループID | `group_id INTEGER NOT NULL CHECK (group_id>0)` |
| name | Text / 定義enum | 不可 | 需要グループ名 | `name TEXT NOT NULL CHECK (length(trim(name))>0)` |
| calculation_unit | Text / 定義enum | 可 | 共通計算単位 | `calculation_unit TEXT CHECK (calculation_unit IS NULL OR (length(trim(calculation_unit))>0))` |
| is_divisible | B | 可 | 計算単位分割可否 | `is_divisible INTEGER CHECK (is_divisible IS NULL OR (is_divisible IN (0,1)))` |
| daily_usage | Dec | 可 | 1人1日使用量 | `daily_usage REAL CHECK (daily_usage IS NULL OR (typeof(daily_usage) IN ('real','integer') AND daily_usage>0 AND daily_usage<=1.7976931348623157e308))` |
| source_text | Text / 定義enum | 可 | 使用量出典 | `source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0))` |
| version_or_date | Text / 定義enum | 可 | 使用量の版又は更新日 | `version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0))` |
| conditions | Text / 定義enum | 可 | 使用量適用条件 | `conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0))` |

表制約：

```sql
PRIMARY KEY (group_id)
```

### 10.10 ItemConversion と item_conversions

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| item_id | ID | 不可 | 品目ID | `item_id INTEGER NOT NULL CHECK (item_id>0)` |
| group_id | ID | 不可 | 需要グループID | `group_id INTEGER NOT NULL CHECK (group_id>0)` |
| factor_x100 | 正整数文字列 | 可 | 換算係数100倍 | `factor_x100 INTEGER CHECK (factor_x100 IS NULL OR (typeof(factor_x100)='integer' AND factor_x100>=1))` |
| source_text | Text / 定義enum | 可 | 換算出典 | `source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0))` |
| version_or_date | Text / 定義enum | 可 | 換算の版又は更新日 | `version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0))` |
| conditions | Text / 定義enum | 可 | 換算適用条件 | `conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0))` |
| factor | Dec | 可 | factor_x100÷100、2桁表示 | 導出。DB列ではない |

表制約：

```sql
PRIMARY KEY (item_id)
FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (group_id) REFERENCES demand_groups (group_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.11 Movement と stock_movements

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| movement_id | ID | 不可 | 取引ID | `movement_id INTEGER NOT NULL CHECK (movement_id>0)` |
| stock_id | ID | 不可 | 在庫ID | `stock_id INTEGER NOT NULL CHECK (stock_id>0)` |
| operator_id | ID | 不可 | 登録担当者ID | `operator_id INTEGER NOT NULL CHECK (operator_id>0)` |
| operator_name | Text / 定義enum | 不可 | 登録時担当者名 | `operator_name TEXT NOT NULL CHECK (length(trim(operator_name))>0)` |
| kind | Text / 定義enum | 不可 | 入出庫区分 | `kind TEXT NOT NULL CHECK (kind IN ('in','out'))` |
| quantity | Dec | 不可 | 取引数量 | `quantity REAL NOT NULL CHECK (typeof(quantity) IN ('real','integer') AND quantity>0 AND quantity<=1.7976931348623157e308)` |
| registered_at | Instant | 不可 | 登録日時。UTC固定ミリ秒ISO 8601。システムが生成 | `registered_at TEXT NOT NULL CHECK (length(registered_at)=24 AND registered_at GLOB '????-??-??T??:??:??.???Z')` |
| reason | Text / 定義enum | 可 | 任意理由 | `reason TEXT CHECK (reason IS NULL OR (length(trim(reason))>0))` |
| merge_generation | I | 不可 | 取引時の統合世代 | `merge_generation INTEGER NOT NULL CHECK (typeof(merge_generation)='integer' AND merge_generation>=0)` |
| state | Text / 定義enum | 不可 | 取引状態 | `state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','cancelled'))` |
| cancelled_at | Instant | 可 | 取消日時。UTC固定ミリ秒ISO 8601。システムが生成 | `cancelled_at TEXT CHECK (cancelled_at IS NULL OR (length(cancelled_at)=24 AND cancelled_at GLOB '????-??-??T??:??:??.???Z'))` |
| cancel_operator_id | ID | 可 | 取消担当者ID | `cancel_operator_id INTEGER` |
| cancel_operator_name | Text / 定義enum | 可 | 取消時担当者名 | `cancel_operator_name TEXT CHECK (cancel_operator_name IS NULL OR (length(trim(cancel_operator_name))>0))` |

表制約：

```sql
PRIMARY KEY (movement_id)
CHECK ((state='active' AND cancelled_at IS NULL AND cancel_operator_id IS NULL AND cancel_operator_name IS NULL) OR (state='cancelled' AND cancelled_at IS NOT NULL AND cancel_operator_id IS NOT NULL AND cancel_operator_name IS NOT NULL))
FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (cancel_operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.12 StateEvent と stock_state_events

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| event_id | ID | 不可 | 操作ID | `event_id INTEGER NOT NULL CHECK (event_id>0)` |
| stock_id | ID | 不可 | 在庫ID | `stock_id INTEGER NOT NULL CHECK (stock_id>0)` |
| action | Text / 定義enum | 不可 | 操作 | `action TEXT NOT NULL CHECK (action IN ('delete','restore'))` |
| operator_id | ID | 不可 | 担当者ID | `operator_id INTEGER NOT NULL CHECK (operator_id>0)` |
| occurred_at | Instant | 不可 | 操作日時。UTC固定ミリ秒ISO 8601。システムが生成 | `occurred_at TEXT NOT NULL CHECK (length(occurred_at)=24 AND occurred_at GLOB '????-??-??T??:??:??.???Z')` |

表制約：

```sql
PRIMARY KEY (event_id)
FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.13 ExpiryChange と stock_expiry_changes

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| change_id | ID | 不可 | 変更ID | `change_id INTEGER NOT NULL CHECK (change_id>0)` |
| stock_id | ID | 不可 | 在庫ID | `stock_id INTEGER NOT NULL CHECK (stock_id>0)` |
| before_expiry_state | Text / 定義enum | 不可 | 変更前期限状態 | `before_expiry_state TEXT NOT NULL CHECK (before_expiry_state IN ('dated','none','unconfirmed'))` |
| before_expiry_date | Date | 可 | 変更前使用期限。実在日付をアプリ検証 | `before_expiry_date TEXT CHECK (before_expiry_date IS NULL OR (length(before_expiry_date)=10 AND before_expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'))` |
| after_expiry_state | Text / 定義enum | 不可 | 変更後期限状態 | `after_expiry_state TEXT NOT NULL CHECK (after_expiry_state IN ('dated','none','unconfirmed'))` |
| after_expiry_date | Date | 可 | 変更後使用期限。実在日付をアプリ検証 | `after_expiry_date TEXT CHECK (after_expiry_date IS NULL OR (length(after_expiry_date)=10 AND after_expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'))` |
| operator_id | ID | 不可 | 担当者ID | `operator_id INTEGER NOT NULL CHECK (operator_id>0)` |
| changed_at | Instant | 不可 | 変更日時。UTC固定ミリ秒ISO 8601。システムが生成 | `changed_at TEXT NOT NULL CHECK (length(changed_at)=24 AND changed_at GLOB '????-??-??T??:??:??.???Z')` |

表制約：

```sql
PRIMARY KEY (change_id)
CHECK (((before_expiry_state='dated' AND before_expiry_date IS NOT NULL) OR (before_expiry_state IN ('none','unconfirmed') AND before_expiry_date IS NULL)))
CHECK (((after_expiry_state='dated' AND after_expiry_date IS NOT NULL) OR (after_expiry_state IN ('none','unconfirmed') AND after_expiry_date IS NULL)))
CHECK (before_expiry_state<>after_expiry_state OR before_expiry_date IS NOT after_expiry_date)
FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.14 Run と calculation_runs

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| run_id | ID | 不可 | 計算ID | `run_id INTEGER NOT NULL CHECK (run_id>0)` |
| shelter_id | ID | 不可 | 対象避難所ID | `shelter_id INTEGER NOT NULL CHECK (shelter_id>0)` |
| shelter_name | Text / 定義enum | 不可 | 計算時避難所名 | `shelter_name TEXT NOT NULL CHECK (length(trim(shelter_name))>0)` |
| target_people | I | 不可 | 試算人数 | `target_people INTEGER NOT NULL CHECK (typeof(target_people)='integer' AND target_people>=1)` |
| target_days | I | 不可 | 試算日数 | `target_days INTEGER NOT NULL CHECK (typeof(target_days)='integer' AND target_days>=1)` |
| base_date | Date | 不可 | 計算基準日JST。実在日付をアプリ検証 | `base_date TEXT NOT NULL CHECK (length(base_date)=10 AND base_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')` |
| calculated_at | Instant | 不可 | 計算日時。UTC固定ミリ秒ISO 8601。システムが生成 | `calculated_at TEXT NOT NULL CHECK (length(calculated_at)=24 AND calculated_at GLOB '????-??-??T??:??:??.???Z')` |
| saved_at | Instant | 不可 | 保存日時。UTC固定ミリ秒ISO 8601。システムが生成 | `saved_at TEXT NOT NULL CHECK (length(saved_at)=24 AND saved_at GLOB '????-??-??T??:??:??.???Z')` |
| formula_version | Text / 定義enum | 不可 | 計算仕様版 | `formula_version TEXT NOT NULL CHECK (length(trim(formula_version))>0)` |
| setup_state | Text / 定義enum | 不可 | 計算時設定状態 | `setup_state TEXT NOT NULL CHECK (setup_state IN ('editing','complete'))` |
| result_state | Text / 定義enum | 不可 | 総合計算状態 | `result_state TEXT NOT NULL CHECK (result_state IN ('computed','partial','unavailable'))` |
| has_unknown_expiry | B | 不可 | 期限未確認警告 | `has_unknown_expiry INTEGER NOT NULL CHECK (has_unknown_expiry IN (0,1))` |
| min_people | I | 可 | 総合人数 | `min_people INTEGER CHECK (min_people IS NULL OR (typeof(min_people)='integer' AND min_people>=0))` |
| min_days | I | 可 | 総合日数 | `min_days INTEGER CHECK (min_days IS NULL OR (typeof(min_days)='integer' AND min_days>=0))` |
| unavailable_reason | Text / 定義enum | 可 | 総合計算不可理由 | `unavailable_reason TEXT CHECK (unavailable_reason IS NULL OR (length(trim(unavailable_reason))>0))` |
| correction_of_run_id | ID | 可 | 訂正元計算ID | `correction_of_run_id INTEGER` |

表制約：

```sql
PRIMARY KEY (run_id)
CHECK ((result_state='computed' AND min_people IS NOT NULL AND min_days IS NOT NULL AND unavailable_reason IS NULL) OR (result_state IN ('partial','unavailable') AND min_people IS NULL AND min_days IS NULL AND unavailable_reason IS NOT NULL))
CHECK (correction_of_run_id IS NULL OR correction_of_run_id<run_id)
CHECK (saved_at>=calculated_at)
FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT
FOREIGN KEY (correction_of_run_id) REFERENCES calculation_runs (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.15 GroupResult と calculation_group_results

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| run_id | ID | 不可 | 計算ID | `run_id INTEGER NOT NULL CHECK (run_id>0)` |
| group_id | ID | 不可 | 需要グループID | `group_id INTEGER NOT NULL CHECK (group_id>0)` |
| group_name | Text / 定義enum | 不可 | 計算時需要名 | `group_name TEXT NOT NULL CHECK (length(trim(group_name))>0)` |
| calculation_unit | Text / 定義enum | 可 | 計算時共通単位 | `calculation_unit TEXT CHECK (calculation_unit IS NULL OR (length(trim(calculation_unit))>0))` |
| is_divisible | B | 可 | 計算時分割可否 | `is_divisible INTEGER CHECK (is_divisible IS NULL OR (is_divisible IN (0,1)))` |
| daily_usage | Dec | 可 | 計算時使用量 | `daily_usage REAL CHECK (daily_usage IS NULL OR (typeof(daily_usage) IN ('real','integer') AND daily_usage>0 AND daily_usage<=1.7976931348623157e308))` |
| source_text | Text / 定義enum | 可 | 計算時使用量出典 | `source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0))` |
| version_or_date | Text / 定義enum | 可 | 計算時版又は更新日 | `version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0))` |
| conditions | Text / 定義enum | 可 | 計算時適用条件 | `conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0))` |
| result_state | Text / 定義enum | 不可 | 需要別計算状態 | `result_state TEXT NOT NULL CHECK (result_state IN ('computed','unavailable'))` |
| unavailable_reason | Text / 定義enum | 可 | 需要別計算不可理由 | `unavailable_reason TEXT CHECK (unavailable_reason IS NULL OR (length(trim(unavailable_reason))>0))` |
| reference_quantity | Dec | 可 | 確認済み参考算入量 | `reference_quantity REAL CHECK (reference_quantity IS NULL OR (typeof(reference_quantity) IN ('real','integer') AND reference_quantity>=0 AND reference_quantity<=1.7976931348623157e308))` |
| required_quantity | Dec | 可 | 必要量 | `required_quantity REAL CHECK (required_quantity IS NULL OR (typeof(required_quantity) IN ('real','integer') AND required_quantity>=0 AND required_quantity<=1.7976931348623157e308))` |
| included_quantity | Dec | 可 | 正式算入数量 | `included_quantity REAL CHECK (included_quantity IS NULL OR (typeof(included_quantity) IN ('real','integer') AND included_quantity>=0 AND included_quantity<=1.7976931348623157e308))` |
| covered_quantity | Dec | 可 | 充足量 | `covered_quantity REAL CHECK (covered_quantity IS NULL OR (typeof(covered_quantity) IN ('real','integer') AND covered_quantity>=0 AND covered_quantity<=1.7976931348623157e308))` |
| shortage_quantity | Dec | 可 | 不足量 | `shortage_quantity REAL CHECK (shortage_quantity IS NULL OR (typeof(shortage_quantity) IN ('real','integer') AND shortage_quantity>=0 AND shortage_quantity<=1.7976931348623157e308))` |
| coverage_rate | Dec | 可 | 表示用充足率パーセント | `coverage_rate REAL CHECK (coverage_rate IS NULL OR (typeof(coverage_rate) IN ('real','integer') AND coverage_rate>=0 AND coverage_rate<=1.7976931348623157e308))` |
| people | I | 可 | 支えられる人数 | `people INTEGER CHECK (people IS NULL OR (typeof(people)='integer' AND people>=0))` |
| days | I | 可 | 支えられる日数 | `days INTEGER CHECK (days IS NULL OR (typeof(days)='integer' AND days>=0))` |
| has_unknown_expiry | B | 不可 | 期限未確認警告 | `has_unknown_expiry INTEGER NOT NULL CHECK (has_unknown_expiry IN (0,1))` |
| limits_people | B | 不可 | 人数制約需要 | `limits_people INTEGER NOT NULL CHECK (limits_people IN (0,1))` |
| limits_days | B | 不可 | 日数制約需要 | `limits_days INTEGER NOT NULL CHECK (limits_days IN (0,1))` |

表制約：

```sql
PRIMARY KEY (run_id, group_id)
CHECK ((result_state='computed' AND unavailable_reason IS NULL AND required_quantity IS NOT NULL AND included_quantity IS NOT NULL AND covered_quantity IS NOT NULL AND shortage_quantity IS NOT NULL AND coverage_rate IS NOT NULL AND people IS NOT NULL AND days IS NOT NULL) OR (result_state='unavailable' AND unavailable_reason IS NOT NULL AND required_quantity IS NULL AND included_quantity IS NULL AND covered_quantity IS NULL AND shortage_quantity IS NULL AND coverage_rate IS NULL AND people IS NULL AND days IS NULL))
FOREIGN KEY (run_id) REFERENCES calculation_runs (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
FOREIGN KEY (group_id) REFERENCES demand_groups (group_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.16 ItemSnapshot と calculation_item_snapshots

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| run_id | ID | 不可 | 計算ID | `run_id INTEGER NOT NULL CHECK (run_id>0)` |
| item_id | ID | 不可 | 品目ID | `item_id INTEGER NOT NULL CHECK (item_id>0)` |
| group_id | ID | 不可 | 需要グループID | `group_id INTEGER NOT NULL CHECK (group_id>0)` |
| item_name | Text / 定義enum | 不可 | 計算時品目名 | `item_name TEXT NOT NULL CHECK (length(trim(item_name))>0)` |
| quantity_unit | Text / 定義enum | 不可 | 計算時管理単位 | `quantity_unit TEXT NOT NULL CHECK (length(trim(quantity_unit))>0)` |
| is_divisible | B | 不可 | 計算時数量分割可否 | `is_divisible INTEGER NOT NULL CHECK (is_divisible IN (0,1))` |
| registration_state | Text / 定義enum | 不可 | 計算時登録状態 | `registration_state TEXT NOT NULL CHECK (registration_state IN ('active','closed'))` |
| factor_x100 | 正整数文字列 | 可 | 計算時換算係数100倍 | `factor_x100 INTEGER CHECK (factor_x100 IS NULL OR (typeof(factor_x100)='integer' AND factor_x100>=1))` |
| source_text | Text / 定義enum | 可 | 計算時換算出典 | `source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0))` |
| version_or_date | Text / 定義enum | 可 | 計算時換算版 | `version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0))` |
| conditions | Text / 定義enum | 可 | 計算時換算適用条件 | `conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0))` |

表制約：

```sql
PRIMARY KEY (run_id, item_id)
FOREIGN KEY (run_id, group_id) REFERENCES calculation_group_results (run_id, group_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.17 WarehouseSnapshot と calculation_warehouse_snapshots

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| run_id | ID | 不可 | 計算ID | `run_id INTEGER NOT NULL CHECK (run_id>0)` |
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |
| warehouse_name | Text / 定義enum | 不可 | 計算時倉庫名 | `warehouse_name TEXT NOT NULL CHECK (length(trim(warehouse_name))>0)` |
| allocation_mode | Text / 定義enum | 可 | 計算時区分 | `allocation_mode TEXT CHECK (allocation_mode IS NULL OR (allocation_mode IN ('dedicated','shared')))` |

表制約：

```sql
PRIMARY KEY (run_id, warehouse_id)
FOREIGN KEY (run_id) REFERENCES calculation_runs (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.18 WarehouseLinkSnapshot と calculation_warehouse_links

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| run_id | ID | 不可 | 計算ID | `run_id INTEGER NOT NULL CHECK (run_id>0)` |
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |
| shelter_id | ID | 不可 | 対応避難所ID | `shelter_id INTEGER NOT NULL CHECK (shelter_id>0)` |
| shelter_name | Text / 定義enum | 不可 | 計算時対応避難所名 | `shelter_name TEXT NOT NULL CHECK (length(trim(shelter_name))>0)` |

表制約：

```sql
PRIMARY KEY (run_id, warehouse_id, shelter_id)
FOREIGN KEY (run_id, warehouse_id) REFERENCES calculation_warehouse_snapshots (run_id, warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

### 10.19 StockSnapshot と calculation_stock_snapshots

| JSONキー | JSON型 | null | 意味 | DDL列定義 |
|---|---|---|---|---|
| run_id | ID | 不可 | 計算ID | `run_id INTEGER NOT NULL CHECK (run_id>0)` |
| stock_id | ID | 不可 | 在庫ID | `stock_id INTEGER NOT NULL CHECK (stock_id>0)` |
| item_id | ID | 不可 | 品目ID | `item_id INTEGER NOT NULL CHECK (item_id>0)` |
| warehouse_id | ID | 不可 | 倉庫ID | `warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0)` |
| stock_quantity | Dec | 不可 | 計算時現物数量 | `stock_quantity REAL NOT NULL CHECK (typeof(stock_quantity) IN ('real','integer') AND stock_quantity>=0 AND stock_quantity<=1.7976931348623157e308)` |
| allocated_total | Dec | 不可 | 計算時全避難所割当合計 | `allocated_total REAL NOT NULL CHECK (typeof(allocated_total) IN ('real','integer') AND allocated_total>=0 AND allocated_total<=1.7976931348623157e308)` |
| selected_allocation | Dec | 不可 | 計算時対象避難所割当 | `selected_allocation REAL NOT NULL CHECK (typeof(selected_allocation) IN ('real','integer') AND selected_allocation>=0 AND selected_allocation<=1.7976931348623157e308)` |
| expiry_state | Text / 定義enum | 不可 | 計算時期限状態 | `expiry_state TEXT NOT NULL CHECK (expiry_state IN ('dated','none','unconfirmed'))` |
| expiry_date | Date | 可 | 計算時使用期限。実在日付をアプリ検証 | `expiry_date TEXT CHECK (expiry_date IS NULL OR (length(expiry_date)=10 AND expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'))` |
| included_quantity | Dec | 不可 | 管理単位算入数量 | `included_quantity REAL NOT NULL CHECK (typeof(included_quantity) IN ('real','integer') AND included_quantity>=0 AND included_quantity<=1.7976931348623157e308)` |
| converted_quantity | Dec | 可 | 共通単位換算後数量 | `converted_quantity REAL CHECK (converted_quantity IS NULL OR (typeof(converted_quantity) IN ('real','integer') AND converted_quantity>=0 AND converted_quantity<=1.7976931348623157e308))` |
| selection_reason | Text / 定義enum | 不可 | 選定理由 | `selection_reason TEXT NOT NULL CHECK (selection_reason IN ('dedicated','shared','unallocated','expired','unresolved'))` |
| unknown_expiry_warning | B | 不可 | 期限未確認警告 | `unknown_expiry_warning INTEGER NOT NULL CHECK (unknown_expiry_warning IN (0,1))` |
| expires_in_period | B | 不可 | 目標期間内期限到来警告 | `expires_in_period INTEGER NOT NULL CHECK (expires_in_period IN (0,1))` |

表制約：

```sql
PRIMARY KEY (run_id, stock_id)
CHECK (((expiry_state='dated' AND expiry_date IS NOT NULL) OR (expiry_state IN ('none','unconfirmed') AND expiry_date IS NULL)))
CHECK (allocated_total<=stock_quantity)
CHECK (selected_allocation<=allocated_total)
CHECK (included_quantity<=stock_quantity)
CHECK (selection_reason NOT IN ('unallocated','expired','unresolved') OR included_quantity=0)
FOREIGN KEY (run_id, item_id) REFERENCES calculation_item_snapshots (run_id, item_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
FOREIGN KEY (run_id, warehouse_id) REFERENCES calculation_warehouse_snapshots (run_id, warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
```

## 11. JSON利用例と検証条件

### 11.1 代表リクエスト

下記ID・数量・日付はテスト用であり、運用初期値ではない。

ST02 在庫登録（初期量が正なら入庫履歴も同時保存）：

```json
{"warehouse_id":"1","item_id":"1","location":"棚A","initial_quantity":"600.00","expiry_state":"none","expiry_date":null,"operator_id":"1","reason":"試験用登録"}
```

AL02 共有割当の解除（数量0を保存するのではなく行を削除）：

```json
{"quantity":"0"}
```

IC01 品目換算条件：

```json
{"group_id":"1","factor":"1.00","source_text":"テスト用仮定","version_or_date":"test-v1","conditions":"単体試験専用"}
```

CA01 一時試算（正式目標更新・結果保存は発生しない）：

```json
{"shelter_id":"1","target_people":100,"target_days":2}
```

CR01 手動保存（未保存トークン・訂正元なし）：

```json
{"calculation_token":"test-only-opaque-token-do-not-use","correction_of_run_id":null}
```

### 11.2 保存成功の完全なJSON例

以下は契約確認用の需要1件・在庫1件の最小フィクスチャ。実際の初期3需要を水だけへ変更する指示ではない。使用量3LもR記載の試験仮定であり採用実基準ではない。保存6表の全キーを含む。

```json
{
  "data": {
    "run": {
      "run_id": "1",
      "shelter_id": "1",
      "shelter_name": "試験避難所",
      "target_people": 100,
      "target_days": 2,
      "base_date": "2026-11-04",
      "calculated_at": "2026-11-04T00:00:00.000Z",
      "saved_at": "2026-11-04T00:01:00.000Z",
      "formula_version": "unfire-20261101-r1",
      "setup_state": "complete",
      "result_state": "computed",
      "has_unknown_expiry": false,
      "min_people": 100,
      "min_days": 2,
      "unavailable_reason": null,
      "correction_of_run_id": null
    },
    "groups": [
      {
        "run_id": "1",
        "group_id": "1",
        "group_name": "試験飲料水",
        "calculation_unit": "L",
        "is_divisible": true,
        "daily_usage": "3.00",
        "source_text": "テスト用仮定",
        "version_or_date": "test-v1",
        "conditions": "単体試験専用",
        "result_state": "computed",
        "unavailable_reason": null,
        "reference_quantity": "600.00",
        "required_quantity": "600.00",
        "included_quantity": "600.00",
        "covered_quantity": "600.00",
        "shortage_quantity": "0.00",
        "coverage_rate": "100.0",
        "people": 100,
        "days": 2,
        "has_unknown_expiry": false,
        "limits_people": true,
        "limits_days": true
      }
    ],
    "items": [
      {
        "run_id": "1",
        "item_id": "1",
        "group_id": "1",
        "item_name": "試験水",
        "quantity_unit": "L",
        "is_divisible": true,
        "registration_state": "active",
        "factor_x100": "100",
        "source_text": "テスト用仮定",
        "version_or_date": "test-v1",
        "conditions": "単体試験専用"
      }
    ],
    "warehouses": [
      {
        "run_id": "1",
        "warehouse_id": "1",
        "warehouse_name": "試験倉庫",
        "allocation_mode": "dedicated"
      }
    ],
    "warehouse_links": [
      {
        "run_id": "1",
        "warehouse_id": "1",
        "shelter_id": "1",
        "shelter_name": "試験避難所"
      }
    ],
    "stocks": [
      {
        "run_id": "1",
        "stock_id": "1",
        "item_id": "1",
        "warehouse_id": "1",
        "stock_quantity": "600.00",
        "allocated_total": "0.00",
        "selected_allocation": "0.00",
        "expiry_state": "none",
        "expiry_date": null,
        "included_quantity": "600.00",
        "converted_quantity": "600.00",
        "selection_reason": "dedicated",
        "unknown_expiry_warning": false,
        "expires_in_period": false
      }
    ],
    "correction_run_ids": []
  }
}
```

### 11.3 実装後に行うAPI受入検証

以下は合格済み一覧ではなく、実装担当者が同じ期待値で実行する検証仕様。各失敗で関連全行の更新前後を比較し、数量だけの変更・履歴だけの保存がないことを確認する。RのV01〜V12に対応する。

| 検証ID | 操作・境界 | 期待結果 | Rの検証 |
|---|---|---|---|
| T01 | 禁止フィールド（ロット、保存期間、任意日時、品目基本備蓄量、直接数量）と禁止メソッドを投稿 | 422又は405。未定義機能が作られない。Q04最終C・Q32最終A・Q02 A/Bを保持 | V01 |
| T02 | 担当者一覧、架空担当者、日時投稿、入出庫理由任意 | 事前登録選択だけ、架空ID422、日時422、担当者名と登録時刻は自動写し | V01 V02 |
| T03 | 在庫10・全割当8で出庫3／2、入庫取消後数量7 | 3拒否409、2許可、取消後7拒否。元履歴保持、全ROLLBACK | V02 |
| T04 | 通常登録の同条件1候補／複数候補／期限未確認／初期0 | 再利用／選択案内409／別行／0行のみ。0入庫履歴なし | V02 V03 |
| T05 | 統合元先の倉庫・品目・場所・期限不一致、未確認、割当あり、自己統合 | 全拒否、変化なし。同場所条件はDの後続確定 | V03 |
| T06 | プレビュー後に数量変化、合格統合、同一ミリ秒取引、先への再統合 | 変更は再プレビュー。F22保持・先世代増分、旧取引取消拒否、新世代取引は条件付き可 | V02 V03 |
| T07 | 削除・復元、割当中削除、merged復元、終了品目復元 | 条件付きのみ許可、数量・期限不変、StateEvent追記、履歴と保存結果保持 | V04 |
| T08 | 既存在庫（deleted/merged含む）の単位変更、品目終了後の入庫・出庫・取消・復帰 | 単位変更・入庫・復帰拒否。出庫・有効取消・既存在庫計算を維持 | V04 |
| T09 | 共有1在庫を複数避難所へ割当、0解除、合計超過、未割当 | 合計範囲のみ許可、0は行削除、未割当自動算入なし | V02 V05 |
| T10 | dedicatedの0/1/2対応、quantity0のactive行、無効行だけの区分変更、名称編集 | 専用1件のみ。active0行でも変更拒否。条件を満たす無効行だけなら可、旧新先editing、名称編集では状態維持 | V05 |
| T11 | editing・completeで対応0、共有割当0、専用在庫未登録／0行／期限切れのみ | 未確定と正常0を区別。専用未登録は不可、0行と期限切れのみは基準が揃えばA0 | V05 V07 |
| T12 | JST期限当日・翌日・未確認・none、期間の初日と最終日、期限訂正同値 | 当日有効、翌日除外、未確認暫定警告、期間両端注意、同値履歴拒否、前後履歴正確 | V06 |
| T13 | 接近日数未入力・0・1・3650・3651、警告件数とST01絞込 | 未入力/0/3651拒否、1/3650可、既定値なし、履歴なし、行数件数が対象一覧と一致 | V06 |
| T14 | 容積欠損・容量null/0・使用量同値／超過・期限切れ現物・異単位 | 不足理由と率null、同値full、超過over、期限切れも容量に含む。異単位総和なし、日常比較の未確認除外 | V06 |
| T15 | N100,D2,u3,A600/300/450/900の4試算 | 必要600。不足0/300/150/0、率100/50/75/150%、日数2/1/1/3、人数100/50/75/150 | V07 |
| T16 | 明示旧新換算、類似名称の未対応品目、需要基準不足、一部不可、暫定警告 | 明示分だけ同需要へ、必要量は需要1回。該当不可・総合null、未知期限だけならcomputed＋警告可 | V07 |
| T17 | 分割不可1.5、分割可1.23/1.234、factor1.25/1.234、十進中間値1.245/1.244、微小0.004 | 不可／可／拒否、125保存／拒否、1.25/1.24、0.00への消失を許容。表示率で充足判定しない | V08 |
| T18 | 過去未来のbase_date投稿、目標片側だけ、JST日付越え、最終人数日数が整数境界直前 | 日付指定・片側拒否、開始日固定、最終商は丸めずfloor | V08 |
| T19 | CA01後に在庫・基準・名称・帰属変更、日付越え、CR01保存 | 計算時点一式のまま、calculated_atとsaved_at分離。現在値との混在・変更検出強制なし | V09 |
| T20 | 一部／全部不可保存、空需要保存、訂正元不存在・自己・将来、異避難所の既存訂正元 | 不可結果は理由付き保存、空需要拒否。不正訂正元拒否、異避難所だけを理由に拒否しない | V09 |
| T21 | 保存後UPDATE/DELETE/子追加、二重保存、token喪失、保存途中の強制例外 | 不変防御・同token同訂正元の重複なし・喪失明示・全ROLLBACK、入力保持 | V02 V09 V11 |
| T22 | 保存履歴の避難所・計算日時・状態絞込、訂正逆参照、現在マスター変更 | 半開日時条件、当時名と根拠維持、訂正関係閲覧、専用比較・無効化なし | V09 |
| T23 | 倉庫／避難所検索、SQLの%/_と引用符、NULL座標、人口レイヤー切替 | パラメーター検索、文字として検索、未確認別一覧、倉庫ピン維持 | V10 |
| T24 | GISコード先頭0・版不一致・重複・人口欠損・面積0・全0・未配備 | 検証不合格版を配信しない、欠損は未知色、全0凡例1階級、人口取得失敗でも倉庫表示可。全倉庫地域在庫集計なし | V10 |
| T25 | FK有効化、遅延FK、ABORT、SQLITE_BUSY・I/O・通信断、DB直接編集迂回 | 全接続FK1、失敗全取消、原因修正方法と入力保持。完成アプリにDBだけで全業務保証と表示しない | V11 |
| T26 | 倉庫品目登録→在庫入庫→対応割当→期限容量→試算→保存→履歴→訂正 | 各成功と各エラーで画面連動・入力保持、主要結果常時・詳細展開、架空在庫明示 | V12 |

<a id="open-issues"></a>

## 12. 未確定事項と技術具体化の管理

### 12.1 今回の資料だけで確定しない内容

| ID | 種別 | 未確定内容 | 実装時の扱い |
|---|---|---|---|
| UQ01 | 設定実値 | 使用量、換算、容積、容量、日常基準、期限接近日数と出典・版・条件 | 仮定の初期値を投入しない。null・未設定・計算不可を保持。near_expiry_daysは新規登録時必須 |
| UQ02 | データ取得 | 実倉庫位置、町丁目人口・境界、基準日、面積、利用条件 | 収集・出典・コード・版・座標を確認して静的版を作る。未配備を503とし実データ取得済みとしない |
| UQ03 | 外部条件 | 教員の木構造指摘対象、自己参照・多対多の許否、SQLite・正式提出物条件 | Q70の物理ER／説明図分離を維持。必要FKを勝手に削除せず外部確認 |
| UQ04 | 正本・承認 | 修正版実装計画の正式最新版との同一性、正式提出・発表条件 | 添付3資料照合は実施。未提示の計画や教員承認まで確認済みにしない |
| UQ05 | 業務実態 | 区の専用共有運用、更新責任、保管場所の公開範囲、実在庫 | 内部試作モデルと事実を区別し、ヒアリング・根拠確認 |
| UQ06 | 暫定境界 | 日常基準比較における期限未確認除外 | 現在は除外。備蓄計算の警告付き暫定算入へ自動的に合わせない。変更時は要件変更として記録 |

異場所統合禁止、入力2桁、当日限定、統合取消なし、REAL近似、微小不足の丸め消失、保存前変更検出なしは既知の決定であり未確定ではない。

### 12.2 今回固定したAPI技術判断

URL・メソッド・DTO集合、ID/Decの文字列表現、ページサイズ、入力未知キー拒否、HTTP/エラー対応、単一プロセスの凍結token保持、同token保存再送、現在の全需要グループ対象、集約表示・密度凡例の配信形式は本APIの技術具体化である。独自の業務機能の追加又は本人・教員による承認済みの証明ではない。採用言語・Webフレームワーク、ポート、起動手順、採用SQLite版の固定はこの通信契約を変えない実装事項として実装計画で決定する。独自のenum・JSON表記・新規データ表を担当者ごとに足さない。

Dで具体化済みの同保管場所統合、世代判定、期間終端、unfire-20261101-r1、子先親最後の保存、静的GIS構造は変更しない。これらを変更する場合はAPIだけでなくR/D/Sへの影響を明示し、業務変更なら本人の判断を受ける。全89件を新しい選択式質問として再決定しない。U08の最終内部承認者は本人であり、チーム全員の合意を新たな必須条件にしない。

<a id="traceability"></a>

## 13. 全89件の要件トレーサビリティ

要件IDはR付録Bの89件を重複なく収録した。最終選択はRとDの対応表で一致確認する。要旨・DB対応はD§12の各行を基準に、R本編・回答記録の条件を本書の各API/TXへ展開した。APIが不要な承認・ER条件は理由を明示し、無理に更新APIを作らない。検証欄Tは本書§11の実装後受入検証であり合格記号ではない。

| 要件ID | 最終選択 | 決定要旨とDB設計対応 | API又は非API責務 | 検証 |
|---|---|---|---|---|
| Q01 | A | 最新本編と今回追加条件を優先。内部承認と教員の外部条件を区別／設計書 §2 §14 | 非API：§1・12の正本・内部最終承認・外部確認 | T01 T26 |
| Q02 | A・B | 自己参照・多対多を保持。教員の対象線と木構造の意味は確認待ち／物理ER図 FK01〜FK32 と説明図 | 非API：§1・12の物理ER／説明図・教員条件。APIのためにFKを消さない | T01 T25 |
| Q03 | A | 在庫IDごとに正数量を割当。未割当は算入せず残余として表示／shelter_warehouses, stock_allocations | SH06 SH07 AL01 AL02 CA01 | T09 T10 T11 |
| Q04 | C | 統合元は取消拒否。統合先も取引時世代と現在世代が異なれば拒否。元記録保持。最終C、履歴消去ではない／stocks, stock_movements | MV01 MV03 ST08 ST09 | T03 T06 |
| Q05 | C | ロット番号・品目保存期間は設けない。在庫の使用期限を保持／items, stocks | IT02 IT04 ST02（禁止フィールド）、§1対象外 | T01 |
| Q06 | A | 倉庫IDと品目IDを複合PK。行なしと基準0を区別／stock_thresholds | TH01 TH02 WH05 | T14 |
| Q07 | A | ロット番号・品目保存期間は設けない。在庫の使用期限を保持／items, stocks | IT02 IT04 ST02（禁止フィールド）、§1対象外 | T01 |
| Q08 | A | 事前登録担当者IDと自動登録日時。別処理日・担当者管理画面はなし／operators, stock_movements | OP01 ST02 MV01 MV02 MV03（管理・任意日時APIなし） | T02 |
| Q09 | A | 事前登録担当者IDと自動登録日時。別処理日・担当者管理画面はなし／operators, stock_movements | OP01 ST02 MV01 MV02 MV03（管理・任意日時APIなし） | T02 |
| Q10 | A | 統合元は取消拒否。統合先も取引時世代と現在世代が異なれば拒否。元記録保持／stocks, stock_movements | MV01 MV03 ST08 ST09 | T03 T06 |
| Q11 | A | 計算実行ではDBへ保存せず、保存ボタンで凍結済み計算一式を新規保存／calculation_runs と5内訳表 | CA01 CR01 CR02 CR03 | T19 T21 |
| Q12 | B | 主要結果と内訳を分離して取得。展開状態はDB保存不要／calculation_group_results, calculation_item_snapshots, calculation_stock_snapshots | CA01 CA02 CR03、UI主要常時・詳細展開 | T26 |
| Q13 | A | 正式目標は避難所、試算条件は計算ヘッダー。更新操作を分離／shelters, calculation_runs | SH03 SH05 CA01 CR01 | T18 T19 |
| Q14 | B | 在庫IDごとに正数量を割当。未割当は算入せず残余として表示／shelter_warehouses, stock_allocations | SH06 SH07 AL01 AL02 CA01 | T09 T10 T11 |
| Q15 | A | 出庫・取消後数量が割当合計未満なら拒否。統合は元先とも割当なし／stocks, stock_allocations, stock_movements | MV02 MV03 ST05 AL02 | T03 T07 T09 |
| Q16 | A | facility_typeは施設種別。allocation_modeは計算区分。対応先は関係表のみ／warehouses, shelter_warehouses | WH02 WH04 SH06 SH07 | T10 |
| Q17 | A | 事前登録担当者IDと自動登録日時。別処理日・担当者管理画面はなし／operators, stock_movements | OP01 ST02 MV01 MV02 MV03（管理・任意日時APIなし） | T02 |
| Q18 | C | 期限未確認を警告付き暫定算入。日常基準比較へは拡張しない／stocks, calculation_stock_snapshots, calculation_group_results | CA01 EX01 ST01 WH05 | T12 T14 T16 |
| Q19 | A | 容量・容積のNULLと容量0は理由付き計算不可。期限切れ現物は容量算入／warehouses, items, stocks | WH05 WH04 IT04 | T14 |
| Q20 | B | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q21 | A | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q22 | A | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q23 | B | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q24 | A | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q25 | B | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q26 | A | 位置はDB、町丁目人口・境界は静的ファイル。人口需要自動推定なし／warehouses＋版付き静的GISファイル | GIS01 GIS02、§9静的配信・UI切替（編集APIなし） | T23 T24 T26 |
| Q27 | A | 緯度経度は対でNULL可。座標未確認は地図非表示・別一覧／warehouses | WH01 WH02 WH04 GIS01 | T23 |
| Q28 | A | 出庫・取消後数量が割当合計未満なら拒否。統合は元先とも割当なし／stocks, stock_allocations, stock_movements | ST03 ST08 ST09 MV03（統合取消APIなし） | T05 T06 |
| Q29 | A | FK03自己参照を維持。統合元を凍結し履歴を元IDへ残す／stocks.merged_into_stock_id | ST03 ST08 ST09 MV03（統合取消APIなし） | T05 T06 |
| Q30 | A | active/deleted/mergedを区別。割当中削除、統合元・終了品目復元を拒否／stocks, stock_state_events | ST01 ST03 ST05 ST06 HX01 | T07 |
| Q31 | A | active/deleted/mergedを区別。割当中削除、統合元・終了品目復元を拒否／stocks, stock_state_events | ST01 ST03 ST05 ST06 HX01 | T07 |
| Q32 | A | 無効化列・削除機能なし。削除トリガーでも拒否。最終A、途中Bの無効化案は不採用／warehouses | WH02 WH04（削除・無効化APIなし） | T01 |
| Q33 | B | 住所追加。名称・住所はパラメーター化LIKE検索。少量試作の部分一致は全走査／shelters | SH01 SH02 SH03 SH04 | T23 |
| Q34 | A | 基本制約はDB、行横断の業務条件はアプリのBEGIN IMMEDIATE内で保証／全19表・DDL・設計書 §8 §11 | 全書込みAPI、§5・8の共通DB接続・検証責務 | T25 |
| Q35 | A | 基本制約はDB、行横断の業務条件はアプリのBEGIN IMMEDIATE内で保証／全19表・DDL・設計書 §8 §11 | 全書込みAPI、§5・8の共通DB接続・検証責務 | T25 |
| Q36 | C | 単一担当者編集。ロック失敗時は全取消して入力保持／接続・トランザクション契約 | 全書込みAPI、§2・5の単一編集者・原子性 | T25 |
| Q37 | B | 原因コードを表示文へ対応付ける。ROLLBACK後も画面入力を保持／保存APIの例外処理 | 全APIの共通エラー・UI入力保持 | T02 T03 T21 T25 T26 |
| Q38 | B | 統合元先・数量・同一条件・取消禁止をプレビュー。確定時に再検証／stocks, stock_allocations | ST03 ST08 ST09 MV03（統合取消APIなし） | T05 T06 |
| Q39 | A | 統合取消APIなし。統合元UPDATE禁止。誤統合は別の許可操作で訂正／stocks | ST03 ST08 ST09 MV03（統合取消APIなし） | T05 T06 |
| Q40 | A | 同倉庫・品目・管理単位・保管場所・期限状態日付、非未確認、双方無割当。Dの後続条件で同一保管場所も必須／stocks, items | ST03 ST08 ST09 MV03（統合取消APIなし） | T05 T06 |
| Q41 | A | dated/none/unconfirmedと日付整合。変更前後・担当者・時刻を一括保存／stocks, stock_expiry_changes | ST01 ST03 ST07 HX02 CA01 WH05 | T12 T14 |
| Q42 | A | dated/none/unconfirmedと日付整合。変更前後・担当者・時刻を一括保存／stocks, stock_expiry_changes | ST01 ST03 ST07 HX02 CA01 WH05 | T12 T14 |
| Q43 | B | dated/none/unconfirmedと日付整合。変更前後・担当者・時刻を一括保存／stocks, stock_expiry_changes | ST01 ST03 ST07 HX02 CA01 WH05 | T12 T14 |
| Q44 | A | JST期限当日終了まで有効、翌日除外。現物数量と容量計算は残す／stocks, calculation_stock_snapshots | ST01 ST03 ST07 HX02 CA01 WH05 | T12 T14 |
| Q45 | B | active行の期限切れ・接近・未確認件数と一覧。件数は在庫行数、数量ではない／stocks, items | IT02 IT04 EX01 ST01 ST03（接近日数履歴なし） | T13 |
| Q46 | B | 必須・既定値なし・1〜3650整数。現在値のみ保存／items.near_expiry_days | IT02 IT04 EX01 ST01 ST03（接近日数履歴なし） | T13 |
| Q47 | A | 必須・既定値なし・1〜3650整数。現在値のみ保存／items.near_expiry_days | IT02 IT04 EX01 ST01 ST03（接近日数履歴なし） | T13 |
| Q48 | A | 必須・既定値なし・1〜3650整数。現在値のみ保存／items.near_expiry_days | IT02 IT04 EX01 ST01 ST03（接近日数履歴なし） | T13 |
| Q49 | A | 必須・既定値なし・1〜3650整数。現在値のみ保存／items.near_expiry_days | IT02 IT04 EX01 ST01 ST03（接近日数履歴なし） | T13 |
| Q50 | A | 既存在庫があれば管理単位変更を拒否。新品目IDと換算を登録。過去結果不変／items, item_conversions, 計算スナップショット | IT02 IT04 DG04 IC01 CR03 | T08 T16 T19 |
| Q51 | B | 終了後は新規在庫・追加入庫・再有効化禁止。出庫・条件付き取消・計算維持／items, stocks, stock_movements | IT01 IT05 ST02 ST06 MV02 MV03 CA01 | T07 T08 |
| Q52 | A | 終了後は新規在庫・追加入庫・再有効化禁止。出庫・条件付き取消・計算維持／items, stocks, stock_movements | IT01 IT05 ST02 ST06 MV02 MV03 CA01 | T07 T08 |
| Q53 | A | 終了後は新規在庫・追加入庫・再有効化禁止。出庫・条件付き取消・計算維持／items, stocks, stock_movements | IT01 IT05 ST02 ST06 MV02 MV03 CA01 | T07 T08 |
| Q54 | A | 明示グループと共通単位で集計。物理在庫は独立、必要量は需要ごと1回／demand_groups, item_conversions | DG01 DG02 DG03 DG04 IC01 CA01、UI簡易確認 | T16 T26 |
| Q55 | A | 明示グループと共通単位で集計。物理在庫は独立、必要量は需要ごと1回／demand_groups, item_conversions | DG01 DG02 DG03 DG04 IC01 CA01、UI簡易確認 | T16 T26 |
| Q56 | A | 計算条件変更は簡易確認。影響予測や承認表を追加しない／demand_groups, item_conversions | DG01 DG02 DG03 DG04 IC01 CA01、UI簡易確認 | T16 T26 |
| Q57 | A | 換算後と中間量は十進ROUND_HALF_UPの2桁。最終人数・日数は商を切捨て／factor_x100, REAL結果列, formula_version | DG04 IC01 CA01、全数値入力API、§2・6.4 | T15 T17 T18 |
| Q58 | B | 需要別不可理由と参考量を保存。部分不可なら総合人数日数NULL／calculation_group_results, calculation_runs | CA01 CA02 CR01 | T11 T16 T20 |
| Q59 | B | 需要別不可理由と参考量を保存。部分不可なら総合人数日数NULL／calculation_group_results, calculation_runs | CA01 CR01 CR03 | T16 T20 |
| Q60 | B | 避難所・計算日時・状態で検索。専用2件比較機能なし／calculation_runs とix_calculation_runs_1/2 | CR02 CR03（専用2件比較APIなし） | T22 |
| Q61 | A | UPDATE/DELETE禁止、保存後の子行INSERTも禁止。訂正は別run／calculation_runs と5内訳表 | CR01 CR03（更新・削除・無効化APIなし） | T20 T21 T22 |
| Q62 | B | 既存かつ小さいrun_idのみ任意参照。更新禁止と合わせ循環・自己参照を拒否／calculation_runs.correction_of_run_id | CR01 CR03 | T20 T22 |
| Q63 | B | 需要・品目・倉庫・対応先・有効在庫主要数量を正規化した写し。当時の根拠で表示／計算6表 | CA01 CA02 CR01 CR03 | T19 T20 T21 T22 |
| Q64 | A | 読取トランザクションで一式を確保。保存時は現マスタ・在庫を再読込しない／calculated_at, saved_at, 計算6表 | CA01 CA02 CR01 CR03 | T19 T20 T21 T22 |
| Q65 | A | 在庫IDごとに正数量を割当。未割当は算入せず残余として表示／shelter_warehouses, stock_allocations | SH06 SH07 AL01 AL02 CA01 | T09 T10 T11 |
| Q66 | A | 倉庫×品目で集計。異単位総和・地域在庫合計・全倉庫合計なし／stocks, stock_allocations, stock_thresholds | WH05 AL01 GIS01 GIS02（全倉庫・地域在庫集計なし） | T14 T24 |
| Q67 | A | 専用は1避難所へ利用可能全量。割当表を使わない／warehouses, shelter_warehouses | SH07 AL02 CA01 | T09 T10 T11 |
| Q68 | B | 数量0を含むactive行又は正の割当行が存在すれば区分・対応変更禁止／stocks, stock_allocations, shelter_warehouses | SH06 SH07 SH08 WH04 | T10 T11 |
| Q69 | B | 設定完了対応0と共有割当0は正常0。設定中・矛盾は理由付き不可／shelters.setup_state, calculation_group_results | SH06 SH08 CA01 CR01 | T11 T16 T20 |
| Q70 | B | 自己参照・多対多を保持。教員の対象線と木構造の意味は確認待ち／物理ER図 FK01〜FK32 と説明図 | 非API：§1・12の物理ER／説明図・教員条件。APIのためにFKを消さない | T01 T25 |
| Q71 | A | 基本制約はDB、行横断の業務条件はアプリのBEGIN IMMEDIATE内で保証／全19表・DDL・設計書 §8 §11 | 全書込みAPI、§5・8の共通DB接続・検証責務 | T25 |
| Q72 | B | 換算後と中間量は十進ROUND_HALF_UPの2桁。最終人数・日数は商を切捨て／factor_x100, REAL結果列, formula_version | DG04 IC01 CA01、全数値入力API、§2・6.4 | T15 T17 T18 |
| Q73 | B | 正の係数を100倍INTEGER。小数第3位入力は拒否。保存時の黙示丸めなし／item_conversions.factor_x100 と計算時同列 | DG04 IC01 CA01、全数値入力API、§2・6.4 | T15 T17 T18 |
| Q74 | A | 基本制約はDB、行横断の業務条件はアプリのBEGIN IMMEDIATE内で保証／全19表・DDL・設計書 §8 §11 | 全書込みAPI、§5・8の共通DB接続・検証責務 | T25 |
| Q75 | B | 最新本編と今回追加条件を優先。内部承認と教員の外部条件を区別／設計書 §2 §14 | 非API：§1・12の正本・内部最終承認・外部確認 | T01 T26 |
| P01 | P01：A | active/deleted/mergedを区別。割当中削除、統合元・終了品目復元を拒否／stocks, stock_state_events | IT01 IT05 ST02 ST06 MV02 MV03 CA01 | T07 T08 |
| P02 | P02：B | 設定完了対応0と共有割当0は正常0。設定中・矛盾は理由付き不可／shelters.setup_state, calculation_group_results | SH06 SH08 CA01 CR01 | T11 T16 T20 |
| P03 | P03：C | 倉庫区分・対応変更の専用監査履歴は追加しない。保存計算の当時帰属は残す／calculation_warehouse_snapshots, calculation_warehouse_links | SH07 MV01 CR03（区分変更専用履歴APIなし） | T10 T19 T22 |
| P04 | P04：A | 分割不可は整数、その他入力は2桁。REAL近似を既知制限として明記／REAL数量容量使用量結果、INTEGER係数人数日数ID | DG04 IC01 CA01、全数値入力API、§2・6.4 | T15 T17 T18 |
| P05 | P05：A | 0.004が0.00となる既知制限を許容し特別補正しない／shortage_quantity と丸め規則 | CA01、§6.4の微小不足特別補正なし | T17 |
| P06 | P06：A | JST期限当日終了まで有効、翌日除外。現物数量と容量計算は残す／stocks, calculation_stock_snapshots | ST01 EX01 CA01 | T12 |
| U01 | A | 区分・対応変更で旧先と新先の和集合をediting。名称住所編集では変更なし／shelters.setup_state | SH06 SH07 SH08 WH04 | T10 T11 |
| U02 | B | 数量0を含むactive行又は正の割当行が存在すれば区分・対応変更禁止／stocks, stock_allocations, shelter_warehouses | SH06 SH07 SH08 WH04 | T10 T11 |
| U03 | A | 分割不可は整数、その他入力は2桁。REAL近似を既知制限として明記／REAL数量容量使用量結果、INTEGER係数人数日数ID | DG04 IC01 CA01、全数値入力API、§2・6.4 | T15 T17 T18 |
| U04 | A | 換算後と中間量は十進ROUND_HALF_UPの2桁。最終人数・日数は商を切捨て／factor_x100, REAL結果列, formula_version | DG04 IC01 CA01、全数値入力API、§2・6.4 | T15 T17 T18 |
| U05 | A | 需要・品目・倉庫・対応先・有効在庫主要数量を正規化した写し。当時の根拠で表示／計算6表 | CA01 CA02 CR01 CR03 | T19 T20 T21 T22 |
| U06 | A | 基準日は計算実行当日のJSTから生成。任意日付入力APIなし／calculation_runs.base_date, calculated_at | CA01、基準日指定フィールドなし | T18 |
| U07 | A | facility_typeは施設種別。allocation_modeは計算区分。対応先は関係表のみ／warehouses, shelter_warehouses | SH06 SH07 SH08 WH04 | T10 T11 |
| U08 | A | 最新本編と今回追加条件を優先。内部承認と教員の外部条件を区別／設計書 §2 §14 | 非API：§1・12の正本・内部最終承認・外部確認 | T01 T26 |

## 14. 今回の照合結果と納品範囲

| 点検 | 今回の結果 |
|---|---|
| 添付版 | R/D/Sの実体を取得、§1のSHA-256を記録 |
| 89件 | R付録BとD§12のQ75件＋P6件＋U8件のID・最終選択を機械照合、一致。全件のAPI／非API責務とT検証を§13へ対応 |
| 物理構造 | Sを新規メモリーDBで実行。19表155列、FK32本、明示索引27本、トリガー34本。Word付録Aの全155列と名前を照合 |
| JSONとDDL | §11.2の完全な保存例を型変換し、子先・ヘッダー最後で実際の6表へINSERT、COMMIT成功。全キーをDB列集合と照合 |
| 不変防御 | 保存ヘッダーUPDATE・DELETE、ヘッダー作成後の子追加が拒否されることを確認 |
| 数値例 | 600/300/450/900Lの4例、1.245/1.244の十進丸め、0.004→0.00を検算 |
| DB健全性 | 今回の実行環境SQLite 3.49.1でforeign_key_check違反0、integrity_check=ok。D記載の過去84件試験を今回の実行実績として転記していない |
| 設計書構造 | 全API IDの重複、全89件の欠落、全列の欠落、JSON例の構文を点検 |
| 未実施 | 完成API・画面の受入T01〜T26、実GIS取得と表示、性能・実業務改善、教員適合。設計書作成を実装合格と扱わない |

本書の納品はMarkdownのAPI設計書1ファイルである。添付資料・既存DB・アプリ・GitHubの変更、公開・メッセージ送信は行っていない。実装時は本書とR/D/Sの契約を同時に守り、通信仕様の変更は版を更新してチームへ共有する。

