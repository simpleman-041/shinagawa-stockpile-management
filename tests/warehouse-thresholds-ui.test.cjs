/* 実JSの状態遷移をDOM代替で検証。実ブラウザの描画とは別。 */
const {test} = require("node:test"), assert = require("node:assert/strict");
const {harness} = require("./helpers/threshold-ui-harness.cjs"), {response} = require("./helpers/master-ui-harness.cjs");
async function setup(size = 2) {
  let offline = false, reject = false, failRead = false, minimum = null, saved = false, hold = null;
  const items = Array.from({length: size}, (_, i) => ({item_id: String(i + 1), name: `物資${i + 1}`, quantity_unit: i ? "個" : "L", is_divisible: !i, registration_state: i ? "closed" : "active"}));
  const h = await harness(async (url, options) => {
    if (offline) throw Error("offline");
    if (options.method === "PUT") {
      if (reject) return response({error: {message: "基準を確認してください。", fields: [{path: "/minimum_quantity", message: "整数を指定してください。"}]}}, 422);
      if (hold) await hold;
      minimum = JSON.parse(options.body).minimum_quantity; saved = true;
      return response({data: {warehouse_id: "1", item_id: url.split("/").at(-1), minimum_quantity: minimum}});
    }
    if (failRead && saved) throw Error("read failure");
    if (url.endsWith("/summary")) return response({data: {items: minimum === null ? [] : [{item_id: "1", daily_usable_quantity: "10.00", below_minimum: Number(minimum) > 10}]}});
    const p = new URL(url, "http://test").searchParams, start = Number(p.get("offset")), limit = Number(p.get("limit"));
    const data = url.startsWith("/api/v1/items?") ? items : minimum === null ? [] : [{warehouse_id: "1", item_id: "1", minimum_quantity: minimum}];
    return response({data: data.slice(start, start + limit), page: {limit, offset: start, total: data.length}});
  });
  return {...h, offline: v => offline = v, reject: v => reject = v, failRead: v => failRead = v, hold: p => hold = p};
}
test("品目全ページ・終了品目・未設定と0・基準未満表示、保存再取得", async () => {
  const h = await setup(401), n = h.nodes;
  assert.equal(n["threshold-item"].children.length, 401);
  assert.match(n["threshold-item"].children.at(-1).textContent, /登録終了/);
  assert.match(n["threshold-current"].textContent, /未設定/); assert.equal(n["threshold-value"].value, "");
  for (const [value, warning] of [["0", "基準以上"], ["11.23", "基準未満"]]) {
    n["threshold-value"].value = value; await n["threshold-form"].dispatch("submit");
    assert.equal(JSON.parse(h.calls.findLast(c => c.options.method === "PUT").options.body).minimum_quantity, value);
    assert.equal(n["threshold-success"].hidden, false); assert.match(n["threshold-warning"].textContent, new RegExp(warning));
    assert.equal(n["threshold-value"].value, value);
  }
  assert.equal(h.calls.filter(c => c.url.startsWith("/api/v1/items?")).length, 3);
  assert.equal(h.calls.filter(c => c.url.includes("/thresholds?")).length, 3);
});
test("0件は入力を無効化し、終了品目の整数単位と対象IDを表示", async () => {
  const empty = await setup(0); assert.equal(empty.nodes["threshold-inputs"].disabled, true); assert.equal(empty.nodes["threshold-empty"].hidden, false);
  const h = await setup(), n = h.nodes;
  n["threshold-item"].value = "2"; await n["threshold-item"].dispatch("change");
  assert.equal(n["threshold-value"].step, "1"); assert.match(n["threshold-current"].textContent, /品目ID 2/);
  await n["threshold-form"].dispatch("submit"); assert.equal(h.calls.filter(c => c.options.method === "PUT").length, 0);
});
test("入力拒否は項目へ表示し、入力保持・再試行・次回成功でエラー消去", async () => {
  const h = await setup(), n = h.nodes; h.reject(true); n["threshold-value"].value = "1.234";
  await n["threshold-form"].dispatch("submit");
  assert.equal(n["threshold-value"].value, "1.234"); assert.match(n["threshold-value-error"].textContent, /整数/);
  assert.equal(n["threshold-save"].disabled, false); assert.equal(n["threshold-success"].hidden, true);
  h.reject(false); n["threshold-value"].value = "1"; await n["threshold-form"].dispatch("submit");
  assert.equal(n["threshold-value-error"].hidden, true); assert.equal(n["threshold-error"].hidden, true);
});
test("二重送信を抑止し、応答喪失は再取得するまで保存しない", async () => {
  const h = await setup(), n = h.nodes;
  let release; h.hold(new Promise(resolve => release = resolve)); n["threshold-value"].value = "5";
  const saving = n["threshold-form"].dispatch("submit"); await new Promise(setImmediate); await n["threshold-form"].dispatch("submit");
  assert.equal(h.calls.filter(c => c.options.method === "PUT").length, 1); release(); await saving;
  h.offline(true); n["threshold-value"].value = "6"; await n["threshold-form"].dispatch("submit");
  assert.equal(n["threshold-value"].value, "6"); assert.equal(n["threshold-save"].disabled, true);
  const count = h.calls.length; await n["threshold-form"].dispatch("submit"); assert.equal(h.calls.length, count);
  h.offline(false); await n["threshold-refresh"].dispatch("click"); assert.equal(n["threshold-value"].value, "5"); assert.equal(n["threshold-save"].disabled, false);
});
test("保存成功後のGET失敗を成功表示せず、再取得と入力破棄取消ができる", async () => {
  const h = await setup(), n = h.nodes; h.failRead(true); n["threshold-value"].value = "7";
  await n["threshold-form"].dispatch("submit");
  assert.match(n["threshold-error"].textContent, /保存済み/); assert.equal(n["threshold-success"].hidden, true); assert.equal(n["threshold-save"].disabled, true);
  await n["threshold-value"].dispatch("input"); h.setConfirmed(false); const count = h.calls.length;
  await n["threshold-refresh"].dispatch("click"); assert.equal(h.calls.length, count);
  n["threshold-item"].value = "2"; await n["threshold-item"].dispatch("change"); assert.equal(n["threshold-item"].value, "1"); assert.equal(n["threshold-value"].value, "7");
  h.setConfirmed(true); h.failRead(false); await n["threshold-refresh"].dispatch("click"); assert.equal(n["threshold-save"].disabled, false);
});
