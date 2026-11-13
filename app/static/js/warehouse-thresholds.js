(async () => {
  "use strict";
  const $ = id => document.getElementById(id);
  const root = `/api/v1/warehouses/${document.body.dataset.warehouseId}`;
  let items = [], thresholds = [], summary = [], busy = false, ready = false, dirty = false, mustRefresh = false, selectedId = "";
  function notice(message = "", success = false) {
    $("threshold-error").hidden = $("threshold-success").hidden = true;
    if (message) { const target = $(success ? "threshold-success" : "threshold-error"); target.textContent = message; target.hidden = false; }
    $("threshold-value-error").hidden = true;
    $("threshold-value").removeAttribute("aria-invalid");
  }
  function lock(value) {
    busy = value; $("threshold-loading").hidden = !value;
    $("threshold-inputs").disabled = value || !ready;
    $("threshold-save").disabled = value || !ready || mustRefresh;
    $("threshold-refresh").disabled = value;
  }
  async function api(url, method = "GET", values) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, {method, signal: controller.signal, headers: {Accept: "application/json", ...(values ? {"Content-Type": "application/json"} : {})}, ...(values ? {body: JSON.stringify(values)} : {})});
      let result;
      try { result = await response.json(); } catch { throw new Error("応答を確認できません。基準・警告を再取得してください。"); }
      if (!response.ok) {
        const error = new Error(response.status >= 500 ? "サーバーで処理を確認できませんでした。" : result.error?.message || "処理に失敗しました。");
        error.fields = response.status < 500 ? result.error?.fields || [] : [];
        error.uncertain = response.status >= 500; throw error;
      }
      if (method === "PUT" && (typeof result.data?.minimum_quantity !== "string" || result.data.item_id !== selected().item_id || result.data.warehouse_id !== document.body.dataset.warehouseId)) throw new Error("保存応答を確認できません。");
      return result;
    } catch (error) {
      if (error.fields) throw error;
      const failure = new Error("通信または応答の確認に失敗しました。入力は保持しています。基準・警告を再取得して結果を確認してください。");
      failure.uncertain = true; throw failure;
    } finally { clearTimeout(timer); }
  }
  async function all(url) {
    const rows = [];
    while (true) {
      const page = await api(`${url}?limit=200&offset=${rows.length}`);
      rows.push(...page.data);
      if (rows.length >= page.page.total) return rows;
      if (!page.data.length) throw new Error("一覧が変更されました。再取得してください。");
    }
  }
  function selected() { return items.find(item => item.item_id === $("threshold-item").value); }
  function render() {
    const item = selected();
    if (!item) return;
    selectedId = item.item_id;
    const threshold = thresholds.find(t => t.item_id === item.item_id);
    const status = summary.find(s => s.item_id === item.item_id);
    $("threshold-current").textContent = `${item.name}（品目ID ${item.item_id}）／ 現在の基準：${threshold ? `${threshold.minimum_quantity} ${item.quantity_unit}` : "未設定"}`;
    $("threshold-value").value = threshold?.minimum_quantity ?? "";
    $("threshold-value").step = item.is_divisible ? "0.01" : "1";
    $("threshold-unit").textContent = `（${item.quantity_unit}・${item.is_divisible ? "小数第2位まで" : "整数"}）`;
    $("threshold-warning").textContent = !threshold ? "日常基準は未設定です。" : `日常使用可能数：${status?.daily_usable_quantity ?? "確認できません"} ${item.quantity_unit} ／ ${status?.below_minimum === true ? "日常基準未満" : status?.below_minimum === false ? "日常基準以上" : "警告状態を確認できません"}`;
    dirty = false;
  }
  async function refresh() {
    // 両方の取得が成功するまで表示用データを入れ替えない。
    const fresh = await all(`${root}/thresholds`);
    const current = (await api(`${root}/summary`)).data;
    thresholds = fresh; summary = current.items;
    mustRefresh = false; render();
  }
  $("threshold-item").addEventListener("change", () => {
    if (dirty && !window.confirm("入力中の基準を破棄し、対象品目を切り替えますか？")) { $("threshold-item").value = selectedId; return; }
    notice(); render();
  });
  $("threshold-value").addEventListener("input", () => { dirty = true; });
  $("threshold-form").addEventListener("submit", async event => {
    event.preventDefault(); if (busy || !ready || mustRefresh || !selected()) return;
    notice();
    const value = $("threshold-value").value;
    if (value === "") { notice("基準を入力してください。空欄は設定解除になりません。"); return; }
    lock(true); let saved = false;
    try {
      await api(`${root}/thresholds/${selected().item_id}`, "PUT", {minimum_quantity: value});
      saved = true; mustRefresh = true;
      await refresh(); notice("基準を保存し、現在の基準・警告を再取得しました。", true);
    } catch (error) {
      if (error.uncertain) mustRefresh = true;
      notice(saved ? "基準は保存済みですが表示を再取得できません。再取得して結果を確認してください。" : error.message);
      const field = error.fields?.find(f => f.path === "/minimum_quantity");
      if (field) { $("threshold-value-error").textContent = field.message; $("threshold-value-error").hidden = false; $("threshold-value").setAttribute("aria-invalid", "true"); }
    } finally { lock(false); }
  });
  $("threshold-refresh").addEventListener("click", async () => {
    if (busy || (dirty && !window.confirm("入力中の基準を破棄し、保存済みの基準を再取得しますか？"))) return;
    notice(); lock(true);
    try { await initData(); } catch (error) { notice(error.message); } finally { lock(false); }
  });
  async function initData() {
    if (!items.length) {
      const choices = await all("/api/v1/items");
      items = choices;
      $("threshold-item").replaceChildren();
      for (const item of items) {
        const option = document.createElement("option"); option.value = item.item_id;
        option.textContent = `${item.name}（${item.quantity_unit}・ID ${item.item_id}${item.registration_state === "closed" ? "・登録終了" : ""}）`;
        $("threshold-item").append(option);
      }
    }
    $("threshold-empty").hidden = items.length !== 0;
    await refresh(); ready = items.length > 0;
  }
  lock(true); try { await initData(); } catch (error) { notice(error.message); } finally { lock(false); }
})();
