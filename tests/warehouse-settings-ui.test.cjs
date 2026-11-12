/* 実際の画面スクリプトをDOM代替で実行する。描画・ブラウザ入力制約は別途確認する。 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

async function harness() {
  const allNodes = [];
  class Element {
    constructor(tag = "div") {
      this.tag = tag; this.children = []; this.events = {}; this.elements = {};
      this.value = ""; this.checked = false; this.disabled = false; this.hidden = false;
      allNodes.push(this);
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = [...nodes]; }
    addEventListener(type, fn) { (this.events[type] ??= []).push(fn); }
    scrollIntoView() {}
    querySelectorAll(selector) {
      const nodes = this.children.flatMap((child) => [child, ...child.querySelectorAll("all")]);
      return selector === "input:checked" ? nodes.filter((node) => node.tag === "input" && node.checked) : nodes;
    }
    async dispatch(type) {
      for (const fn of this.events[type] || []) fn({ preventDefault() {}, currentTarget: this });
      await new Promise(setImmediate);
    }
  }
  const template = fs.readFileSync(path.join(__dirname, "../app/templates/warehouse_settings.html"), "utf8");
  const nodes = Object.fromEntries([...template.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  for (const [id, names] of Object.entries({ "warehouse-setting-form": ["warehouse_id", "allocation_mode", "confirmed"], "setup-form": ["setup_state", "confirmed"], "allocation-filter": ["warehouse_id"] })) {
    nodes[id].tag = "form";
    for (const name of names) nodes[id].elements[name] = new Element("input");
  }
  nodes["warehouse-setting-form"].elements.warehouse_id = nodes["settings-warehouse"];
  nodes["allocation-filter"].elements.warehouse_id = nodes["allocation-warehouse"];
  const controls = [new Element("fieldset"), new Element("fieldset")];
  const warehouses = [{ warehouse_id: "1", name: "架空共有倉庫", allocation_mode: "shared" }];
  const shelters = [{ shelter_id: 1, name: "架空避難所1" }, { shelter_id: 2, name: "架空避難所2" }];
  const stock = { stock: { stock_id: "1", warehouse_id: "1", item_id: "1", location: "棚A", quantity: "10", expiry_state: "none", expiry_date: null },
    item_name: "架空物品", quantity_unit: "個", allocated_total: "2", unallocated_quantity: "8", expiry_status: "none" };
  let offline = false, reject = false, allocation = "2", empty = false;
  let targets = ["1", "2"], state = "editing";
  const calls = [];
  function response(data, status = 200) { return { ok: status < 400, json: async () => structuredClone(data) }; }
  const fetch = async (url, options) => {
    calls.push({ url, options });
    if (offline) throw new Error("offline");
    const resource = url.split("?")[0];
    if (resource === "/api/v1/warehouses") return response({ data: warehouses, page: { total: 1 } });
    if (resource === "/api/v1/shelters") return response({ data: shelters, page: { total: 2 } });
    if (resource === "/api/v1/items") return response({ data: [{ item_id: "1", is_divisible: false }], page: { total: 1 } });
    if (resource === "/api/v1/demand-groups") return response({ data: [], page: { total: 0 } });
    if (resource.endsWith("/warehouse-settings")) {
      const id = resource.split("/")[4];
      return response({ data: { shelter: { shelter_id: id, setup_state: state }, warehouses: targets.includes(id) ? warehouses : [],
        links: targets.map((shelter_id) => ({ warehouse_id: "1", shelter_id })), issues: [] } });
    }
    if (resource.endsWith("/allocations")) return response({ data: empty ? [] : [{ stock, selected_allocation: allocation }], page: { total: empty ? 0 : 1 } });
    if (resource.endsWith("/allocations/1")) {
      if (reject) return response({ error: { message: "全避難所の割当合計が現在庫を超えます。" } }, 409);
      allocation = JSON.parse(options.body).quantity;
      return response({ data: {} });
    }
    if (resource.endsWith("/warehouse-settings/warehouses/1")) {
      targets = JSON.parse(options.body).shelter_ids;
      return response({ data: { affected_shelters: shelters } });
    }
    if (resource.endsWith("/warehouse-setup")) { state = JSON.parse(options.body).setup_state; return response({ data: {} }); }
    throw new Error("Unexpected request " + url);
  };
  const document = { body: { dataset: { shelterId: "1" } }, getElementById: (id) => nodes[id],
    createElement: (tag) => new Element(tag), createTextNode: (text) => { const node = new Element(); node.textContent = text; return node; },
    querySelectorAll: (selector) => {
      if (selector === "[data-controls]") return controls;
      if (selector === "button, [data-controls]") return allNodes.filter((node) => node.tag === "button").concat(controls);
      return allNodes.filter((node) => node.tag === selector);
    } };
  await vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/js/warehouse-settings.js"), "utf8"), { document, fetch, URLSearchParams });
  assert.equal(nodes["settings-error"].textContent, undefined);
  return { nodes, calls, setOffline: (value) => { offline = value; }, setReject: (value) => { reject = value; }, setEmpty: () => { empty = true; } };
}

test("割当の拒否と通信失敗は入力を保持し、成功後は現在値を再取得する", async () => {
  const h = await harness(), n = h.nodes;
  assert.match(n["settings-issues"].children[0].textContent, /需要基準が未登録/);
  const cell = n["allocation-rows"].children[0].children[6];
  const form = cell.children[0], input = form.children[0].children[0];
  input.value = "9";
  h.setReject(true); await form.dispatch("submit");
  assert.match(n["settings-error"].textContent, /現在庫を超え/);
  assert.equal(input.value, "9");
  h.setReject(false); h.setOffline(true);
  const count = h.calls.length; await form.dispatch("submit");
  assert.match(n["settings-error"].textContent, /通信に失敗/);
  assert.equal(input.value, "9"); assert.equal(h.calls.length, count + 1);
  h.setOffline(false); await form.dispatch("submit");
  assert.match(n["settings-success"].textContent, /割当を保存/);
  assert.equal(n["allocation-rows"].children[0].children[6].children[0].children[0].children[0].value, "9");
  h.setEmpty(); await n["settings-refresh"].dispatch("click");
  assert.equal(n["allocation-empty"].hidden, false);
});

test("倉庫の全対応先を選択し、確認後に本文へ送信する", async () => {
  const h = await harness(), n = h.nodes, form = n["warehouse-setting-form"];
  n["settings-warehouse"].value = "1";
  await n["settings-warehouse"].dispatch("change");
  const choices = n["target-shelters"].querySelectorAll("input:checked");
  assert.equal(choices.length, 2);
  choices[0].checked = false;
  form.elements.confirmed.checked = true;
  await form.dispatch("submit");
  const sent = h.calls.find((call) => call.options.method === "PUT");
  assert.deepEqual(JSON.parse(sent.options.body), { allocation_mode: "shared", shelter_ids: ["2"] });
  assert.match(n["settings-success"].textContent, /影響する避難所/);
});
