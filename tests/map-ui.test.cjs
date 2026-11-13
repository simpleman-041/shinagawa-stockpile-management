/* 実map.jsをDOM/Leaflet代替で検証する。描画・地図タイルの実機確認とは別。 */
const {test}=require("node:test"), assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),{webcrypto,createHash}=require("node:crypto");

async function harness({populationFailure=false, warehouseFailure=false}={}) {
  class Element {
    constructor(){this.children=[];this.events={};this.value="";this.checked=true;this.hidden=false;this.style={};}
    append(...n){this.children.push(...n);} prepend(...n){this.children.unshift(...n);} replaceChildren(...n){this.children=[...n];}
    addEventListener(k,fn){this.events[k]=fn;} async dispatch(k){this.events[k]?.({preventDefault(){}});await settle();}
  }
  const template=fs.readFileSync(path.join(__dirname,"../app/templates/map.html"),"utf8");
  const nodes=Object.fromEntries([...template.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const map={layers:new Set(),setView(){return this;},fitBounds(){},removeLayer(l){this.layers.delete(l);}};
  class Layer {
    constructor(){this.events={};this.children=[];}
    addTo(target){if(target===map)map.layers.add(this);else target.children.push(this);return this;}
    on(k,fn){this.events[k]=fn;return this;}
    getLayers(){return this.children;} getBounds(){return {};} clearLayers(){this.children=[];}
  }
  let pins,regions,tiles,popFail=populationFailure,warehouseFail=warehouseFailure;
  const L={map:()=>map,featureGroup:()=>pins=new Layer(),tileLayer:()=>tiles=new Layer(),divIcon:x=>x,marker:(coords)=>{const l=new Layer();l.coords=coords;return l;},geoJSON:(data,options)=>{regions=new Layer();regions.options=options;data.features.forEach(f=>{const l=new Layer();options.onEachFeature(f,l);regions.children.push(l);});return regions;}};
  const features=[{type:"Feature",id:"001",properties:{area_name:"試験区域",area_km2:.5},geometry:{type:"Polygon",coordinates:[]}}];
  const geo=JSON.stringify({type:"FeatureCollection",features});
  const csv="area_code,population,population_date\n001,10,2020-10-01\n";
  const hash=s=>createHash("sha256").update(s).digest("hex");
  const manifest={dataset_id:"test",population_date:"2020-10-01",boundary_version:"試験版",sources:[{url:"https://example.com/source",usage_terms:"https://example.com/terms"}],area_definition:"試験",sha256:{areas_geojson:hash(geo),population_csv:hash(csv)}};
  const calls=[];
  const response=(value,status=200)=>({ok:status===200,json:async()=>structuredClone(value),arrayBuffer:async()=>new TextEncoder().encode(value).buffer});
  async function fetch(url) {
    calls.push(url);
    if(url==="/api/v1/gis/warehouses"){
      if(warehouseFail)throw Error("倉庫通信失敗");
      return response({data:{located:[{warehouse_id:"1",name:"試験倉庫%",address:"試験住所",latitude:35.6,longitude:139.7}],unlocated:[{warehouse_id:"2",name:"座標不明",address:"試験住所",latitude:null,longitude:null}],stock_data_kind:"sample"}});
    }
    if(url==="/api/v1/gis/datasets/current")return popFail?response({error:{message:"未配置"}},503):response({data:{dataset_id:"test",manifest_url:"/manifest",areas_url:"/areas",population_url:"/population",legend:{classes:[{lower:"0.00",upper:"20.00",color:"#EFF3FF"}],unknown_color:"#BDBDBD"}}});
    if(url==="/manifest")return response(manifest);
    if(url==="/areas")return response(geo);
    if(url==="/population")return response(csv);
    if(url.startsWith("/api/v1/stocks?"))return response({data:[{stock:{warehouse_id:"1"},item_name:"架空米",location:"別の場所"}],page:{total:1}});
    if(url==="/api/v1/warehouses/1/summary")return response({data:{warehouse:{name:"試験倉庫%",address:"試験住所",facility_type:"試験"},base_date:"2026-11-13",items:[],capacity:{state:"unavailable",issues:[{message:"容積未設定"}]}}});
    throw Error(url);
  }
  const context={document:{getElementById:id=>nodes[id],createElement:()=>new Element()},L,fetch,crypto:webcrypto,TextDecoder,URLSearchParams,console};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../app/static/js/map.js"),"utf8"),context);
  async function settle(){for(let i=0;i<8;i++)await new Promise(setImmediate);}
  await settle();
  return {nodes,map,pins,getRegions:()=>regions,tiles,calls,helpers:context.UnfireGIS,setPopFailure:v=>popFail=v,settle};
}

test("人口表示のON/OFFで倉庫ピンを維持し、座標不明をピンにしない",async()=>{
  const h=await harness(); await h.settle();
  assert.equal(h.pins.children.length,1);
  assert.deepEqual(Array.from(h.pins.children[0].coords),[35.6,139.7]);
  const regions=h.getRegions();assert.ok(h.map.layers.has(regions));
  h.nodes["population-toggle"].checked=false; await h.nodes["population-toggle"].dispatch("change");
  assert.ok(!h.map.layers.has(regions));assert.ok(h.map.layers.has(h.pins));assert.equal(h.pins.children.length,1);
  h.nodes["population-toggle"].checked=true;await h.nodes["population-toggle"].dispatch("change");
  assert.ok(h.map.layers.has(regions));
});

test("人口取得失敗でも倉庫ピンを残し、再取得できる",async()=>{
  const h=await harness({populationFailure:true});
  assert.equal(h.pins.children.length,1);assert.match(h.nodes["population-error"].textContent,/倉庫表示は引き続き/);
  h.setPopFailure(false);await h.nodes["map-refresh"].dispatch("click");await h.settle();
  assert.ok(h.getRegions());assert.equal(h.nodes["population-error"].hidden,true);
  h.setPopFailure(true);await h.nodes["map-refresh"].dispatch("click");
  assert.equal(h.pins.children.length,1);
});

test("倉庫失敗とタイル失敗を分けて案内し人口レイヤーを維持",async()=>{
  const h=await harness({warehouseFailure:true});await h.settle();
  assert.match(h.nodes["warehouse-error"].textContent,/倉庫取得失敗/);
  assert.ok(h.map.layers.has(h.getRegions()));
  h.tiles.events.tileerror();assert.match(h.nodes["tile-error"].textContent,/一覧は引き続き/);
});

test("ピンと区域の選択で横概要を更新し、名称住所をリテラル検索",async()=>{
  const h=await harness();await h.settle();
  h.pins.children[0].events.click();await h.settle();
  assert.equal(h.nodes["map-info-title"].textContent,"試験倉庫%");
  assert.ok(h.nodes["map-info"].children.some(n=>n.href==="/warehouses/1"));
  h.getRegions().children[0].events.click();
  assert.equal(h.nodes["map-info-title"].textContent,"試験区域");
  assert.match(h.nodes["map-info"].children[1].textContent,/10人/);
  h.nodes["map-query"].value="%";await h.nodes["map-search"].dispatch("submit");assert.equal(h.pins.children.length,1);
  h.nodes["map-query"].value="存在しない";await h.nodes["map-search"].dispatch("submit");assert.equal(h.pins.children.length,0);
});

test("人口コード先頭0と欠損、未丸め密度で5等幅・境界・最上位を判定",async()=>{
  const {helpers:h}=await harness();
  const population=h.csv('area_code,population,population_date\n"001",10,2020-10-01\n002,,2020-10-01\n');
  assert.equal(population.get("001").population,10);assert.equal(population.get("002").population,null);
  assert.equal(h.density({id:"001",properties:{area_km2:0}},population),null);
  assert.equal(h.densityColor(null,{n:100n,d:1n}),"#BDBDBD");assert.equal(h.densityColor({n:0n,d:1n},{n:0n,d:1n}),"#EFF3FF");
  assert.equal(h.densityColor({n:20n,d:1n},{n:100n,d:1n}),"#BDD7E7");assert.equal(h.densityColor({n:100n,d:1n},{n:100n,d:1n}),"#08519C");
  assert.equal(h.densityColor({n:2n,d:1000n},{n:1n,d:100n}),"#BDD7E7"); // 表示境界が0.00でも未丸め値で判定。
  const data=new Map([["max",{population:7}],["border",{population:7}]]);
  const max=h.densityRatio({id:"max",properties:{area_km2:100}},data);
  const border=h.densityRatio({id:"border",properties:{area_km2:500}},data);
  assert.equal(h.densityColor(border,max),"#BDD7E7"); // 0.014/0.07の二進近似でも下の階級に落とさない。
});

test("品目名と期限条件で倉庫を絞り、条件クリアで全倉庫へ戻す",async()=>{
  const h=await harness();
  h.nodes["map-search-target"].value="item";h.nodes["map-stock-status"].value="expired";h.nodes["map-query"].value="米";
  await h.nodes["map-search"].dispatch("submit");assert.equal(h.pins.children.length,1);
  assert.ok(h.calls.some(url=>url.startsWith("/api/v1/stocks?") && url.includes("expiry_status=expired")));
  h.nodes["map-query"].value="別の場所";await h.nodes["map-search"].dispatch("submit");assert.equal(h.pins.children.length,0);
  await h.nodes["map-clear"].dispatch("click");assert.equal(h.pins.children.length,1);
});
