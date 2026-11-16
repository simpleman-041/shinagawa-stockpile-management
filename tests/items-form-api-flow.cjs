/* Real script, rendered form, Flask HTTP and isolated SQLite; DOM is substituted. */
const assert = require("node:assert/strict");
const {formHarness, item, response} = require("./helpers/items-form-harness.cjs");
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || "")) throw Error("隔離テストサーバーのURLが必要です。");
async function get(url) {
  const r = await fetch(base + url); assert.equal(r.status, 200); return r.json();
}
async function form(options) {
  const url = options.mode === "edit" ? "/items/1/edit" : "/items/new";
  const html = await (await fetch(base + url)).text();
  return formHarness({...options, html});
}
(async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const normal = await form({transport: async (url, options) => { await gate; return fetch(base + url, options); }});
  const pending = normal.submit(); await normal.settle();
  for (let i = 0; i < 5; i++) await normal.submit();
  release(); await pending;
  assert.equal(normal.calls.length, 1); assert.equal(normal.location.href, "/items");
  assert.equal((await get("/api/v1/items")).page.total, 2);

  // Forward and finish the actual write before dropping its response at the client boundary.
  for (const mode of ["create", "edit"]) {
    const h = await form({mode, values: {name: `応答喪失-${mode}`}, transport: async (url, options) => {
      const r = await fetch(base + url, options);
      if (options.method === "POST" || options.method === "PATCH") {
        assert.equal(r.status, mode === "edit" ? 200 : 201); await r.json(); throw Error("saved, response lost");
      }
      return r;
    }});
    await h.submit(); await h.submit();
    assert.equal(h.calls.length, 1); assert.equal(h.location.href, "unchanged");
    assert.match(h.nodes["item-form-error"].textContent, /保存結果は不明/);
    assert.equal(h.form.elements.name.value, `応答喪失-${mode}`);
    if (mode === "edit") {
      await h.recheck();
      assert.equal(h.calls.length, 2);
      assert.equal(h.nodes["item-current-name"].textContent, "応答喪失-edit");
      assert.equal(h.nodes["item-form-submit"].disabled, true);
      assert.equal(h.nodes["item-form-resume"].disabled, false);
    }
    assert.equal(h.calls.filter(c => ["POST", "PATCH"].includes(c.options.method)).length, 1);
  }
  assert.equal((await get("/api/v1/items")).page.total, 3);
  assert.equal((await get("/api/v1/items?q=" + encodeURIComponent("応答喪失-create"))).page.total, 1);

  const offline = await form({transport: () => { throw Error("not forwarded"); }});
  await offline.submit(); await offline.submit();
  assert.equal(offline.calls.length, 1);
  assert.equal((await get("/api/v1/items")).page.total, 3);

  // A 5xx can also be observed after the underlying request has committed.
  const serverError = await form({values: {name: "保存後5xx"}, transport: async (url, options) => {
    const r = await fetch(base + url, options); assert.equal(r.status, 201); await r.json();
    return response({error: {code: "INTERNAL_ERROR", message: "private trace"}}, 500);
  }});
  await serverError.submit(); await serverError.submit();
  assert.equal(serverError.calls.length, 1);
  assert.equal(serverError.nodes["item-form-submit"].disabled, true);
  assert.match(serverError.nodes["item-form-error"].textContent, /保存結果は不明/);
  assert.equal((await get("/api/v1/items")).page.total, 4);
  assert.equal((await get("/api/v1/items/1")).data.name, "応答喪失-edit");
  process.stdout.write("Items form real HTTP: single insert, pre-save disconnect, post-commit response loss, GET confirmation, post-commit 5xx passed\n");
})().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
