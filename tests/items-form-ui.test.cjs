const {test} = require("node:test"), assert = require("node:assert/strict");
const {formHarness, fields, defaults, item, response} = require("./helpers/items-form-harness.cjs");
const refusal = status => response({error: {code: status === 409 ? "UNIT_HAS_STOCK" : "VALIDATION_ERROR", message: "入力と既存在庫を確認してください。", fields: []}}, status);
function retained(h) {
  for (const name of fields) assert.equal(h.form.elements[name].value, defaults[name]);
}
function locked(h) {
  assert.equal(h.nodes["item-form-submit"].disabled, true);
  for (const name of fields) assert.equal(h.form.elements[name].disabled, true);
}

for (const mode of ["create", "edit"]) {
  test(`${mode}: 応答待ちと遷移前のsubmitを1件に抑え、入力の型を維持する`, async () => {
    let release;
    const h = formHarness({mode, transport: () => new Promise(resolve => { release = resolve; })});
    const saving = h.submit(); await h.settle();
    locked(h); assert.equal(h.form.attributes["aria-busy"], "true");
    for (let i = 0; i < 5; i++) await h.submit();
    assert.equal(h.calls.length, 1);
    const request = h.calls[0];
    assert.equal(request.options.method, mode === "edit" ? "PATCH" : "POST");
    assert.equal(request.url, mode === "edit" ? "/api/v1/items/1" : "/api/v1/items");
    assert.deepEqual(JSON.parse(request.options.body), {...defaults, is_divisible: false, near_expiry_days: 180});
    release(response({data: item()}, mode === "edit" ? 200 : 201)); await saving;
    assert.equal(h.location.href, "/items");
    await h.submit(); assert.equal(h.calls.length, 1); locked(h);
  });

  for (const status of [409, 422]) test(`${mode}: ${status}の明確な拒否後は入力を保持し修正・再操作できる`, async () => {
    let reject = true;
    const h = formHarness({mode, transport: () => reject ? refusal(status) : response({data: item()}, mode === "edit" ? 200 : 201)});
    await h.submit(); retained(h);
    assert.equal(h.nodes["item-form-error"].hidden, false);
    assert.match(h.nodes["item-form-error"].textContent, /既存在庫/);
    assert.equal(h.nodes["item-form-recovery"].hidden, true);
    for (const name of fields) assert.equal(h.form.elements[name].disabled, false);
    h.form.elements.name.value = "修正した品目"; reject = false;
    await h.submit(); assert.equal(h.calls.length, 2);
    assert.equal(JSON.parse(h.calls[1].options.body).name, "修正した品目");
    assert.equal(h.nodes["item-form-error"].hidden, true);
    assert.equal(h.location.href, "/items");
  });

  for (const kind of ["offline-before-save", "lost-after-save", "500", "503-retryable", "invalid-json", "invalid-4xx-json", "missing-data", "malformed-item", "wrong-status", "malformed-4xx"]) {
    test(`${mode}: ${kind}は結果不明として保持し自動再送・遷移しない`, async () => {
      let saved = false;
      const h = formHarness({mode, transport: () => {
        if (kind === "offline-before-save") throw Error("private network trace");
        if (kind === "lost-after-save") { saved = true; throw Error("lost response"); }
        if (kind === "500" || kind === "503-retryable") return response({error: {code: "STORAGE_BUSY", message: "private SQL trace", retryable: true}}, kind === "500" ? 500 : 503);
        if (kind.includes("json")) return {ok: kind === "invalid-json", status: kind === "invalid-json" ? 201 : 422, json: async () => { throw Error("private JSON trace"); }};
        if (kind === "missing-data") return response({}, mode === "edit" ? 200 : 201);
        if (kind === "malformed-item") return response({data: item({unit_volume_m3: 0.01})}, mode === "edit" ? 200 : 201);
        if (kind === "wrong-status") return response({data: item()}, 202);
        return response({error: {message: "missing code"}}, 422);
      }});
      await h.submit(); await h.submit(); await h.settle();
      retained(h); locked(h); assert.equal(h.calls.length, 1);
      assert.equal(saved, kind === "lost-after-save");
      assert.equal(h.location.href, "unchanged");
      assert.equal(h.nodes["item-form-recovery"].hidden, false);
      assert.match(h.nodes["item-form-error"].textContent, /保存結果は不明/);
      assert.doesNotMatch(h.nodes["item-form-error"].textContent, /private|SQL|JSON trace/);
      assert.equal(h.form.attributes["aria-busy"], "false");
    });
  }

  for (const stage of ["headers", "body"]) test(`${mode}: ${stage}待ちの15秒タイムアウトでも結果不明を維持`, async () => {
    const timers = {setTimeout: (fn, delay) => { assert.equal(delay, 15000); return setTimeout(fn, 0); }};
    const h = formHarness({mode, timers, transport: (_url, options) => {
      const waiting = new Promise((_, reject) => options.signal.addEventListener("abort", () => reject(Error("timeout"))));
      return stage === "headers" ? waiting : {ok: true, status: mode === "edit" ? 200 : 201, json: () => waiting};
    }});
    await h.submit(); await h.submit(); retained(h); locked(h);
    assert.equal(h.calls.length, 1); assert.equal(h.nodes["item-form-recovery"].hidden, false);
  });
}

test("新規: 一覧確認の説明があり、確認取消は停止維持、承諾は入力を戻すだけでPOSTしない", async () => {
  let accept = false;
  const h = formHarness({transport: () => { throw Error("lost"); }, confirm: () => accept});
  await h.submit(); await h.resume(); locked(h); assert.equal(h.calls.length, 1);
  assert.match(h.confirmations[0], /同名品目.*断定できません/);
  accept = true; await h.resume(); retained(h);
  assert.equal(h.calls.length, 1); assert.equal(h.nodes["item-form-submit"].disabled, false);
  assert.equal(h.nodes["item-form-submit"].focused, true);
  h.form.elements.name.value = "確認して再操作";
  await h.submit(); assert.equal(h.calls.length, 2);
});

for (const kind of ["offline", "404", "500", "invalid-json", "wrong-id", "missing-fields"]) test(`編集: GET ${kind}では再保存を許可せず、再確認で復帰できる`, async () => {
  let available = false;
  const h = formHarness({mode: "edit", transport: (_url, options) => {
    if (options.method === "PATCH") throw Error("lost");
    if (available) return response({data: item({name: "保存済み", unit_volume_m3: null})});
    if (kind === "offline") throw Error("offline");
    if (kind === "invalid-json") return {ok: true, status: 200, json: async () => { throw Error("invalid"); }};
    if (kind === "wrong-id") return response({data: item({item_id: "2"})});
    if (kind === "missing-fields") return response({data: {item_id: "1"}});
    return response({error: {message: "private trace"}}, Number(kind));
  }});
  await h.submit(); await h.resume(); assert.equal(h.confirmations.length, 0);
  await h.recheck(); locked(h); retained(h);
  assert.equal(h.nodes["item-form-resume"].disabled, true);
  assert.match(h.nodes["item-form-status"].textContent, /不明のまま/);
  available = true; await h.recheck();
  assert.equal(h.nodes["item-current-name"].textContent, "保存済み");
  assert.equal(h.nodes["item-current-unit_volume_m3"].textContent, "未設定");
  assert.equal(h.nodes["item-form-resume"].disabled, false);
  locked(h); retained(h);
  assert.equal(h.calls.filter(c => c.options.method === "PATCH").length, 1);
});

test("編集: 確認中のGET重複と保存を止め、一致する取得結果でも成功断定・自動再送しない", async () => {
  let release, accept = false;
  const h = formHarness({mode: "edit", confirm: () => accept, transport: (_url, options) => {
    if (options.method === "PATCH") throw Error("lost");
    return new Promise(resolve => { release = resolve; });
  }});
  await h.submit(); const checking = h.recheck(); await h.settle();
  await h.recheck(); await h.submit(); await h.resume();
  assert.equal(h.calls.length, 2); locked(h);
  assert.equal(h.form.attributes["aria-busy"], "true");
  release(response({data: item()})); await checking;
  assert.equal(h.calls[1].options.cache, "no-store");
  assert.match(h.nodes["item-form-status"].textContent, /成否は断定できません/);
  assert.equal(h.location.href, "unchanged");
  await h.resume(); locked(h);
  accept = true; await h.resume(); assert.equal(h.calls.length, 2);
  assert.equal(h.nodes["item-form-submit"].disabled, false);
  retained(h);
});

for (const volume of ["", "0", "9007199254740993.01"]) test(`送信: 容積 ${JSON.stringify(volume)}はnull/0/文字列精度を保つ`, async () => {
  const h = formHarness({values: {unit_volume_m3: volume}, transport: () => refusal(422)});
  await h.submit(); assert.equal(JSON.parse(h.calls[0].options.body).unit_volume_m3, volume === "" ? null : volume);
});

test("編集: 大きいIDを丸めずGETし、GET失敗で古い確認結果を利用しない", async () => {
  let available = true;
  const identifier = "9007199254740993";
  const h = formHarness({mode: "edit", itemId: identifier, transport: (url, options) => {
    assert.equal(url, `/api/v1/items/${identifier}`);
    if (options.method === "PATCH" || !available) throw Error("offline");
    return response({data: item({item_id: identifier})});
  }});
  await h.submit(); await h.recheck();
  assert.equal(h.nodes["item-form-resume"].disabled, false);
  available = false; await h.recheck(); await h.resume();
  assert.equal(h.nodes["item-form-current"].hidden, true);
  assert.equal(h.nodes["item-form-resume"].disabled, true);
  assert.equal(h.confirmations.length, 0); locked(h);
});
