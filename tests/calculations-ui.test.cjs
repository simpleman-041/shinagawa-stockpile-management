/* 実スクリプトをDOM代替で検証する。ブラウザの描画・入力制約は別途確認する。 */
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");

const header = {shelter_id:"1",shelter_name:"架空避難所",target_people:100,target_days:2,base_date:"2026-11-12",calculated_at:"2026-11-12T00:00:00.000Z",formula_version:"unfire-20261101-r1",setup_state:"complete",result_state:"computed",has_unknown_expiry:true,min_people:75,min_days:1,unavailable_reason:null};
const preview = {calculation_token:"opaque-token",header,groups:[{group_id:"1",group_name:"試験需要",calculation_unit:"食",is_divisible:false,daily_usage:"3.00",source_text:"試験出典",version_or_date:"v1",conditions:"試験専用",result_state:"computed",reference_quantity:"450.50",required_quantity:"600.00",included_quantity:"450.50",covered_quantity:"450.50",shortage_quantity:"149.50",coverage_rate:"75.1",people:75,days:1,limits_people:true,limits_days:true,has_unknown_expiry:true,unavailable_reason:null}],items:[{item_id:"1",group_id:"1",item_name:"旧品目",quantity_unit:"箱",registration_state:"closed",is_divisible:false,factor_x100:"125",source_text:"試験出典",version_or_date:"v1",conditions:"試験専用"}],warehouses:[{warehouse_id:"1",warehouse_name:"試験倉庫",allocation_mode:"dedicated"}],warehouse_links:[{warehouse_id:"1",shelter_id:"1",shelter_name:"架空避難所"}],stocks:[{stock_id:"1",item_id:"1",warehouse_id:"1",stock_quantity:"360.40",allocated_total:"0.00",selected_allocation:"0.00",included_quantity:"360.40",converted_quantity:"450.50",expiry_state:"unconfirmed",expiry_date:null,selection_reason:"dedicated",unknown_expiry_warning:true,expires_in_period:false}],issues:[]};

async function harness(mode="calculate", search="?shelter_id=1", shelterCount=1) {
  class Element {
    constructor(tag="div") { this.tag=tag; this.children=[]; this.events={}; this.elements={}; this.value=""; this.hidden=false; this.disabled=false; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children=[...children]; }
    addEventListener(event,fn) { (this.events[event] ??= []).push(fn); }
    async dispatch(event) { for(const fn of this.events[event]||[]) await fn({preventDefault(){},currentTarget:this}); await new Promise(setImmediate); }
  }
  const template=fs.readFileSync(path.join(__dirname,"../app/templates/calculations.html"),"utf8");
  const nodes=Object.fromEntries([...template.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  if(mode!=="calculate") for(const id of ["calculation-form","calculation-inputs","save-calculation-form","save-inputs"]) delete nodes[id];
  if(mode!=="history") for(const id of ["history-form","history-inputs"]) delete nodes[id];
  if(nodes["save-calculation-form"]) nodes["save-calculation-form"].elements.correction_of_run_id=new Element("input");
  if(nodes["history-form"]) for(const name of ["shelter_id","result_state","from","to"]) nodes["history-form"].elements[name]=new Element("input");
  const calls=[],changes=[];
  let offline=false,reject=false,empty=false;
  const response=(data,status=200)=>({ok:status<400,json:async()=>structuredClone(data)});
  async function fetch(url,options) {
    calls.push({url,options}); if(offline) throw new Error("offline");
    if(url.startsWith("/api/v1/shelters?")) {
      const p=new URLSearchParams(url.split("?")[1]),start=Number(p.get("offset")),limit=Number(p.get("limit"));
      return response({data:Array.from({length:Math.max(0,Math.min(limit,shelterCount-start))},(_,i)=>({shelter_id:String(start+i+1),name:`架空避難所${start+i+1}`,target_people:100,target_days:2,setup_state:"complete"})),page:{total:shelterCount,limit,offset:start}});
    }
    if(url==="/api/v1/calculations") return reject ? response({error:{message:"目標条件を確認してください。"}},422) : response({data:preview});
    if(url.startsWith("/api/v1/calculations/")) return response({error:{message:"保持していません。再計算してください。"}},409);
    const saved={run:{...header,run_id:"1",saved_at:"2026-11-13T00:00:00.000Z",correction_of_run_id:null},...Object.fromEntries(["groups","items","warehouses","warehouse_links","stocks"].map(k=>[k,preview[k]])),correction_run_ids:["2"]};
    if(url==="/api/v1/calculation-runs" && options.method==="POST") return reject ? response({error:{message:"訂正元を確認してください。"}},422) : response({data:saved},201);
    if(url==="/api/v1/calculation-runs/1") return response({data:saved});
    if(url.startsWith("/api/v1/calculation-runs?")) return response({data:empty?[]:[saved.run],page:{total:empty?0:1,limit:20,offset:0}});
    throw new Error("Unexpected request "+url);
  }
  const document={body:{dataset:{mode,runId:"1"}},getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  class FormData { constructor(form){return Object.entries(form.elements).map(([k,v])=>[k,v.value]);} }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../app/static/js/calculations.js"),"utf8"),{document,fetch,URLSearchParams,location:{search},history:{replaceState:(_a,_b,url)=>changes.push(url)},FormData});
  await new Promise(setImmediate);
  return {nodes,calls,changes,setOffline:v=>offline=v,setReject:v=>reject=v,setEmpty:v=>empty=v};
}

for (const count of [0,1,50,51,401]) test(`計算・履歴の避難所選択: ${count}件全てへ到達し検索時は再取得しない`,async()=>{
  for (const mode of ["calculate","history"]) {
    const h=await harness(mode,count ? `?shelter_id=${count}` : "",count),n=h.nodes;
    const options=n["calculation-shelter"].children;
    assert.equal(options.length,count); assert.equal(new Set(options.map(o=>o.value)).size,count);
    if(count) assert.equal(options.at(-1).value,String(count));
    const calls=h.calls.filter(c=>c.url.startsWith("/api/v1/shelters?"));
    assert.equal(calls.length,Math.max(1,Math.ceil(count/200)));
    if(mode==="calculate" && count) {
      assert.equal(n["calculation-shelter"].value,String(count));
      await n["calculation-form"].dispatch("submit");
      assert.equal(JSON.parse(h.calls.at(-1).options.body).shelter_id,String(count));
    } else if(mode==="history") await n["history-form"].dispatch("submit");
    assert.equal(h.calls.filter(c=>c.url.startsWith("/api/v1/shelters?")).length,calls.length);
  }
});

test("目標初期値、計算結果、整数調達切上げ、根拠、明示保存と二重操作防止",async()=>{
  const h=await harness(),n=h.nodes;
  assert.equal(n["target-people"].value,100); assert.equal(n["target-days"].value,2);
  assert.equal(h.calls.filter(c=>c.options.method==="POST").length,0);
  await n["calculation-form"].dispatch("submit");
  assert.deepEqual(JSON.parse(h.calls.at(-1).options.body),{shelter_id:"1",target_people:100,target_days:2});
  assert.match(n["result-minimum"].textContent,/75人.*1日/);
  assert.match(n["result-groups"].children[0].children[4].textContent,/149.50.*150/);
  assert.equal(n["result-warning"].hidden,false);
  assert.match(h.changes[0],/token=opaque-token/);
  assert.equal(n["save-inputs"].disabled,false);
  await n["save-calculation-form"].dispatch("submit");
  assert.equal(n["save-inputs"].disabled,true);
  assert.match(n["save-state"].children[1].href,/calculation-runs\/1/);
  const count=h.calls.length; await n["save-calculation-form"].dispatch("submit"); assert.equal(h.calls.length,count);
});

test("計算・保存の拒否と通信失敗は入力と直前の結果を保持し自動再送しない",async()=>{
  const h=await harness(),n=h.nodes;
  await n["calculation-form"].dispatch("submit");
  n["target-people"].value="120"; h.setReject(true);
  await n["calculation-form"].dispatch("submit");
  assert.equal(n["target-people"].value,"120"); assert.match(n["calculation-error"].textContent,/前回の計算/);
  n["save-calculation-form"].elements.correction_of_run_id.value="999";
  await n["save-calculation-form"].dispatch("submit");
  assert.equal(n["save-calculation-form"].elements.correction_of_run_id.value,"999");
  h.setOffline(true); const count=h.calls.length;
  await n["save-calculation-form"].dispatch("submit");
  assert.equal(h.calls.length,count+1); assert.match(n["calculation-error"].textContent,/通信に失敗/);
  assert.equal(n["calculation-result"].hidden,false); assert.equal(n["save-inputs"].disabled,false);
});

test("喪失トークンは未保存と再計算を案内し、履歴の空結果を表示する",async()=>{
  const lost=await harness("calculate","?shelter_id=1&token=lost");
  assert.match(lost.nodes["calculation-error"].textContent,/再計算/); assert.equal(lost.nodes["save-inputs"].disabled,true);
  const h=await harness("history",""),n=h.nodes; h.setEmpty(true);
  await n["history-form"].dispatch("submit"); await new Promise(setImmediate);
  assert.equal(n["history-empty"].hidden,false); assert.equal(n["history-table"].hidden,true);
  assert.equal(n["history-next"].disabled,true);
});

test("保存詳細は保存データだけを表示し、訂正リンクを提供する",async()=>{
  const h=await harness("saved","");
  assert.deepEqual(h.calls.map(c=>c.url),["/api/v1/calculation-runs/1"]);
  assert.match(h.nodes["result-title"].textContent,/#1/);
  assert.match(h.nodes["correction-links"].children[0].href,/calculation-runs\/2/);
});
