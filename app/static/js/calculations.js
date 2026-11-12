(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const mode = document.body.dataset.mode;
  const states = {computed: "計算済み", partial: "一部計算不可", unavailable: "計算不可"};
  const reasons = {dedicated: "専用全量", shared: "共有割当", unallocated: "共有未割当", expired: "期限切れ除外", unresolved: "帰属未確定"};
  const expiryStates = {dated: "期限あり", none: "期限不要", unconfirmed: "期限未確認"};
  let shelters = [], preview = null, busy = false, historyOffset = 0, historyFilters = new URLSearchParams();
  const query = new URLSearchParams(location.search);
  const display = (value, suffix = "") => value === null || value === undefined ? "計算不可" : `${value}${suffix}`;
  const at = (value) => new Intl.DateTimeFormat("ja-JP", {dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Tokyo"}).format(new Date(value));
  function node(tag, text) { const n = document.createElement(tag); n.textContent = text; return n; }
  function link(href, text) { const n = node("a", text); n.href = href; return n; }
  function notice(message = "", success = false) {
    $("calculation-error").hidden = true; $("calculation-success").hidden = true;
    if (message) { const target = $(success ? "calculation-success" : "calculation-error"); target.textContent = message; target.hidden = false; }
  }
  function lock(value) {
    busy = value;
    $("calculation-loading").hidden = !value;
    for (const id of ["calculation-inputs", "history-inputs"]) if ($(id)) $(id).disabled = value;
    if ($("save-inputs")) $("save-inputs").disabled = value || !preview?.calculation_token || Boolean(preview.saved);
  }
  async function api(path, method = "GET", data) {
    const options = {method, headers: {Accept: "application/json"}};
    if (data !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
    let response;
    try { response = await fetch(`/api/v1${path}`, options); }
    catch { throw new Error("通信に失敗しました。入力と表示中の結果は保持しています。保存操作の場合は計算履歴を確認してください。"); }
    let result;
    try { result = await response.json(); }
    catch { throw new Error("応答を確認できませんでした。入力を保持しています。履歴で保存結果を確認してください。"); }
    if (!response.ok) throw new Error([result.error?.message || "処理に失敗しました。", ...(result.error?.fields || []).map(f => f.message)].filter((v,i,a) => a.indexOf(v) === i).join(" "));
    return result;
  }
  function table(parent, title, columns, rows) {
    parent.append(node("h3", title));
    if (!rows.length) { parent.append(node("p", "対象はありません。")); return; }
    const wrap = document.createElement("div"); wrap.className = "table-wrap";
    const t = document.createElement("table"), head = document.createElement("thead"), tr = document.createElement("tr"), body = document.createElement("tbody");
    columns.forEach(c => tr.append(node("th", c))); head.append(tr); t.append(head);
    rows.forEach(values => { const r = document.createElement("tr"); values.forEach(v => r.append(node("td", v ?? "未設定"))); body.append(r); });
    t.append(body); wrap.append(t); parent.append(wrap);
  }
  function render(data, saved = false) {
    const h = saved ? data.run : data.header;
    $("calculation-result").hidden = false;
    $("result-title").textContent = saved ? `保存した計算 #${h.run_id}` : "計算結果（計算時点）";
    $("result-metadata").textContent = `${h.shelter_name} ／ ${h.target_people}人・${h.target_days}日 ／ 基準日 ${h.base_date}（日本時間） ／ 計算 ${at(h.calculated_at)}${saved ? ` ／ 保存 ${at(h.saved_at)}` : ""} ／ 倉庫設定${h.setup_state === "complete" ? "完了" : "中"} ／ 計算式 ${h.formula_version}`;
    $("result-state").textContent = states[h.result_state];
    $("result-minimum").textContent = `総合：${display(h.min_people, "人")} ／ ${display(h.min_days, "日")}`;
    const period = data.stocks.some(s => s.expires_in_period && Number(s.included_quantity) > 0);
    $("result-warning").hidden = !h.has_unknown_expiry && !period;
    $("result-warning").textContent = [h.has_unknown_expiry ? "期限未確認の在庫を暫定算入しています。期限を確認してください。" : "", period ? "目標期間内に期限が到来する算入在庫があります。" : ""].filter(Boolean).join(" ");
    $("result-reason").hidden = !h.unavailable_reason;
    $("result-reason").textContent = h.unavailable_reason || "";
    const rows = $("result-groups"); rows.replaceChildren();
    data.groups.forEach(g => {
      const row = document.createElement("tr");
      // 整数単位の調達目安を小数数量から損失なく切上げる。
      let purchase = g.shortage_quantity;
      if (g.shortage_quantity !== null && !g.is_divisible) {
        const [whole, fraction = ""] = g.shortage_quantity.split(".");
        purchase = String(BigInt(whole) + (/[1-9]/.test(fraction) ? 1n : 0n));
      }
      [ `${g.group_name} (${g.calculation_unit ?? "単位未設定"})`, display(g.required_quantity), display(g.included_quantity), display(g.covered_quantity),
        `${display(g.shortage_quantity)}${purchase === null ? "" : ` ／ 調達目安 ${purchase}`}`, display(g.coverage_rate, "%"),
        `${display(g.people, "人")}${g.limits_people ? "（制約需要）" : ""}`, `${display(g.days, "日")}${g.limits_days ? "（制約需要）" : ""}`,
        `${states[g.result_state]}${g.has_unknown_expiry ? "・期限未確認を暫定算入" : ""}\n参考量 ${g.reference_quantity ?? "確認不可"}${g.unavailable_reason ? `\n${g.unavailable_reason}` : ""}`
      ].forEach(v => row.append(node("td", v))); rows.append(row);
    });
    const detail = $("result-details"); detail.replaceChildren();
    table(detail, "需要基準", ["需要", "共通単位・分割", "1人1日の使用量", "出典", "版・日付", "適用条件"], data.groups.map(g => [g.group_name, `${g.calculation_unit ?? "未設定"} ／ ${g.is_divisible === null ? "未設定" : g.is_divisible ? "分割可" : "整数単位"}`, g.daily_usage, g.source_text, g.version_or_date, g.conditions]));
    const groups = new Map(data.groups.map(g => [g.group_id,g.group_name]));
    const items = new Map(data.items.map(i => [i.item_id,i.item_name]));
    const warehouses = new Map(data.warehouses.map(w => [w.warehouse_id,w.warehouse_name]));
    table(detail, "品目と換算（計算時点）", ["品目", "需要", "管理単位・登録状態", "換算係数", "出典", "版・日付", "適用条件"], data.items.map(i => [i.item_name, groups.get(i.group_id), `${i.quantity_unit} ／ ${i.registration_state === "closed" ? "登録終了" : "登録中"}`, i.factor_x100 === null ? "未設定" : `${BigInt(i.factor_x100) / 100n}.${String(BigInt(i.factor_x100) % 100n).padStart(2,"0")}`, i.source_text,i.version_or_date,i.conditions]));
    table(detail, "倉庫と全対応先（計算時点）", ["倉庫", "区分", "対応先"], data.warehouses.map(w => [w.warehouse_name, {dedicated:"専用",shared:"共有"}[w.allocation_mode] || "未設定", data.warehouse_links.filter(l => l.warehouse_id === w.warehouse_id).map(l => `${l.shelter_name} (#${l.shelter_id})`).join("、") || "なし"]));
    table(detail, "在庫の算入根拠（計算時点）", ["在庫ID・倉庫", "品目", "現物数量", "全割当済み", "対象への割当", "算入量（管理単位）", "換算量（共通単位）", "期限", "算入・除外理由"], data.stocks.map(s => [`#${s.stock_id} ${warehouses.get(s.warehouse_id)}`, items.get(s.item_id),s.stock_quantity,s.allocated_total,s.selected_allocation,s.included_quantity,s.converted_quantity,`${expiryStates[s.expiry_state]} ${s.expiry_date || ""}${s.unknown_expiry_warning ? "（暫定算入）" : ""}${s.expires_in_period ? "（期間内到来）" : ""}`,reasons[s.selection_reason]]));
    const corrections = $("correction-links"); corrections.replaceChildren();
    if (saved) {
      if (h.correction_of_run_id) corrections.append(link(`/calculation-runs/${h.correction_of_run_id}`, `訂正元 #${h.correction_of_run_id}`), node("span", " "));
      data.correction_run_ids.forEach(id => corrections.append(link(`/calculation-runs/${id}`, `訂正先 #${id}`), node("span", " ")));
      corrections.append(link(`/calculations?shelter_id=${h.shelter_id}&correction_of_run_id=${h.run_id}`, "新しい条件で試算して訂正として保存"));
    }
  }
  function selectShelter() {
    const shelter = shelters.find(s => String(s.shelter_id) === $("calculation-shelter").value);
    $("target-people").value = shelter?.target_people ?? ""; $("target-days").value = shelter?.target_days ?? "";
    $("formal-target").textContent = shelter ? `正式目標：${shelter.target_people === null ? "未設定" : `${shelter.target_people}人・${shelter.target_days}日`} ／ 倉庫設定${shelter.setup_state === "complete" ? "完了" : "中"}` : "";
    const links = $("shelter-links"); links.replaceChildren();
    if (shelter) links.append(link(`/shelters/${shelter.shelter_id}/edit`, "正式目標を編集"), node("span", " ／ "), link(`/shelters/${shelter.shelter_id}/warehouse-settings`, "倉庫対応・共有割当を確認"));
  }
  async function loadHistory(offset = 0) {
    if (busy) return;
    notice(); lock(true);
    $("history-previous").disabled = true; $("history-next").disabled = true;
    const params = new URLSearchParams(historyFilters); params.set("limit","20"); params.set("offset",String(offset));
    try {
      const r = await api(`/calculation-runs?${params}`); historyOffset = offset;
      $("history-rows").replaceChildren(); $("history-empty").hidden = r.page.total !== 0; $("history-table").hidden = r.data.length === 0;
      $("history-count").textContent = `${r.page.total}件${r.data.length ? ` ／ ${offset+1}〜${offset+r.data.length}件目` : ""}`;
      r.data.forEach(h => { const row = document.createElement("tr"); [h.run_id,h.shelter_name,at(h.calculated_at),`${h.target_people}人・${h.target_days}日`, states[h.result_state],`${display(h.min_people,"人")} ／ ${display(h.min_days,"日")}`].forEach(v => row.append(node("td",v))); const cell = document.createElement("td"); cell.append(link(`/calculation-runs/${h.run_id}`, "詳細")); row.append(cell); $("history-rows").append(row); });
      $("history-previous").disabled = offset === 0; $("history-next").disabled = offset + r.data.length >= r.page.total;
    } catch (error) { notice(error.message); }
    finally { lock(false); }
  }
  if ($("calculation-form")) {
    $("calculation-shelter").addEventListener("change", selectShelter);
    $("calculation-form").addEventListener("submit", async e => {
      e.preventDefault(); if (busy) return;
      const people = Number($("target-people").value), days = Number($("target-days").value);
      if (![people,days].every(v => Number.isSafeInteger(v) && v > 0)) { notice("人数・日数には1以上の整数を入力してください。"); return; }
      const values = {shelter_id: $("calculation-shelter").value,target_people:people,target_days:days};
      notice(); lock(true);
      try {
        preview = (await api("/calculations","POST",values)).data; render(preview);
        $("save-state").textContent = "未保存です。表示した条件・数量・根拠を確認して保存してください。";
        const params = new URLSearchParams({shelter_id:values.shelter_id,token:preview.calculation_token});
        if ($("save-calculation-form").elements.correction_of_run_id.value) params.set("correction_of_run_id", $("save-calculation-form").elements.correction_of_run_id.value);
        history.replaceState(null,"",`/calculations?${params}`);
      } catch (error) { notice(error.message + (preview ? " 表示中の結果は前回の計算です。" : "")); }
      finally { lock(false); }
    });
    $("save-calculation-form").addEventListener("submit", async e => {
      e.preventDefault(); if (busy || !preview || preview.saved) return;
      const correction = e.currentTarget.elements.correction_of_run_id.value;
      const values = {calculation_token:preview.calculation_token,correction_of_run_id:correction || null};
      notice(); lock(true);
      try {
        const r = (await api("/calculation-runs","POST",values)).data;
        preview.saved = true; $("save-state").replaceChildren(node("span", "保存済みです。 "),link(`/calculation-runs/${r.run.run_id}`, `保存計算 #${r.run.run_id}を確認`));
        notice("計算時点の結果と根拠を保存しました。",true);
      } catch (error) { notice(error.message); }
      finally { lock(false); }
    });
  }
  if ($("history-form")) {
    $("history-form").addEventListener("submit", e => {
      e.preventDefault(); if (busy) return;
      const values = new FormData(e.currentTarget), filters = new URLSearchParams();
      for (const [k,v] of values) if (v) {
        if (k === "from" || k === "to") { const time = new Date(v); if (Number.isNaN(time.getTime())) { notice("日時を確認してください。"); return; } filters.set(k,time.toISOString()); }
        else filters.set(k,v);
      }
      historyFilters = filters; loadHistory(0);
    });
    $("history-previous").addEventListener("click",() => loadHistory(Math.max(0,historyOffset-20)));
    $("history-next").addEventListener("click",() => loadHistory(historyOffset+20));
  }
  async function init() {
    lock(true);
    try {
      if (mode === "saved") { render((await api(`/calculation-runs/${document.body.dataset.runId}`)).data,true); return; }
      shelters = (await api("/shelters")).data;
      const select = $("calculation-shelter");
      shelters.forEach(s => { const o = node("option",s.name); o.value = String(s.shelter_id); select.append(o); });
      if (query.has("shelter_id")) select.value = query.get("shelter_id");
      if (mode === "calculate") {
        selectShelter();
        if (query.has("correction_of_run_id")) $("save-calculation-form").elements.correction_of_run_id.value = query.get("correction_of_run_id");
        if (query.has("token")) { preview = (await api(`/calculations/${encodeURIComponent(query.get("token"))}`)).data; render(preview); }
        if (!shelters.length) notice("避難所が未登録です。避難所一覧から登録してください。");
      } else if (select.value) historyFilters.set("shelter_id",select.value);
    } catch (error) { notice(error.message); }
    finally { lock(false); }
    if (mode === "history") await loadHistory();
  }
  init();
})();
