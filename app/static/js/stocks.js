/* 在庫APIの成功後に現在値を再取得する。失敗時は入力を保持し、POSTを自動再送しない。 */
"use strict";
(async () => {
  const $ = (id) => document.getElementById(id);
  const mode = document.body.dataset.mode;
  const stockId = document.body.dataset.stockId;
  const root = `/api/v1/stocks/${stockId}`;
  const labels = { active: "有効", deleted: "削除済み", merged: "統合済み", near: "期限接近", valid: "期限内", expired: "期限切れ", none: "期限不要", unconfirmed: "未確認", dated: "期限あり", delete: "削除", restore: "復元" };
  const refs = {};
  // 初期データ取得に失敗しても、通常のフォーム送信で入力を失わせない。
  for (const form of document.querySelectorAll("form")) {
    form.addEventListener("submit", (event) => event.preventDefault());
  }
  let current;
  let token;
  let offset = 0;
  let listGeneration = 0;
  const historyOffsets = { state: 0, expiry: 0 };
  function showError(error) {
    $("error").textContent = error.message;
    $("error").hidden = false;
    $("error").scrollIntoView({ block: "nearest" });
  }
  async function api(path, method = "GET", body) {
    let response;
    try {
      response = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    } catch {
      throw new Error("通信に失敗しました。入力内容は保持しています。更新操作は、結果を確認してから再操作してください。");
    }
    let result;
    try { result = await response.json(); } catch { throw new Error("応答を読み取れません。更新結果を確認してください。"); }
    if (!response.ok) {
      const fields = (result.error?.fields || []).map((field) => `${field.path} ${field.message}`).join(" / ");
      throw new Error(`${result.error?.message || "処理に失敗しました。"} ${fields}`);
    }
    return result;
  }
  async function all(path) {
    const values = [];
    let page;
    do {
      page = await api(`/api/v1/${path}?limit=200&offset=${values.length}`);
      values.push(...page.data);
    } while (values.length < page.page.total);
    return values;
  }
  function rowData(view) {
    const s = view.stock;
    const item = refs.items.find((i) => i.item_id === s.item_id);
    const warehouse = refs.warehouses.find((w) => String(w.warehouse_id) === s.warehouse_id);
    return { "在庫ID": s.stock_id, "品目": view.item_name, "分類": item?.category || "", "倉庫": warehouse?.name || s.warehouse_id,
      "保管場所": s.location, "数量": `${s.quantity} ${view.quantity_unit}`, "割当済み数量": view.allocated_total,
      "未割当数量": view.unallocated_quantity, "期限状態": labels[s.expiry_state], "使用期限": s.expiry_date || "—",
      "期限状況": labels[view.expiry_status], "在庫状態": labels[s.state], "品目登録状態": view.item_registration_state === "active" ? "登録中" : "登録終了",
      "統合先ID": s.merged_into_stock_id || "—", "統合世代": s.merge_generation };
  }
  function definitionList(element, values) {
    element.replaceChildren();
    for (const [key, value] of Object.entries(values)) {
      const dt = document.createElement("dt"); dt.textContent = key;
      const dd = document.createElement("dd"); dd.textContent = value;
      element.append(dt, dd);
    }
  }
  function syncExpiry(form) {
    const dated = form.elements.expiry_state.value === "dated";
    form.elements.expiry_date.disabled = !dated;
    form.elements.expiry_date.required = dated;
  }
  function expiryValues(form) {
    return { expiry_state: form.elements.expiry_state.value, expiry_date: form.elements.expiry_state.value === "dated" ? form.elements.expiry_date.value : null };
  }
  function submit(id, operation) {
    const form = $(id);
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const buttons = [...form.querySelectorAll("button")];
      buttons.forEach((b) => { b.disabled = true; });
      $("error").hidden = true;
      $("success").hidden = true;
      try { await operation(form); } catch (error) { showError(error); }
      finally { buttons.forEach((b) => { b.disabled = false; }); }
    });
  }
  async function loadList() {
    const generation = ++listGeneration;
    const params = new URLSearchParams(new FormData($("search")));
    for (const [key, value] of [...params]) if (!value) params.delete(key);
    params.set("limit", "50"); params.set("offset", String(offset));
    $("loading").hidden = false;
    $("error").hidden = true;
    try {
      const result = await api(`/api/v1/stocks?${params}`);
      if (generation !== listGeneration) return;
      $("rows").replaceChildren();
      for (const value of result.data) {
        const data = rowData(value);
        const tr = document.createElement("tr");
        for (const field of ["品目", "分類", "倉庫", "保管場所", "数量", "使用期限", "期限状況"]) {
          const td = document.createElement("td"); td.textContent = data[field]; tr.append(td);
        }
        const td = document.createElement("td"); const a = document.createElement("a");
        a.href = `/stocks/${value.stock.stock_id}`; a.textContent = "詳細を見る"; td.append(a); tr.append(td); $("rows").append(tr);
      }
      $("count").textContent = `${result.page.total}件中 ${offset + (result.data.length ? 1 : 0)}〜${offset + result.data.length}件`;
      $("empty").hidden = result.data.length !== 0;
      $("previous").disabled = offset === 0;
      $("next").disabled = offset + 50 >= result.page.total;
      history.replaceState(null, "", `/stocks?${params}`);
      const alerts = (await api("/api/v1/stock-alerts")).data;
      $("alerts").textContent = `有効在庫の警告　期限切れ ${alerts.expired_count}件 ／ 期限接近 ${alerts.near_expiry_count}件 ／ 未確認 ${alerts.unconfirmed_count}件`;
    } catch (error) { if (generation === listGeneration) showError(error); }
    finally { if (generation === listGeneration) $("loading").hidden = true; }
  }
  async function loadHistory(kind, append = false) {
    const path = kind === "state" ? "state-events" : "expiry-changes";
    const result = await api(`${root}/${path}?limit=50&offset=${historyOffsets[kind]}`);
    const container = $(`${kind}-history`);
    if (!append) container.replaceChildren();
    if (!append && !result.data.length) container.textContent = "履歴はありません。";
    for (const value of result.data) {
      const p = document.createElement("p");
      const actor = refs.operators.find((o) => o.operator_id === value.operator_id)?.name || value.operator_id;
      p.textContent = kind === "state" ? `${value.occurred_at} ${labels[value.action]} ／ 担当者 ${actor}` :
        `${value.changed_at} ${labels[value.before_expiry_state]} ${value.before_expiry_date || ""} → ${labels[value.after_expiry_state]} ${value.after_expiry_date || ""} ／ 担当者 ${actor}`;
      container.append(p);
    }
    $(`more-${kind}`).hidden = historyOffsets[kind] + result.data.length >= result.page.total;
  }
  async function loadDetail() {
    current = (await api(root)).data;
    definitionList($("detail"), rowData(current));
    const active = current.stock.state === "active";
    $("active-actions").hidden = !active;
    $("merge-actions").hidden = !active;
    $("restore-actions").hidden = current.stock.state !== "deleted";
    $("location-form").elements.location.value = current.stock.location;
    const form = $("expiry-form");
    form.elements.expiry_state.value = current.stock.expiry_state;
    form.elements.expiry_date.value = current.stock.expiry_date || "";
    syncExpiry(form);
    $("item-link").href = `/items/${current.stock.item_id}/edit`;
    $("warehouse-link").href = `/warehouses/${current.stock.warehouse_id}/edit`;
    token = null; $("merge-preview").hidden = true;
    for (const checkbox of document.querySelectorAll('input[type="checkbox"]')) checkbox.checked = false;
    historyOffsets.state = 0; historyOffsets.expiry = 0;
    await Promise.all([loadHistory("state"), loadHistory("expiry")]);
  }
  async function updated() {
    $("success").textContent = "保存しました。"; $("success").hidden = false;
    await loadDetail();
  }
  try {
    [refs.warehouses, refs.items, refs.operators] = await Promise.all([all("warehouses"), all("items"), all("operators")]);
    for (const select of document.querySelectorAll("[data-options]")) {
      const type = select.dataset.options;
      const id = { warehouses: "warehouse_id", items: "item_id", operators: "operator_id" }[type];
      for (const value of refs[type]) {
        if (select.dataset.activeOnly && value.registration_state !== "active") continue;
        const option = document.createElement("option"); option.value = value[id]; option.textContent = value.name; select.append(option);
      }
    }
    for (const form of document.querySelectorAll("form")) {
      if (form.elements.expiry_state) form.elements.expiry_state.addEventListener("change", () => syncExpiry(form));
    }
    if (mode === "list") {
      const params = new URLSearchParams(location.search);
      for (const [key, value] of params) if ($( "search").elements[key]) $("search").elements[key].value = value;
      offset = /^\d+$/.test(params.get("offset") || "") ? Number(params.get("offset")) : 0;
      $("search").addEventListener("submit", (e) => { e.preventDefault(); offset = 0; void loadList(); });
      $("clear").addEventListener("click", () => { $("search").reset(); offset = 0; void loadList(); });
      $("previous").addEventListener("click", () => { offset = Math.max(0, offset - 50); void loadList(); });
      $("next").addEventListener("click", () => { offset += 50; void loadList(); });
      await loadList();
    } else if (mode === "create") {
      const form = $("create");
      form.elements.item_id.addEventListener("change", () => {
        const item = refs.items.find((i) => i.item_id === form.elements.item_id.value);
        $("unit-hint").textContent = item ? `単位 ${item.quantity_unit} ／ ${item.is_divisible ? "小数第2位まで" : "整数のみ"}` : "";
      });
      submit("create", async (f) => {
        const values = Object.fromEntries(new FormData(f));
        Object.assign(values, expiryValues(f));
        if (!values.operator_id) delete values.operator_id;
        values.reason = values.reason || null;
        const result = await api("/api/v1/stocks", "POST", values);
        location.assign(`/stocks/${result.data.stock.stock.stock_id}?saved=1`);
      });
    } else {
      await loadDetail();
      if (new URLSearchParams(location.search).has("saved")) {
        $("success").textContent = "在庫情報を保存しました。"; $("success").hidden = false;
      }
      submit("location-form", async (f) => { await api(root, "PATCH", { location: f.elements.location.value }); await updated(); });
      submit("expiry-form", async (f) => { await api(`${root}/expiry`, "PUT", { ...expiryValues(f), operator_id: f.elements.operator_id.value }); await updated(); });
      for (const [id, action] of [["delete-form", "logical-deletion"], ["restore-form", "restoration"]]) {
        submit(id, async (f) => {
          await api(`${root}/${action}`, "POST", { operator_id: f.elements.operator_id.value, confirmed: f.elements.confirmed.checked });
          location.assign(`/stocks/${stockId}?saved=1`);
        });
      }
      submit("merge-form", async (f) => {
        token = null; $("merge-preview").hidden = true;
        const p = (await api("/api/v1/stock-merges/preview", "POST", { source_stock_id: stockId, target_stock_id: f.elements.target_stock_id.value })).data;
        token = p.preview_token;
        definitionList($("merge-detail"), { "統合元": `${p.source.stock.stock_id} ${p.source.item_name}`, "元の場所・期限": `${p.source.stock.location} ／ ${p.source.stock.expiry_date || labels[p.source.stock.expiry_state]}`,
          "元の数量": p.source.stock.quantity, "統合先": `${p.target.stock.stock_id} ${p.target.item_name}`, "先の場所・期限": `${p.target.stock.location} ／ ${p.target.stock.expiry_date || labels[p.target.stock.expiry_state]}`,
          "先の数量": p.target.stock.quantity, "統合後の元数量": p.after_source_quantity, "統合後の先数量": p.after_target_quantity, "統合後の先世代": p.after_target_generation });
        $("merge-notice").textContent = p.cancellation_notice;
        $("merge-confirm").elements.confirmed.checked = false;
        $("merge-preview").hidden = false;
      });
      submit("merge-confirm", async (f) => {
        if (!token) throw new Error("プレビューからやり直してください。");
        await api("/api/v1/stock-merges", "POST", { preview_token: token, operator_id: f.elements.operator_id.value, confirmed: f.elements.confirmed.checked });
        await updated();
      });
      for (const kind of ["state", "expiry"]) $(`more-${kind}`).addEventListener("click", async () => {
        historyOffsets[kind] += 50;
        try { await loadHistory(kind, true); } catch (error) { historyOffsets[kind] -= 50; showError(error); }
      });
    }
  } catch (error) { showError(error); }
  finally { $("loading").hidden = true; }
})();
