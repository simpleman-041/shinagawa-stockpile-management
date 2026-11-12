/* 倉庫対応・割当の保存後に現在値を取得し、通信失敗時は入力を保持する。 */
"use strict";
(async () => {
  const element = (id) => document.getElementById(id);
  const shelterId = document.body.dataset.shelterId;
  const root = `/api/v1/shelters/${shelterId}`;
  const modes = { dedicated: "専用", shared: "共有" };
  const expiry = { dated: "期限あり", none: "期限不要", unconfirmed: "期限未確認", expired: "期限切れ", near: "期限接近", valid: "期限内" };
  let warehouses = [], shelters = [], items = [], groups = [], snapshots = [], current;
  let ready = false, busy = false, offset = 0, total = 0, warehouseFilter = "";
  for (const form of document.querySelectorAll("form")) form.addEventListener("submit", (event) => event.preventDefault());

  function showError(error) {
    element("settings-error").textContent = error.message;
    element("settings-error").hidden = false;
    element("settings-error").scrollIntoView({ block: "nearest" });
  }
  async function api(url, method = "GET", values) {
    let response;
    try {
      response = await fetch(url, { method, headers: values ? { "Content-Type": "application/json" } : {}, body: values ? JSON.stringify(values) : undefined });
    } catch {
      throw new Error("通信に失敗しました。入力は保持しています。現在の設定・割当を再取得し、保存結果を確認してから再操作してください。");
    }
    let result;
    try { result = await response.json(); } catch { throw new Error("応答を読み取れません。再取得して保存結果を確認してください。"); }
    if (!response.ok) {
      const fields = (result.error?.fields || []).map((field) => field.message).join(" ");
      throw new Error(`${result.error?.message || "操作に失敗しました。"} ${fields}`);
    }
    return result;
  }
  async function all(resource) {
    const values = [];
    let result;
    do {
      result = await api(`/api/v1/${resource}?limit=200&offset=${values.length}`);
      values.push(...result.data);
    } while (values.length < result.page.total);
    return values;
  }
  function option(select, value, text) {
    const node = document.createElement("option"); node.value = value; node.textContent = text; select.append(node);
  }
  function warehouseName(id) { return warehouses.find((w) => String(w.warehouse_id) === String(id))?.name || id; }
  function shelterName(id) { return shelters.find((s) => String(s.shelter_id) === String(id))?.name || id; }
  function selectWarehouse() {
    const form = element("warehouse-setting-form");
    const id = form.elements.warehouse_id.value;
    const warehouse = warehouses.find((w) => String(w.warehouse_id) === id);
    const links = snapshots.flatMap((snapshot) => snapshot.links).filter((link) => link.warehouse_id === id);
    const targetIds = new Set(links.map((link) => link.shelter_id));
    form.elements.allocation_mode.value = warehouse?.allocation_mode || "";
    form.elements.confirmed.checked = false;
    element("warehouse-current").textContent = warehouse ? `現在 ${modes[warehouse.allocation_mode] || "区分未設定"} ／ 対応先 ${[...targetIds].map(shelterName).join("、") || "なし"}` : "";
    const choices = element("target-shelters"); choices.replaceChildren();
    const legend = document.createElement("legend"); legend.textContent = "変更後の対応避難所（全件）"; choices.append(legend);
    for (const shelter of shelters) {
      const label = document.createElement("label"), input = document.createElement("input");
      input.type = "checkbox"; input.value = String(shelter.shelter_id); input.checked = targetIds.has(input.value);
      label.append(input, document.createTextNode(`${shelter.name}（ID ${shelter.shelter_id}）`)); choices.append(label);
    }
  }
  function renderSettings() {
    element("setup-state").textContent = `設定状態 ${current.shelter.setup_state === "complete" ? "完了" : "設定中"}`;
    element("setup-form").elements.setup_state.value = current.shelter.setup_state;
    element("setup-form").elements.confirmed.checked = false;
    const container = element("warehouse-links"); container.replaceChildren();
    if (!current.warehouses.length) container.textContent = "対応倉庫はありません。";
    for (const warehouse of current.warehouses) {
      const p = document.createElement("p");
      const names = current.links.filter((link) => link.warehouse_id === warehouse.warehouse_id).map((link) => shelterName(link.shelter_id));
      p.textContent = `${warehouse.name}（${modes[warehouse.allocation_mode] || "区分未設定"}）／ 全対応先 ${names.join("、")}`;
      const link = document.createElement("a"); link.href = `/stocks?warehouse_id=${warehouse.warehouse_id}`; link.textContent = " 在庫を見る"; p.append(link); container.append(p);
    }
    const issues = element("settings-issues"); issues.replaceChildren();
    if (!groups.length) {
      const li = document.createElement("li");
      li.textContent = "需要基準が未登録です。備蓄計算には需要・使用量・品目換算の設定が必要です。"; issues.append(li);
    }
    for (const value of current.issues) {
      const contexts = value.paths.map((path) => {
        const match = path.match(/^\/(warehouses|stocks|demand_groups|item_conversions)\/(\d+)/);
        if (!match) return "";
        if (match[1] === "warehouses") return warehouseName(match[2]);
        if (match[1] === "stocks") return `在庫ID ${match[2]}`;
        if (match[1] === "demand_groups") return `需要ID ${match[2]}`;
        return items.find((item) => item.item_id === match[2])?.name || `品目ID ${match[2]}`;
      }).filter(Boolean);
      const li = document.createElement("li");
      li.textContent = `${value.message} ${[...new Set(contexts)].join("、")}`; issues.append(li);
    }
    if (!current.issues.length && groups.length) { const li = document.createElement("li"); li.textContent = "倉庫対応・割当の矛盾は検出されていません。"; issues.append(li); }
    const selector = element("settings-warehouse"), selected = selector.value;
    selector.replaceChildren(); option(selector, "", "選択してください");
    for (const warehouse of warehouses) option(selector, String(warehouse.warehouse_id), `${warehouse.name}（ID ${warehouse.warehouse_id}）`);
    selector.value = selected;
    selectWarehouse();
    const filter = element("allocation-warehouse"); filter.replaceChildren(); option(filter, "", "すべて");
    for (const warehouse of current.warehouses.filter((w) => w.allocation_mode === "shared")) option(filter, warehouse.warehouse_id, warehouse.name);
    filter.value = warehouseFilter;
    if (!filter.value) warehouseFilter = "";
  }
  async function loadAllocations() {
    const query = new URLSearchParams({ limit: "20", offset: String(offset) });
    if (warehouseFilter) query.set("warehouse_id", warehouseFilter);
    const result = await api(`${root}/allocations?${query}`);
    total = result.page.total;
    const rows = element("allocation-rows"); rows.replaceChildren();
    element("allocation-empty").hidden = result.data.length !== 0;
    element("allocation-count").textContent = `${total}件中 ${offset + (result.data.length ? 1 : 0)}〜${offset + result.data.length}件`;
    for (const candidate of result.data) {
      const view = candidate.stock, stock = view.stock, row = document.createElement("tr");
      for (const text of [`在庫ID ${stock.stock_id} ／ ${warehouseName(stock.warehouse_id)}`, `${view.item_name} ／ ${stock.location}`,
        `${stock.expiry_date || expiry[stock.expiry_state]} ／ ${expiry[view.expiry_status]}`, `${stock.quantity} ${view.quantity_unit}`, view.allocated_total, view.unallocated_quantity]) {
        const td = document.createElement("td"); td.textContent = text; row.append(td);
      }
      const cell = document.createElement("td"), form = document.createElement("form"), label = document.createElement("label");
      const input = document.createElement("input"), button = document.createElement("button");
      input.name = "quantity"; input.inputMode = "decimal"; input.required = true; input.value = candidate.selected_allocation;
      label.textContent = `割当数量（${view.quantity_unit}）`; label.append(input);
      const hint = document.createElement("small");
      hint.textContent = items.find((i) => i.item_id === stock.item_id)?.is_divisible ? "小数第2位まで" : "整数のみ";
      button.textContent = "割当を保存"; form.append(label, hint, button); cell.append(form); row.append(cell); rows.append(row);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        void action(async () => {
          await api(`${root}/allocations/${stock.stock_id}`, "PUT", { quantity: input.value });
          saved("割当を保存しました。"); await load();
        });
      });
    }
  }
  function saved(message) { element("settings-success").textContent = message; element("settings-success").hidden = false; }
  async function load() {
    const data = await Promise.all([all("warehouses"), all("shelters"), all("items"), all("demand-groups")]);
    const states = await Promise.all(data[1].map((shelter) => api(`/api/v1/shelters/${shelter.shelter_id}/warehouse-settings`)));
    [warehouses, shelters, items, groups] = data;
    snapshots = states.map((result) => result.data);
    current = snapshots.find((snapshot) => snapshot.shelter.shelter_id === shelterId);
    if (!current) throw new Error("対象の避難所が見つかりません。");
    renderSettings(); await loadAllocations(); ready = true;
  }
  async function action(operation) {
    if (busy) return;
    busy = true; element("settings-error").hidden = true; element("settings-success").hidden = true;
    element("settings-loading").hidden = false;
    for (const node of document.querySelectorAll("button, [data-controls]")) node.disabled = true;
    try { await operation(); } catch (error) { showError(error); }
    finally {
      busy = false; element("settings-loading").hidden = true;
      for (const node of document.querySelectorAll("button")) node.disabled = false;
      for (const node of document.querySelectorAll("[data-controls]")) node.disabled = !ready;
      element("allocation-previous").disabled = !ready || offset === 0;
      element("allocation-next").disabled = !ready || offset + 20 >= total;
    }
  }
  element("settings-warehouse").addEventListener("change", selectWarehouse);
  element("settings-refresh").addEventListener("click", () => { void action(load); });
  element("warehouse-setting-form").addEventListener("submit", (event) => {
    event.preventDefault(); const form = event.currentTarget;
    const targets = [...element("target-shelters").querySelectorAll("input:checked")].map((input) => input.value);
    void action(async () => {
      if (!form.elements.confirmed.checked) throw new Error("区分と全対応先を確認してください。");
      const result = await api(`${root}/warehouse-settings/warehouses/${form.elements.warehouse_id.value}`, "PUT", {
        allocation_mode: form.elements.allocation_mode.value, shelter_ids: targets });
      saved(`倉庫の設定を保存しました。影響する避難所 ${result.data.affected_shelters.map((s) => s.name).join("、") || "なし"}`);
      offset = 0; await load();
    });
  });
  element("setup-form").addEventListener("submit", (event) => {
    event.preventDefault(); const form = event.currentTarget;
    void action(async () => {
      if (!form.elements.confirmed.checked) throw new Error("現在の設定・確認事項を確認してください。");
      await api(`${root}/warehouse-setup`, "PUT", { setup_state: form.elements.setup_state.value });
      saved("設定状態を保存しました。"); await load();
    });
  });
  element("allocation-filter").addEventListener("submit", (event) => {
    event.preventDefault(); warehouseFilter = element("allocation-warehouse").value; offset = 0;
    void action(loadAllocations);
  });
  for (const [id, difference] of [["allocation-previous", -20], ["allocation-next", 20]]) element(id).addEventListener("click", () => {
    void action(async () => { const previous = offset; offset += difference; try { await loadAllocations(); } catch (error) { offset = previous; throw error; } });
  });
  await action(load);
})();
