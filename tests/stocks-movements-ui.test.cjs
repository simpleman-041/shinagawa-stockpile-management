/* Nodeで実際のstocks.jsを実行し、通信失敗・入力保持・登録・取消・期間検索を確認する。
   DOMの代替を使うため、実ブラウザの描画・操作確認とは別の検証。 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Element {
  constructor(tag = "div") {
    this.tag = tag; this.children = []; this.listeners = {}; this.elements = {};
    this.dataset = {}; this.options = []; this.value = ""; this.defaultValue = "";
    this.hidden = false; this.disabled = false; this.checked = false; this.open = false;
  }
  append(...nodes) { this.children.push(...nodes); if (this.tag === "select") this.options.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  async dispatch(type) { for (const fn of this.listeners[type] || []) await fn({ preventDefault() {} }); }
  querySelectorAll(selector) { return selector === "button" ? [this.button ??= new Element("button")] : []; }
  scrollIntoView() {}
  reset() { for (const field of Object.values(this.elements)) { field.value = field.defaultValue; field.checked = false; } }
  showModal() { this.open = true; }
  close() { this.open = false; for (const fn of this.listeners.close || []) fn(); }
}

async function harness() {
  const template = fs.readFileSync(path.join(__dirname, "../app/templates/stocks.html"), "utf8");
  const nodes = Object.fromEntries([...template.matchAll(/\bid="([^"]+)"/g)].map((m) => [m[1], new Element()]));
  const selects = [], checkboxes = [], forms = [];
  for (const match of template.matchAll(/<form\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/form>/g)) {
    const form = nodes[match[1]]; forms.push(form);
    for (const field of match[2].matchAll(/<(input|select)\b([^>]*)>([\s\S]*?)(?=<\/(?:select)>|<label|$)/g)) {
      const name = /\bname="([^"]+)"/.exec(field[2])?.[1];
      if (!name) continue;
      const node = new Element(field[1]);
      if (field[1] === "select") {
        for (const option of field[3].matchAll(/<option\b[^>]*value="([^"]*)"/g)) {
          const value = new Element("option"); value.value = option[1]; node.append(value);
        }
        node.value = node.options[0]?.value || "";
        const source = /data-options="([^"]+)"/.exec(field[2])?.[1];
        if (source) { node.dataset.options = source; selects.push(node); }
      } else node.value = /\bvalue="([^"]*)"/.exec(field[2])?.[1] || "";
      if (/type="checkbox"/.test(field[2])) checkboxes.push(node);
      node.defaultValue = node.value; form.elements[name] = node;
    }
  }
  // inputはvoid要素なので、selectと独立して拾う。
  for (const match of template.matchAll(/<form\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/form>/g)) {
    for (const field of match[2].matchAll(/<input\b([^>]*)>/g)) {
      const name = /\bname="([^"]+)"/.exec(field[1])?.[1];
      if (name && !nodes[match[1]].elements[name]) nodes[match[1]].elements[name] = new Element("input");
    }
  }
  let quantity = 10, offline = false, reject = false;
  const history = [], calls = [];
  const stock = () => ({ stock: { stock_id: "1", warehouse_id: "1", item_id: "1", location: "棚A", quantity: String(quantity),
      state: "active", expiry_state: "none", expiry_date: null, merge_generation: 0 },
    item_name: "検証品目", quantity_unit: "個", item_registration_state: "active", allocated_total: "0", expiry_status: "none" });
  const response = (data, status = 200) => ({ ok: status < 400, json: async () => data });
  const fetch = async (url, options) => {
    calls.push({ url, options });
    if (offline) throw new Error("offline");
    const target = new URL(url, "http://localhost");
    if (target.pathname === "/api/v1/warehouses") return response({ data: [{ warehouse_id: "1", name: "検証倉庫" }], page: { total: 1 } });
    if (target.pathname === "/api/v1/items") return response({ data: [{ item_id: "1", name: "検証品目", is_divisible: false }], page: { total: 1 } });
    if (target.pathname === "/api/v1/operators") return response({ data: [{ operator_id: "1", name: "検証担当" }], page: { total: 1 } });
    if (target.pathname === "/api/v1/stocks/1") return response({ data: stock() });
    if (/\/(state-events|expiry-changes)$/.test(target.pathname)) return response({ data: [], page: { total: 0 } });
    if (target.pathname === "/api/v1/stocks/1/movements") {
      if (reject) return response({ error: { message: "数量が現在庫を超えます。", fields: [] } }, 409);
      const body = JSON.parse(options.body);
      quantity += (body.kind === "in" ? 1 : -1) * Number(body.quantity);
      const movement = { movement_id: String(history.length + 1), stock_id: "1", kind: body.kind, quantity: body.quantity,
        operator_name: "検証担当", registered_at: "2026-11-12T01:20:30.123Z", state: "active", merge_generation: 0, reason: body.reason };
      history.unshift(movement); return response({ data: { stock: stock(), movement } }, 201);
    }
    if (target.pathname === "/api/v1/stock-movements") return response({ data: [...history], page: { total: history.length } });
    const mid = target.pathname.match(/^\/api\/v1\/stock-movements\/(\d+)(\/cancellation)?$/);
    if (mid) {
      const movement = history.find((m) => m.movement_id === mid[1]);
      if (mid[2]) { movement.state = "cancelled"; movement.cancel_operator_name = "検証担当"; quantity -= Number(movement.quantity); }
      return response({ data: mid[2] ? { stock: stock(), movement } : movement });
    }
    throw new Error("Unexpected request " + url);
  };
  const context = { document: { body: { dataset: { mode: "detail", stockId: "1" } }, getElementById: (id) => nodes[id],
      createElement: (tag) => new Element(tag), querySelectorAll: (selector) => selector === "form" ? forms : selector === "[data-options]" ? selects : checkboxes },
    fetch, URLSearchParams, location: { search: "" }, FormData: class {
      constructor(form) { this.form = form; }
      *[Symbol.iterator]() { for (const [key, value] of Object.entries(this.form.elements)) yield [key, value.value]; }
    } };
  const promise = vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/js/stocks.js"), "utf8"), context);
  await promise;
  assert.equal(nodes.error.textContent, undefined, "初期化に失敗していないこと");
  return { nodes, calls, history, setOffline: (value) => { offline = value; }, setReject: (value) => { reject = value; } };
}

test("入出庫の空履歴、重要拒否・通信失敗時の入力保持、登録と確認付き取消", async () => {
  const h = await harness(), n = h.nodes, form = n["movement-form"];
  assert.equal(n["movement-empty"].hidden, false);
  form.elements.quantity.value = "3"; form.elements.operator_id.value = "1"; form.elements.reason.value = "補充";
  h.setReject(true); await form.dispatch("submit");
  assert.match(n.error.textContent, /数量が現在庫/);
  assert.equal(form.elements.quantity.value, "3"); assert.equal(form.elements.reason.value, "補充");
  h.setReject(false); h.setOffline(true);
  const before = h.calls.length;
  await form.dispatch("submit");
  assert.match(n.error.textContent, /通信に失敗/);
  assert.equal(h.calls.length, before + 1, "POSTを自動再送しない");
  assert.equal(form.elements.quantity.value, "3");
  h.setOffline(false); await n["refresh-stock"].dispatch("click");
  assert.equal(form.elements.quantity.value, "3", "結果確認の再取得でも未送信入力を保持");
  await form.dispatch("submit");
  assert.equal(form.elements.quantity.value, "");
  assert.match(n.success.textContent, /入庫を登録しました/);
  assert.equal(h.history.length, 1);
  assert.match(n["movement-rows"].children[0].children[1].textContent, /2026\/11\/12.*10:20:30\.123/);
  await n["movement-rows"].children[0].children[7].children[0].dispatch("click");
  assert.equal(n["cancellation-dialog"].open, true);
  n["cancellation-form"].elements.operator_id.value = "1";
  n["cancellation-form"].elements.confirmed.checked = true;
  await n["cancellation-form"].dispatch("submit");
  assert.equal(n["cancellation-dialog"].open, false);
  assert.equal(h.history[0].state, "cancelled");
  assert.match(n.success.textContent, /取り消しました/);
});

test("履歴の日本時間を端末に依存せずUTCの半開期間として送る", async () => {
  const h = await harness(), form = h.nodes["movement-search"];
  form.elements.from.value = "2026-11-12T10:20:30.123";
  form.elements.to.value = "2026-11-13T10:20";
  await form.dispatch("submit");
  const url = new URL(h.calls.at(-1).url, "http://localhost");
  assert.equal(url.searchParams.get("stock_id"), "1");
  assert.equal(url.searchParams.get("from"), "2026-11-12T01:20:30.123Z");
  assert.equal(url.searchParams.get("to"), "2026-11-13T01:20:00.000Z");
});
