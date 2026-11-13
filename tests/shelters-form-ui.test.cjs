/* Q13/AUD-01。実JSの送信契約と独立した成功／失敗表示をDOM代替で検証する。 */
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");

function harness(mode = "edit", hasTargets = true) {
  class Element {
    constructor() { this.events = {}; this.elements = {}; this.value = ""; this.hidden = true; this.disabled = false; this.dataset = {}; }
    addEventListener(type, fn) { this.events[type] = fn; }
    querySelectorAll() { return Object.values(this.elements); }
    async submit() { await this.events.submit({preventDefault() {}}); }
  }
  const ids = ["shelter-form", "shelter-form-error", "shelter-form-success", "shelter-targets-form", "shelter-targets-error", "shelter-targets-success"];
  const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
  const form = nodes["shelter-form"], targets = nodes["shelter-targets-form"];
  form.dataset = {mode, shelterId: "1"}; targets.dataset.shelterId = "1";
  function field(form, name, value) { form.elements[name] = Object.assign(new Element(), {value}); }
  field(form, "name", "旧名称"); field(form, "address", "旧住所");
  const targetForm = mode === "edit" ? targets : form;
  field(targetForm, "target_people", hasTargets ? "100" : ""); field(targetForm, "target_days", hasTargets ? "2" : "");
  if (mode !== "edit") delete nodes["shelter-targets-form"];
  const calls = [], location = {href: "unchanged"};
  let failing = null, offline = false, brokenJSON = false;
  const fetch = async (url, options) => {
    calls.push({url, method: options.method, body: JSON.parse(options.body)});
    if (offline) throw new Error("offline");
    return {ok: options.method !== failing, json: async () => {
      if (brokenJSON) throw new Error("invalid JSON");
      return options.method === failing ? {error: {message: "今回の保存は失敗しました。"}} : {data: {}};
    }};
  };
  class FormData { constructor(form) { this.form = form; } get(name) { return this.form.elements[name]?.value ?? null; } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/js/shelters-form.js"), "utf8"), {
    document: {querySelector: selector => nodes[selector.slice(1)] || null}, FormData, fetch, window: {location},
  });
  return {nodes, form, targets, calls, location, setFailure: value => failing = value, setOffline: value => offline = value, setBrokenJSON: value => brokenJSON = value};
}

for (const hasTargets of [false, true]) test(`正式目標${hasTargets ? "あり" : "なし"}で通常保存と目標保存を分離する`, async () => {
  const h = harness("edit", hasTargets);
  h.form.elements.name.value = "新名称";
  await h.form.submit();
  assert.deepEqual(h.calls, [{url: "/api/v1/shelters/1", method: "PATCH", body: {name: "新名称", address: "旧住所"}}]);
  assert.equal(h.location.href, "unchanged");
  h.form.elements.address.value = "新住所";
  await h.form.submit();
  assert.deepEqual(h.calls.at(-1).body, {name: "新名称", address: "新住所"});
  h.targets.elements.target_people.value = "120"; h.targets.elements.target_days.value = "3";
  await h.targets.submit();
  assert.deepEqual(h.calls.at(-1), {url: "/api/v1/shelters/1/targets", method: "PUT", body: {target_people: 120, target_days: 3}});
  assert.equal(h.calls.length, 3);
  assert.equal(h.nodes["shelter-form-success"].hidden, false);
  assert.match(h.nodes["shelter-targets-success"].textContent, /120人・3日/);
});

for (const failing of ["PATCH", "PUT"]) test(`${failing}の失敗を別の保存の成功と混同せず、入力を保持する`, async () => {
  const h = harness();
  const failedForm = failing === "PATCH" ? h.form : h.targets;
  const goodForm = failing === "PATCH" ? h.targets : h.form;
  const prefix = failing === "PATCH" ? "shelter-form" : "shelter-targets";
  await goodForm.submit(); h.setFailure(failing);
  await failedForm.submit();
  assert.equal(h.nodes[`${prefix}-success`].hidden, true);
  assert.equal(h.nodes[`${prefix}-error`].hidden, false);
  assert.match(h.nodes[`${prefix}-error`].textContent, /今回の保存は失敗/);
  assert.equal(h.form.elements.name.value, "旧名称"); assert.equal(h.targets.elements.target_people.value, "100");
  assert.equal(h.location.href, "unchanged");
  h.setOffline(true); await failedForm.submit();
  assert.match(h.nodes[`${prefix}-error`].textContent, /保存結果を確認/);
  assert.equal(h.calls.length, 3);
  assert.equal(Object.values(failedForm.elements).some(n => n.disabled), false);
});

test("新規登録は未設定を省略し、不正な目標と読めない応答を保存成功にしない", async () => {
  const h = harness("create", false);
  await h.form.submit();
  assert.deepEqual(h.calls[0], {url: "/api/v1/shelters", method: "POST", body: {name: "旧名称", address: "旧住所"}});
  assert.equal(h.location.href, "/shelters");
  const edit = harness();
  edit.targets.elements.target_days.value = "";
  await edit.targets.submit(); assert.equal(edit.calls.length, 0);
  assert.equal(edit.nodes["shelter-targets-error"].hidden, false);
  edit.targets.elements.target_days.value = "2"; edit.setBrokenJSON(true);
  await edit.targets.submit();
  assert.equal(edit.nodes["shelter-targets-success"].hidden, true);
  assert.match(edit.nodes["shelter-targets-error"].textContent, /保存結果を確認できません/);
});
