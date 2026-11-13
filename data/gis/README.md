# GIS固定版

`shinagawa-census2020-v1` は品川区の2020年国勢調査町丁・字等境界・人口の参考表示用固定版。
現在人口や供給対象区域を表さない。人口から備蓄目標を推定しない。

## 出典と検証

- 『国勢調査町丁・字等別境界データセット』（CODH作成）／「令和2年国勢調査町丁・字等別境界データ」（e-Stat）を加工。
- [提供元ページ](https://geoshape.ex.nii.ac.jp/ka/resource/13109.html)、[原TopoJSON](https://geoshape.ex.nii.ac.jp/ka/topojson/2020/13/r2ka13109.topojson)、[DOI](https://doi.org/10.20676/00000450)。2026-11-13取得。
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) および [e-Stat利用規約](https://www.e-stat.go.jp/terms-of-use)。画面とManifestに出典・加工・利用条件を表示する。
- 原ファイルは `sources/r2ka13109.topojson`。SHA-256は `c55bc7478b52863cb9a07eeff97587bafc5a2e615194247f73283aa908c7e5f7`。
- 原メタデータ `dc:source=r2ka13109.shp`、`dc:issued=2022-06-24`、`PREF=13,CITY=109` を確認。
- KEY_CODE全131件は一意、全区域がAREA_MAX_F=M。原JINKO合計422,488人は[品川区の公表値](https://www.city.shinagawa.tokyo.jp/contentshozon2024/2024tokeisho15.pdf)の2020-10-01人口と一致する。
- KEY_CODEは原資料の桁数をそのまま保持する。`131090280` は区域名S_NAMEがNULLのため、「名称未設定（原データ 131090280）」という表示ラベルを付けた。架空の町名への置換、区域の削除、桁数の補完を行っていない。
- AREAは原資料のm²を1,000,000で除してkm²化。JINKOは同一TopoJSON内の同一KEY_CODEから採用した。異なる年の人口との結合や面積の推定は行っていない。
- 原版のJGD2000経緯度（metadataのdatum=2000）から、proj4 2.23.0・GRS80・零パラメータ近似でWGS84へ変換。出力は経度・緯度順、8桁表示。地図参考表示の近似であり、測量・施設入口の精密位置決定には使わない。
- ポリゴンは元の全頂点・穴・区域を維持し、TopoJSONの共有arcと逆向きを復元。簡略化は行っていない。生成ファイルのハッシュをManifestに記録して毎回検証する。

## 再生成と差替え

ビルド時だけNodeとproj4を使う。アプリ実行時のPython依存は増やしていない。
公式npm版 `proj4@2.23.0` の `dist/proj4.js` をビルド用に用意し、次を実行する。

```powershell
node tools/build-gis-dataset.cjs data/gis/sources/r2ka13109.topojson instance/proj4.js data/gis/shinagawa-census2020-v1
```

このコマンドは同梱版を再現するためのもの。人口や境界を更新する場合は出典・版・利用条件・区域コード・人口基準日を再照合し、ビルダーの検証条件も更新する。
新しいdataset_idのディレクトリを別に作成して検証後、Flaskの `GIS_CURRENT_DATASET` を切り替える。
`GIS_DATA_ROOT` は固定版ルート。テストでは隔離ディレクトリへ切り替える。
配信中のdataset_idの内容を上書きしない。旧版ファイルも一式残す。
不整合版は503 GIS_DATA_UNAVAILABLEで配信を拒否する。未設定人口・面積0／欠損は密度不明色となり、0人口と区別する。

倉庫位置はDBの登録座標であり、この固定版には含めていない。公式の施設位置を照合してから倉庫編集で登録する。
住所からの自動ジオコーディングや、現在の登録座標の自動補正は行わない。

Leaflet 1.9.4は `app/static/vendor/leaflet-1.9.4` にBSD-2-Clauseライセンス付きで同梱。
背景は[地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)を実行時に取得し、出典リンクを表示する。
人口・境界・Leaflet本体はローカル配信。背景通信が失敗しても倉庫・境界は独立して表示する。
