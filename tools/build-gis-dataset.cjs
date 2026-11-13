/* 開発時のみ。CODH公開TopoJSONからAPI §9の固定版を作成する。
 * node tools/build-gis-dataset.cjs source.topojson proj4.js output-directory
 * proj4 2.23.0を使用。ランタイムには不要。 */
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const [input, projPath, output] = process.argv.slice(2);
const proj4 = require(path.resolve(projPath));
const source = JSON.parse(fs.readFileSync(input,"utf8"));
if(source.type !== "Topology" || source.metadata["dc:source"] !== "r2ka13109.shp") throw Error("Unexpected source");
// JGD2000 (EPSG:4612) → WGS84。零パラメータ近似。測量用途には使用しない。
const from = "+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs";
const arcs = source.arcs.map(arc => {
  let x=0,y=0;
  return arc.map(p => {
    let xy=p;
    if(source.transform){x+=p[0];y+=p[1];xy=[x*source.transform.scale[0]+source.transform.translate[0],y*source.transform.scale[1]+source.transform.translate[1]];}
    return proj4(from,"EPSG:4326",xy).map(v=>Number(v.toFixed(8)));
  });
});
function ring(ids){
  const points=[];
  ids.forEach(id=>{let a=arcs[id<0?~id:id]; if(id<0)a=[...a].reverse(); if(points.length && JSON.stringify(points.at(-1))!==JSON.stringify(a[0]))throw Error("Disconnected arc");points.push(...(points.length?a.slice(1):a));});
  if(JSON.stringify(points[0])!==JSON.stringify(points.at(-1))) throw Error("Open ring");
  return points;
}
const geometries=source.objects.town.geometries;
const features=geometries.map(g=>{
  const p=g.properties;
  if(p.CITY!=="109"||p.PREF!=="13"||p.AREA_MAX_F!=="M"||!Number.isSafeInteger(p.JINKO)||p.JINKO<0)throw Error("Unverified properties");
  return {type:"Feature",id:p.KEY_CODE,properties:{area_name:p.S_NAME || `名称未設定（原データ ${p.KEY_CODE}）`,area_km2:p.AREA/1000000},geometry:{type:g.type,coordinates:g.type==="Polygon"?g.arcs.map(ring):g.type==="MultiPolygon"?g.arcs.map(a=>a.map(ring)):(()=>{throw Error("Geometry");})()}};
});
if(features.length!==131||new Set(features.map(f=>f.id)).size!==131||geometries.reduce((a,g)=>a+g.properties.JINKO,0)!==422488)throw Error("Source totals changed; reverify");
const areas=JSON.stringify({type:"FeatureCollection",features})+"\n";
const population="area_code,population,population_date\n"+geometries.map(g=>`${g.properties.KEY_CODE},${g.properties.JINKO},2020-10-01`).join("\n")+"\n";
const sha=s=>crypto.createHash("sha256").update(s).digest("hex");
const manifest={dataset_id:path.basename(output),version:"1.0",population_date:"2020-10-01",boundary_version:"令和2年国勢調査・CODH公開版2022-06-24",area_code_system:"令和2年国勢調査 KEY_CODE（原データの桁数を保持）",sources:[{url:"https://geoshape.ex.nii.ac.jp/ka/resource/13109.html",usage_terms:"https://creativecommons.org/licenses/by/4.0/"},{url:"https://geoshape.ex.nii.ac.jp/ka/topojson/2020/13/r2ka13109.topojson",usage_terms:"https://www.e-stat.go.jp/terms-of-use"}],area_definition:"国勢調査の町丁・字等境界。原資料で区域名が欠ける1区域は名称未設定と表示。面積は原データAREA(m²)を1,000,000で除してkm²化。2020年人口JINKOを同一KEY_CODEで対応。JGD2000からWGS84へproj4 2.23.0の零パラメータ近似で変換（地図参考表示用、測量用途不可）。",area_unit:"km2",crs:"EPSG:4326",sha256:{areas_geojson:sha(areas),population_csv:sha(population)}};
fs.mkdirSync(output,{recursive:true});
fs.writeFileSync(path.join(output,"areas.geojson"),areas);
fs.writeFileSync(path.join(output,"population.csv"),population);
fs.writeFileSync(path.join(output,"manifest.json"),JSON.stringify(manifest,null,2)+"\n");
console.log(`${features.length} areas, 422488 people, source sha256 ${sha(fs.readFileSync(input))}`);
