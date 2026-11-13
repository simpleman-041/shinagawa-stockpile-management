# GIS・地図表示の実装・検証報告

2026年11月13日（JST）。機能コードと固定版を追加。実ブラウザ検証・実倉庫座標の照合待ち。

## 利用者の操作と範囲

倉庫一覧から `/map` を開く。Leafletで登録済み座標の倉庫ピンを表示し、未確認の倉庫は別一覧に出す。
ピン・倉庫一覧から横概要を開き、住所・施設種別・容量と品目ごとの現物数量・割当済み・未割当・期限切れ・未確認を確認する。
倉庫詳細・在庫一覧へ進める。倉庫詳細画面とWH05概要APIは存在しなかったため、地図に必要な範囲で今回追加した。
概要は異単位の数量を合算せず、容量には期限切れ現物も含める。日常基準では期限未確認を除外する。
容量・容積の不足は理由付き計算不可とし、容量0・100%・超過を区別する。

検索対象は倉庫名・住所または品目名。期限接近／切れ／未確認、日常基準未満でも倉庫を絞り込む。
名称はリテラル部分一致、在庫・概要は既存ST01と今回のWH05を参照する。条件クリアと再取得を提供する。
人口レイヤーは倉庫ピンと別のLayerGroupで管理し、切替・取得失敗でピンを削除しない。
人口密度を5等幅階級で色分けし、区域選択で総人口・面積・密度・区域コード・基準日を横概要へ出す。
地理院タイルの通信失敗、人口データ不正、倉庫の取得失敗を別々に案内する。取得できた前回の倉庫表示と検索入力を保持し、自動再送しない。

## 採用資料と判断

- 前回までの要件定義2.0（2026-11-01）を継続適用：F16、§7・10、Q19〜27・66、V06・V10。
- API1.0（2026-11-04）：GIS01/02、WH05、§9、T23/24。GIS人口表の追加や未掲載の編集APIは作らない。
- DB設計・DDL 2026-11-01を維持。全読取は既存接続の読取BEGIN。DB・在庫・保存計算・既存マスターは更新しない。
- SD-6画面設計S002の検索・件数・結果一覧・地図・詳細導線を参照。版表示は未確認。拡大はLeafletのズームで扱い、後続要件の横概要と人口切替・凡例を追加した。
- READMEで採用されているLeafletを使用。1.9.4を公式npm配布元からライセンスとともにローカル同梱。Pythonランタイムの依存追加なし。

人口・境界は同じ2020年版のCODH/e-Stat原TopoJSONから採用した。全131区域、人口422,488人、KEY_CODE一意、人口総数は品川区公表値と一致。
区域名がNULLの1区域は「名称未設定」とコードを表示し、架空町名を付けていない。
出典、元ファイル、原版ハッシュ、利用条件、面積単位、CRS変換、再生成方法は [固定版README](../data/gis/README.md) に記録した。
JGD2000からWGS84への変換は零パラメータ近似であり、測量用途ではない。
人口基準日は2020-10-01。2026年の人口や現在の町丁目境界に更新したものではない。

原版：[CODH提供元](https://geoshape.ex.nii.ac.jp/ka/resource/13109.html)、[原TopoJSON](https://geoshape.ex.nii.ac.jp/ka/topojson/2020/13/r2ka13109.topojson)。
総人口の照合：[品川区の2020年国勢調査結果](https://www.city.shinagawa.tokyo.jp/contentshozon2024/2024tokeisho15.pdf)。

## API・固定版検証

| 操作 | 経路 | 応答 |
| --- | --- | --- |
| 全倉庫位置 | GET /api/v1/gis/warehouses | located/unlocatedとstock_data_kind:sample、200 |
| 現行固定版 | GET /api/v1/gis/datasets/current | GISDataset、200。不整合・未配置は503 |
| 倉庫概要 | GET /api/v1/warehouses/{warehouse_id}/summary | WarehouseSummary、200 |
| 出典・版 | GET /gis/{dataset_id}/manifest.json | Manifestをdataで包まず配信 |
| 区域 | GET /gis/{dataset_id}/areas.geojson | application/geo+json |
| 人口 | GET /gis/{dataset_id}/population.csv | text/csv;charset=utf-8 |

IDはAPIの文字列表現。倉庫座標はlatitude/longitude、GeoJSONは経度・緯度順。
すべて読取専用。未知クエリー、GET本文、不在ID、未知パス、未提供メソッドを契約に従って拒否する。
配信要求ごとにManifest・2ファイルのハッシュ・JSON重複キー・区域コード重複・座標範囲・リング・人口整数・基準日・出典・CRSを一括検証し、検証した同じバイト列を返す。
パスは固定ファイル3種と安全な版IDに限定し、ルート外やシンボリックリンク経由の参照を拒否する。
人口行欠損・空値・面積欠損／0は密度不明として扱い、人口0は既知の密度0と区別する。
重複・不正人口・区域コード不一致・基準日不一致・ハッシュ不一致等の不正版は配信しない。
クライアントでも2ファイルのSHA-256をManifestと照合し、異なる版の混在を検出する。
色判定は人口整数・面積の十進値をBigIntの有理数で比較し、表示用2桁境界や二進近似を使わない。
全既知密度0は1階級、すべて密度不明は未知色のみ。

## 変更ファイル

- `app/services/gis.py`：座標読取と固定版検証・凡例。
- `app/services/warehouse_summary.py`：倉庫別容量・品目別物理在庫・割当・日常基準。
- `app/routes/gis.py`、`app/__init__.py`、`app/routes/demand_groups.py`：API登録、固定版配信、対象404/405。
- `app/routes/pages.py`、`app/templates/map.html`、`app/templates/warehouse_detail.html`：画面と詳細入口。
- `app/static/js/map.js`、`app/static/css/map.css`、`app/templates/warehouses.html`：地図操作、検索、導線。
- `app/static/vendor/leaflet-1.9.4/`：ライブラリ・画像・ライセンス。
- `data/gis/`、`tools/build-gis-dataset.cjs`：公開原版、配信用固定版、再生成と出典。
- `tests/test_gis.py`、`tests/map-ui.test.cjs`：API・DB・画面スクリプトの検証。
- `README.md`、本報告：操作・前提・残る確認。

## 検証

Python3.15.2／SQLite3.53.4／pytest9.2.0。承認DDLから作成した隔離DBを使用。
新規pytest30件を含む全438件成功（失敗・エラー・スキップ0件）。
地図のDOM/Leaflet代替6件と既存画面スクリプト8件、計14件成功。JavaScript構文・git diff --checkも成功。

| 受入条件 | 自動検証 |
| --- | --- |
| 全倉庫を分離、NULL座標を0にしない、人口失敗から独立 | 成功 |
| 版付きJSON/GeoJSON/CSV、先頭0コード、出典・ハッシュ、同梱実データ | 成功 |
| 重複コード、負数・小数人口、不正基準日、範囲外座標、未閉合リング、CRS不一致の拒否 | 成功 |
| 面積0／欠損、人口欠損・0、全0・全不明凡例 | 成功 |
| 人口ON/OFF、人口取得失敗、倉庫失敗、背景タイル失敗 | DOM/Leaflet代替で成功 |
| ピン・区域の横概要、品目検索・期限条件・条件クリア、未丸め階級境界 | DOM/Leaflet代替で成功 |
| 倉庫容量100%・超過、容量／容積不足、期限切れ現物算入 | 成功 |
| 割当によるJOIN増幅なし、異単位を合算しない、日常基準だけの品目・0基準 | 成功 |
| 期限当日有効、日常基準では未確認除外、論理削除除外、GETでDB全体不変 | 成功 |
| 画面入口・404、未知クエリー・GET本文・405とAllow | 成功 |

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=instance/gis-regression-r1
node tests/map-ui.test.cjs
node tests/calculations-ui.test.cjs
node tests/warehouse-settings-ui.test.cjs
node tests/stocks-movements-ui.test.cjs
node --check app/static/js/map.js
git diff --check
```

Windowsの一時領域制約のためpytestは専用basetempを指定して実行した。
Nodeの複数ファイル同時起動はspawn EPERMで実行できなかったため、各ファイルを単独起動して同じケースを完走した。

## 未完了の確認・対象外

実ブラウザは接続ホストが利用不可。Microsoft Edgeのネイティブ取得は `Computer Use app approval timed out` となり操作に到達できなかった。
正常描画・空状態・重要拒否・通信失敗・ズーム・ピン重なり・キーボード・スマートフォン幅は手動未確認。
DOM代替とJinja2の成功を実ブラウザ確認済みとしていない。

既存開発DBの登録座標は実倉庫の出典付き位置としては未確認で、公式住所と整合しない例がある。
例えば「大崎備蓄倉庫」の登録座標35.5,140.1、「大井1丁目備蓄倉庫」の35.8,139.7は、
公式資料の西五反田3-6-38／大井1-15-13に対応する施設座標としては採用できない。
[品川区地域防災計画の所在地一覧](https://www.city.shinagawa.tokyo.jp/ct/pdf/hpg000001888_72.pdf)を参照し、実施設位置を照合・登録する必要がある。
今回、DBの名称・住所・座標・在庫の自動補正や初期データ投入は行っていない。地図上は登録座標であることを明示した。
実倉庫位置への照合と実ブラウザ操作が済むまで、GIS全体の受入完了とはしない。

人口からの需要自動設定、地域別在庫集計、配送、データ編集・アップロード、基準編集画面、認証、本番公開は対象外。
人間による独立レビューも受入前に必要。
