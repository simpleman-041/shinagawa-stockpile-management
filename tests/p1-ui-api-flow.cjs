/* DOM代替で実JSを動かし、HTTPは実Flask・正本DDLの隔離DBへ接続する。 */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const {harness} = require("./helpers/calculation-conditions-harness.cjs");
const base = process.argv[2];
if (!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error("専用テストサーバーのURLを指定してください。");
const calls = [];
async function transport(url, options) {
  calls.push({url, method: options?.method || "GET", body: options?.body && JSON.parse(options.body)});
  return fetch(base + url, options);
}
async function api(url, method = "GET", values) {
  const r = await fetch(base + "/api/v1" + url, {method, ...(values === undefined ? {} : {headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)})});
  const data = await r.json(); assert.ok(r.ok, JSON.stringify(data)); return data.data;
}

async function existingForm(url, filename) {
  const html = await (await fetch(base + url)).text(), nodes = {};
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) nodes[match[1]] = {hidden: true, textContent: ""};
  const forms = [];
  for (const match of html.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/g)) {
    const attrs = match[1], id = attrs.match(/id="([^"]+)"/)[1], form = nodes[id]; forms.push(form);
    form.dataset = Object.fromEntries([...attrs.matchAll(/data-([a-z-]+)="([^"]*)"/g)].map(m => [m[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase()), m[2]]));
    form.elements = {}; form.events = {};
    form.addEventListener = (type, fn) => { form.events[type] = fn; };
    form.querySelectorAll = () => Object.values(form.elements);
    for (const control of match[2].matchAll(/<(input|select)\b([^>]*)>/g)) {
      const name = control[2].match(/\bname="([^"]+)"/)?.[1];
      if (name) form.elements[name] = {value: control[2].match(/\bvalue="([^"]*)"/)?.[1] || "", disabled: false};
    }
    form.submit = () => form.events.submit({preventDefault() {}});
  }
  class FormData {
    constructor(form) { this.values = new Map(Object.entries(form.elements).map(([name, value]) => [name, value.value])); }
    get(name) { return this.values.get(name) ?? null; }
  }
  const location = {href: "unchanged"};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/js", filename), "utf8"), {document: {querySelector: selector => nodes[selector.slice(1)] || null}, FormData, fetch: transport, window: {location}});
  return {nodes, forms, location};
}

(async () => {
  const shelter = await existingForm("/shelters/1/edit", "shelters-form.js");
  shelter.nodes["shelter-form"].elements.name.value = "Updated shelter";
  await shelter.nodes["shelter-form"].submit();
  assert.equal(shelter.nodes["shelter-form-error"].hidden, true);
  let savedShelter = await api("/shelters/1");
  assert.equal(savedShelter.name, "Updated shelter"); assert.equal(savedShelter.target_people, 50);
  const targetForm = shelter.nodes["shelter-targets-form"];
  targetForm.elements.target_people.value = "100"; targetForm.elements.target_days.value = "2";
  await targetForm.submit();
  assert.equal(shelter.nodes["shelter-targets-error"].hidden, true);
  assert.deepEqual(calls.find(c => c.method === "PATCH").body, {name: "Updated shelter", address: "Fictional address"});
  assert.equal((await api("/shelters/1")).target_days, 2);

  const item = await existingForm("/items/3/edit", "items-form.js");
  Object.assign(item.forms[0].elements.is_divisible, {value: "false"});
  await item.forms[0].submit();
  assert.equal(item.nodes["item-form-error"].hidden, true);
  assert.equal((await api("/items/3")).is_divisible, false);

  const html = await (await fetch(base + "/calculation-conditions")).text();
  const h = await harness(transport, html), n = h.nodes;
  const success = () => assert.equal(n["conditions-error"].hidden, true, n["conditions-error"].textContent);
  success(); assert.equal(n["groups-empty"].hidden, false);
  h.set("group-create-form", {name: "Test water demand", calculation_unit: "L", is_divisible: "true", daily_usage: "3", source_text: "Fictional usage", version_or_date: "test-v1", conditions: "Test only"});
  await n["group-create-form"].dispatch("submit"); success();
  for (const [iid, factor] of [["1", "1.00"], ["2", "2.00"]]) {
    await h.selectItem(iid);
    h.set("membership-form", {group_id: "1", factor, source_text: "Fictional conversion", version_or_date: "test-v1", conditions: "Test only"});
    await n["membership-form"].dispatch("submit"); success();
  }
  assert.equal(n["conversion-rows"].children.length, 2);
  assert.match(n["conversion-rows"].children[1].children[0].textContent, /登録終了/);
  const first = await api("/calculations", "POST", {shelter_id: "1"});
  assert.equal(first.header.target_people, 100); assert.equal(first.header.target_days, 2);
  assert.equal(first.groups[0].required_quantity, "600.00"); assert.equal(first.groups[0].included_quantity, "600.00");
  const stored = await api("/calculation-runs", "POST", {calculation_token: first.calculation_token});

  h.set("group-edit-form", {daily_usage: "4"});
  n["conversion-rows"].children[0].children[2].children[0].value = "1.25";
  await n["group-edit-form"].dispatch("submit"); success();
  const changed = await api("/calculations", "POST", {shelter_id: "1"});
  assert.equal(changed.groups[0].required_quantity, "800.00"); assert.equal(changed.groups[0].included_quantity, "750.00");
  assert.equal(changed.groups[0].shortage_quantity, "50.00"); assert.equal(changed.groups[0].coverage_rate, "93.8");
  assert.equal(changed.groups[0].people, 93); assert.equal(changed.groups[0].days, 1);

  const valid = await api("/demand-groups/1/conditions");
  for (const invalid of ["0", "1.234"]) {
    n["conversion-rows"].children[0].children[2].children[0].value = invalid;
    await n["group-edit-form"].dispatch("submit");
    assert.equal(n["conditions-error"].hidden, false); assert.equal(n["conditions-success"].hidden, true);
    assert.equal(n["conversion-rows"].children[0].children[2].children[0].value, invalid);
    assert.deepEqual(await api("/demand-groups/1/conditions"), valid);
  }
  n["conversion-rows"].children[0].children[2].children[0].value = "";
  await n["group-edit-form"].dispatch("submit"); success();
  assert.equal((await api("/demand-groups/1/conditions")).conversions[0].factor, null);
  assert.equal((await api("/calculations", "POST", {shelter_id: "1"})).header.result_state, "unavailable");

  h.set("group-create-form", {name: "Future demand"});
  await n["group-create-form"].dispatch("submit"); success();
  const draft = await api("/demand-groups/2/conditions");
  assert.equal(draft.group.daily_usage, null); assert.equal(draft.group.is_divisible, null);
  await h.selectItem("2");
  h.set("membership-form", {group_id: "2", factor: "", source_text: "", version_or_date: "", conditions: ""});
  await n["membership-form"].dispatch("submit"); success();
  assert.ok(h.confirmations.some(value => /別需要へ移動/.test(value)));
  const moved = await api("/demand-groups/2/conditions");
  assert.equal(moved.conversions[0].item_id, "2"); assert.equal(moved.conversions[0].factor_x100, null);
  assert.equal((await api("/demand-groups/1/conditions")).conversions.length, 1);
  assert.equal((await api("/items/2")).registration_state, "closed");
  assert.deepEqual(await api(`/calculation-runs/${stored.run.run_id}`), stored);
  console.log("P1 UI -> real API -> SQLite: shelter editing, item divisibility, conditions, calculation and frozen saved result passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
