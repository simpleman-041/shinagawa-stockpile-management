/* 実JS→実Flask→正本DDLの隔離SQLite。描画はDOM代替。 */
const assert = require("node:assert/strict");
const {harness: thresholds} = require("./helpers/threshold-ui-harness.cjs");
const {harness: masters} = require("./helpers/master-ui-harness.cjs");
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || "")) throw Error("専用テストサーバーURLが必要です。");
const calls = [];
async function transport(url, options) { calls.push({url, method: options?.method || "GET"}); return fetch(base + url, options); }
(async () => {
  for (const [key, plural] of [["warehouse", "warehouses"], ["item", "items"], ["shelter", "shelters"]]) {
    const h = await masters(key, transport), n = h.nodes, names = [];
    do {
      names.push(...n[`${key}-table-body`].children.map(row => row.children[0].textContent));
      if (n[`${key}-next`].disabled) break;
      await n[`${key}-next`].dispatch("click");
    } while (true);
    assert.equal(names.length, 206); assert.equal(new Set(names).size, 206);
    assert.match(n[`${key}-count`].textContent, /206件.*201〜206/);
    assert.ok(n[`${key}-table-body`].children[0].children.at(-1).children.some(a => a.href === `/${plural}/201/edit`));
  }
  const html = await (await fetch(base + "/warehouses/1")).text();
  assert.match(html, /threshold-form/);
  const h = await thresholds(transport, html), n = h.nodes;
  assert.equal(n["threshold-item"].children.length, 206);
  assert.match(n["threshold-current"].textContent, /未設定/);
  for (const [value, warning] of [["11.23", "基準未満"], ["0", "基準以上"]]) {
    n["threshold-value"].value = value;
    await n["threshold-form"].dispatch("submit");
    assert.equal(n["threshold-error"].hidden, true, n["threshold-error"].textContent);
    assert.equal(n["threshold-success"].hidden, false);
    assert.match(n["threshold-warning"].textContent, new RegExp(warning));
  }
  n["threshold-value"].value = "1.234"; await n["threshold-form"].dispatch("submit");
  assert.match(n["threshold-value-error"].textContent, /小数第2位/);
  assert.equal(n["threshold-value"].value, "1.234");
  const w = await masters("warehouse", transport, true);
  w.nodes["warehouse-form"].dataset = {mode: "edit", warehouseId: "1"};
  w.nodes["warehouse-form"].elements.capacity_m3.value = "100.23";
  await w.nodes["warehouse-form"].dispatch("submit");
  assert.equal(w.nodes["warehouse-form-error"].hidden, true);
  const warehouse = (await (await fetch(base + "/api/v1/warehouses/1")).json()).data;
  assert.equal(warehouse.capacity_m3, "100.23"); assert.equal(warehouse.warehouse_id, "1");
  assert.equal(calls.filter(c => c.method === "PUT").length, 3);
  process.stdout.write("P2 real HTTP UI flow passed\n");
})().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
