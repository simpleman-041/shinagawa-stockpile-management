const {test} = require("node:test");
const assert = require("node:assert/strict");
const {harness} = require("./helpers/calculation-conditions-harness.cjs");

const group = (id, name) => ({group_id: id, name, calculation_unit: "L", is_divisible: true, daily_usage: "3.00", source_text: "架空出典", version_or_date: "test-v1", conditions: "試験用"});
const conversion = (id, gid, factor) => ({item_id: id, group_id: gid, factor, factor_x100: factor === null ? null : "100", source_text: null, version_or_date: null, conditions: null});
async function setup({empty = false, initiallyOffline = false} = {}) {
  const snapshots = empty ? [] : [
    {group: group("1", "試験需要1"), conversions: [conversion("1", "1", "1.00"), conversion("2", "1", null)]},
    {group: group("2", "試験需要2"), conversions: []},
  ];
  const items = empty ? [] : [{item_id: "1", name: "登録中の品目", quantity_unit: "L", registration_state: "active"}, {item_id: "2", name: "終了品目", quantity_unit: "本", registration_state: "closed"}];
  let offline = initiallyOffline, writeOffline = false, reject = false, failRefresh = false;
  const calls = [];
  const response = (data, status = 200) => ({ok: status < 400, json: async () => structuredClone(data)});
  async function fetch(url, options) {
    calls.push({url, method: options.method, body: options.body && JSON.parse(options.body)});
    if (offline || (writeOffline && options.method !== "GET") || (failRefresh && options.method === "GET")) throw new Error("offline");
    const path = url.split("?")[0];
    if (options.method === "GET" && ["/api/v1/items", "/api/v1/demand-groups"].includes(path)) {
      const values = path.endsWith("items") ? items : snapshots.map(value => value.group);
      const offset = Number(new URL(url, "http://test").searchParams.get("offset"));
      // 一覧を1件ずつ返し、次ページを本当に取得することも検証する。
      return response({data: values.slice(offset, offset + 1), page: {total: values.length}});
    }
    if (options.method === "GET") return response({data: snapshots.find(value => path === `/api/v1/demand-groups/${value.group.group_id}/conditions`)});
    if (reject) return response({error: {message: "入力を修正してください。", fields: [{path: "/conversions/1/factor", message: "小数第2位まで指定してください。"}]}}, 422);
    const body = JSON.parse(options.body);
    if (options.method === "POST") {
      const created = {group_id: String(snapshots.length + 1), ...body}; snapshots.push({group: created, conversions: []});
      return response({data: created}, 201);
    }
    if (path.includes("/demand-groups/")) {
      const value = snapshots.find(value => path === `/api/v1/demand-groups/${value.group.group_id}/conditions`);
      value.group = {group_id: value.group.group_id, ...body.group};
      value.conversions = body.conversions.map(c => ({...c, group_id: value.group.group_id}));
      return response({data: value});
    }
    const iid = path.split("/")[4];
    for (const snapshot of snapshots) snapshot.conversions = snapshot.conversions.filter(c => c.item_id !== iid);
    snapshots.find(value => value.group.group_id === body.group_id).conversions.push({item_id: iid, ...body});
    return response({data: {item_id: iid, ...body}});
  }
  const h = await harness(fetch);
  return {...h, calls, snapshots, setOffline: v => offline = v, setWriteOffline: v => writeOffline = v, setReject: v => reject = v, setFailRefresh: v => failRefresh = v};
}

test("空一覧から需要を画面追加し、空欄をnullのまま保存して計算への影響を確認する", async () => {
  const h = await setup({empty: true}), n = h.nodes;
  assert.equal(n["groups-empty"].hidden, false); assert.equal(n["membership-controls"].disabled, true);
  h.set("group-create-form", {name: "新需要"});
  await n["group-create-form"].dispatch("submit");
  assert.deepEqual(h.calls.find(c => c.method === "POST").body, {name: "新需要", calculation_unit: null, is_divisible: null, daily_usage: null, source_text: null, version_or_date: null, conditions: null});
  assert.match(h.confirmations[0], /全備蓄計算の対象/);
  assert.equal(n["groups-empty"].hidden, true); assert.equal(n["conditions-success"].hidden, false);
  assert.equal(n["condition-group"].value, "1"); assert.equal(n["group-create-form"].elements.name.value, "");
});

test("全所属品目と終了品目を含め、係数・null・分割不可falseを一括送信する", async () => {
  const h = await setup(), n = h.nodes;
  assert.ok(h.calls.some(c => c.url.includes("items?limit=200&offset=1")));
  await h.selectGroup("1");
  assert.equal(n["conversion-rows"].children.length, 2);
  assert.match(n["conversion-rows"].children[1].children[0].textContent, /終了品目.*保持対象/);
  h.set("group-edit-form", {is_divisible: "false", calculation_unit: "本", daily_usage: "4"});
  n["conversion-rows"].children[0].children[2].children[0].value = "1.25";
  await n["group-edit-form"].dispatch("submit");
  const body = h.calls.find(c => c.method === "PUT").body;
  assert.equal(body.group.is_divisible, false);
  assert.equal(body.group.daily_usage, "4");
  assert.deepEqual(body.conversions.map(c => [c.item_id, c.factor]), [["1", "1.25"], ["2", null]]);
  assert.ok(h.confirmations.some(text => /共通単位を変更/.test(text)));
});

test("所属の明示移動は専用PUTだけを使い、終了品目を保持する", async () => {
  const h = await setup(), n = h.nodes;
  await h.selectItem("2");
  assert.match(n["membership-current"].textContent, /試験需要1.*登録終了/);
  h.set("membership-form", {group_id: "2", factor: "2.50", source_text: "換算根拠", version_or_date: "v2", conditions: "移動先単位"});
  await n["membership-group"].dispatch("change");
  await n["membership-form"].dispatch("submit");
  const put = h.calls.find(c => c.method === "PUT");
  assert.equal(put.url, "/api/v1/items/2/conversion");
  assert.deepEqual(put.body, {group_id: "2", factor: "2.50", source_text: "換算根拠", version_or_date: "v2", conditions: "移動先単位"});
  assert.match(h.confirmations.at(-1), /別需要へ移動.*\n現在：試験需要1 → 保存先：試験需要2/);
  assert.equal(n["conversion-rows"].children.length, 1);
  assert.match(n["conversion-rows"].children[0].children[0].textContent, /終了品目/);
});

test("確認キャンセルと422は入力を保持し、0をnullに変換せず、成功を表示しない", async () => {
  const h = await setup(), n = h.nodes; await h.selectGroup("1");
  h.setConfirmed(false); h.set("group-edit-form", {daily_usage: "0"});
  await n["group-edit-form"].dispatch("submit");
  assert.equal(h.calls.filter(c => c.method !== "GET").length, 0);
  h.setConfirmed(true); h.setReject(true);
  n["conversion-rows"].children[1].children[2].children[0].value = "1.234";
  await n["group-edit-form"].dispatch("submit");
  assert.equal(h.calls.at(-1).body.group.daily_usage, "0");
  assert.equal(n["group-edit-form"].elements.daily_usage.value, "0");
  assert.equal(n["conversion-rows"].children[1].children[2].children[0].value, "1.234");
  assert.match(n["conditions-error"].textContent, /終了品目の換算係数/);
  assert.equal(n["conditions-success"].hidden, true);
});

test("取得失敗と更新結果不明では再取得まで保存を止め、POSTを自動再送しない", async () => {
  const h = await setup({initiallyOffline: true}), n = h.nodes;
  assert.equal(n["create-controls"].disabled, true); assert.equal(n["conditions-refresh"].disabled, false);
  h.setOffline(false); await n["conditions-refresh"].dispatch("click");
  h.set("group-create-form", {name: "結果不明の需要"}); h.setWriteOffline(true);
  await n["group-create-form"].dispatch("submit");
  assert.equal(h.calls.filter(c => c.method === "POST").length, 1);
  assert.equal(n["group-create-form"].elements.name.value, "結果不明の需要");
  assert.equal(n["create-controls"].disabled, true);
  assert.match(n["conditions-error"].textContent, /保存結果を確認/);
  h.setWriteOffline(false); await n["conditions-refresh"].dispatch("click");
  assert.equal(n["create-controls"].disabled, false);
  assert.equal(h.calls.filter(c => c.method === "POST").length, 1);
});

test("保存成功後の再取得失敗を更新失敗と混同せず、確認後に再取得できる", async () => {
  const h = await setup(), n = h.nodes; await h.selectGroup("1");
  h.setFailRefresh(true);
  await n["group-edit-form"].dispatch("submit");
  assert.equal(n["conditions-success"].hidden, false);
  assert.match(n["conditions-error"].textContent, /保存は完了しましたが、再取得に失敗/);
  assert.equal(n["group-controls"].disabled, true);
  h.setFailRefresh(false); await n["conditions-refresh"].dispatch("click");
  assert.equal(n["group-controls"].disabled, false);
});
