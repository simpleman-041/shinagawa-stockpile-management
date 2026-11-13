/* 実JSとDOM代替。実ブラウザの描画・操作確認とは別。 */
const {test} = require("node:test"), assert = require("node:assert/strict");
const {harness, response} = require("./helpers/master-ui-harness.cjs");
const item = id => ({item_id: String(id), name: `品目${id}`, category: "物資", quantity_unit: "L", is_divisible: true, near_expiry_days: 10, registration_state: "active"});
for (const [key, plural] of [["warehouse", "warehouses"], ["item", "items"], ["shelter", "shelters"]]) {
  for (const size of [0, 1, 50, 51, 123]) test(`${plural}: ${size}件をページ送りし欠落・重複なく操作できる`, async () => {
    const rows = Array.from({length: size}, (_, i) => ({...item(i + 1), [`${key}_id`]: String(i + 1), address: "架空住所", capacity_m3: null, latitude: null, target_people: null, target_days: null}));
    const h = await harness(key, url => {
      const p = new URL(url, "http://test").searchParams, start = Number(p.get("offset"));
      assert.equal(p.get("limit"), "50");
      return response({data: rows.slice(start, start + 50), page: {total: size, limit: 50, offset: start}});
    });
    const n = h.nodes, seen = [];
    do {
      for (const row of n[`${key}-table-body`].children) seen.push(row.children[0].textContent);
      if (n[`${key}-next`].disabled) break;
      await n[`${key}-next`].dispatch("click");
    } while (true);
    assert.deepEqual(seen, rows.map(r => r.name));
    assert.match(n[`${key}-count`].textContent, new RegExp(`^${size}件`));
    if (size > 50) {
      const action = n[`${key}-table-body`].children[0].children.at(-1).children.find(x => x.tag === "a");
      assert.match(action.href, new RegExp(`/${plural}/101/edit|/${plural}/51/edit`));
      await n[`${key}-previous`].dispatch("click");
      assert.equal(new URL(h.calls.at(-1).url, "http://test").searchParams.get("offset"), size > 100 ? "50" : "0");
    }
  });
  test(`${plural}: 検索は先頭へ戻りページ間で確定済み条件を保持する`, async () => {
    const h = await harness(key, url => { const p = new URL(url, "http://test").searchParams; return response({data: [item(1)], page: {total: 101, limit: 50, offset: Number(p.get("offset"))}}); });
    const n = h.nodes; n[`${key}-query`].value = "一致";
    await n[`${key}-search-form`].dispatch("submit");
    n[`${key}-query`].value = "未検索";
    await n[`${key}-next`].dispatch("click");
    assert.equal(new URL(h.calls.at(-1).url, "http://test").searchParams.get("q"), "一致");
    await n[`${key}-search-form`].dispatch("submit");
    const p = new URL(h.calls.at(-1).url, "http://test").searchParams;
    assert.equal(p.get("offset"), "0"); assert.equal(p.get("q"), "未検索");
  });
  test(`${plural}: 検索に失敗した条件をページ送りへ混入しない`, async () => {
    let fail = false;
    const h = await harness(key, () => { if (fail) throw Error("offline"); return response({data: [item(1)], page: {total: 101}}); });
    h.nodes[`${key}-query`].value = "失敗条件"; fail = true;
    await h.nodes[`${key}-search-form`].dispatch("submit");
    assert.equal(h.nodes[`${key}-error`].hidden, false);
    fail = false; await h.nodes[`${key}-next`].dispatch("click");
    assert.equal(new URL(h.calls.at(-1).url, "http://test").searchParams.has("q"), false);
  });
}

test("倉庫フォーム: 項目別・業務エラー、入力保持、成功時クリア、二重送信防止", async () => {
  let done, reject = true;
  const h = await harness("warehouse", async () => {
    if (reject) return response({error: {message: "入力を確認してください。", fields: [{path: "/name", message: "名称を指定してください。"}]}}, 422);
    await new Promise(resolve => done = resolve); return response({data: {warehouse_id: "1"}}, 201);
  }, true);
  const n = h.nodes, f = n["warehouse-form"];
  await f.dispatch("submit");
  assert.equal(n["warehouse-error-name"].textContent, "名称を指定してください。");
  assert.equal(f.elements.name.value, "架空倉庫"); assert.equal(h.location.href, "unchanged");
  reject = false; const saving = f.dispatch("submit"); await h.settle(); await f.dispatch("submit");
  assert.equal(h.calls.length, 2); done(); await saving;
  assert.equal(n["warehouse-form-error"].hidden, true); assert.equal(n["warehouse-error-name"].hidden, true);
  assert.equal(h.location.href, "/warehouses");
});

for (const kind of ["offline", "server", "invalid-json"]) test(`倉庫フォーム: ${kind}を安全に表示し入力を保持`, async () => {
  const h = await harness("warehouse", () => {
    if (kind === "offline") throw Error("private stack");
    if (kind === "invalid-json") return {ok: false, json: async () => { throw Error("SQL trace"); }};
    return response({error: {message: "private stack", fields: [{path: "/name", message: "SQL trace"}]}}, 500);
  }, true);
  await h.nodes["warehouse-form"].dispatch("submit");
  const message = h.nodes["warehouse-form-error"].textContent;
  assert.match(message, /確認/); assert.doesNotMatch(message, /private|SQL/);
  assert.equal(h.nodes["warehouse-form"].elements.name.value, "架空倉庫");
});

function closeButton(h) { return h.nodes["item-table-body"].children[0].children.at(-1).children.find(n => n.tag === "button"); }

test("倉庫容量は入力文字列のまま送り、座標だけを数値へ変換する", async () => {
  const h = await harness("warehouse", (_url, options) => {
    const values = JSON.parse(options.body);
    assert.equal(values.capacity_m3, "9007199254740993.01"); assert.equal(values.latitude, 35.123456);
    return response({error: {message: "保存できない値です。", fields: [{path: "/capacity_m3", message: "精度を確認してください。"}]}}, 422);
  }, true);
  h.nodes["warehouse-form"].elements.capacity_m3.value = "9007199254740993.01";
  h.nodes["warehouse-form"].elements.latitude.value = "35.123456";
  await h.nodes["warehouse-form"].dispatch("submit");
  assert.match(h.nodes["warehouse-error-capacity_m3"].textContent, /精度/);
});
for (const state of ["active", "unavailable"]) test(`品目終了: 通信断後の状態${state}を再確認しPOSTを自動再送しない`, async () => {
  const h = await harness("item", (url, options) => {
    if (options?.method === "POST") throw Error("offline");
    if (/\/items\/1$/.test(url)) { if (state === "unavailable") throw Error("offline"); return response({data: {...item(1), registration_state: state}}); }
    return response({data: state === "closed" ? [] : [item(1)], page: {total: state === "closed" ? 0 : 1}});
  });
  await closeButton(h).dispatch("click");
  assert.equal(h.calls.filter(c => c.options?.method === "POST").length, 1);
  assert.equal(h.calls.filter(c => /\/items\/1$/.test(c.url)).length, 1);
  assert.match(h.nodes["item-error"].textContent, state === "active" ? /登録中/ : /結果は不明/);
  assert.equal(closeButton(h).disabled, state === "unavailable");
});

for (const lost of [false, true]) test(`品目終了: ${lost ? "応答喪失から終了済みを確認" : "正常終了"}、二重操作防止`, async () => {
  let closed = false, release;
  const h = await harness("item", async (url, options) => {
    if (options?.method === "POST") { await new Promise(r => release = r); closed = true; if (lost) throw Error("lost"); return response({data: {...item(1), registration_state: "closed"}}); }
    if (/\/items\/1$/.test(url)) return response({data: {...item(1), registration_state: "closed"}});
    return response({data: [{...item(1), registration_state: closed ? "closed" : "active"}], page: {total: 1}});
  });
  const button = closeButton(h), pending = button.dispatch("click"); await h.settle(); await button.dispatch("click");
  assert.equal(h.calls.filter(c => c.options?.method === "POST").length, 1);
  release(); await pending; assert.equal(closeButton(h), undefined);
  if (lost) assert.match(h.nodes["item-error"].textContent, /登録終了済み/);
});

for (const kind of ["server", "invalid-json", "timeout", "validation"]) test(`品目終了: ${kind}の通知と再試行`, async () => {
  let failed = true, posts = 0;
  const h = await harness("item", (url, options) => {
    if (options?.method === "POST") {
      posts++;
      if (!failed) return response({data: {...item(1), registration_state: "closed"}});
      if (kind === "validation") return response({error: {message: "対象品目を確認してください。"}}, 422);
      if (kind === "server") return response({error: {message: "SQL private trace"}}, 500);
      if (kind === "invalid-json") return {ok: true, status: 200, json: async () => { throw Error("invalid"); }};
      return new Promise((_, reject) => options.signal.addEventListener("abort", () => reject(Error("timeout"))));
    }
    if (/\/items\/1$/.test(url)) return response({data: item(1)});
    return response({data: [item(1)], page: {total: 1}});
  }, false, {setTimeout: (fn, delay) => { assert.equal(delay, 15000); return setTimeout(fn, 0); }});
  await closeButton(h).dispatch("click");
  assert.equal(posts, 1); assert.equal(h.nodes["item-error"].hidden, false);
  assert.doesNotMatch(h.nodes["item-error"].textContent, /SQL|private/);
  assert.equal(closeButton(h).disabled, false);
  failed = false; await closeButton(h).dispatch("click"); assert.equal(posts, 2);
});

test("品目終了: 結果不明の間は再送せず、手動再取得で操作を復旧する", async () => {
  let online = false, posts = 0;
  const h = await harness("item", (url, options) => {
    if (options?.method === "POST") { posts++; throw Error("lost"); }
    if (/\/items\/1$/.test(url)) { if (!online) throw Error("offline"); return response({data: item(1)}); }
    return response({data: [item(1)], page: {total: 1}});
  });
  await closeButton(h).dispatch("click");
  await closeButton(h).dispatch("click"); assert.equal(posts, 1);
  assert.equal(h.nodes["item-recheck"].hidden, false);
  online = true; await h.nodes["item-recheck"].dispatch("click");
  assert.equal(closeButton(h).disabled, false); assert.equal(h.nodes["item-recheck"].hidden, true);
});

test("品目終了: 終了確認後に一覧取得が失敗しても、古いボタンから再処理しない", async () => {
  let closed = false, posts = 0;
  const h = await harness("item", (url, options) => {
    if (options?.method === "POST") { posts++; closed = true; return response({data: {...item(1), registration_state: "closed"}}); }
    if (closed) throw Error("offline");
    return response({data: [item(1)], page: {total: 1}});
  });
  const button = closeButton(h);
  await button.dispatch("click"); await button.dispatch("click");
  assert.equal(posts, 1); assert.equal(button.disabled, true);
  assert.equal(h.nodes["item-error"].hidden, false);
});
