/* Q54〜58・AUD-02。既存DG/IC APIへ接続し、保存結果・在庫を変更しない。 */
"use strict";
(async () => {
  const $ = id => document.getElementById(id);
  const createForm = $("group-create-form"), editForm = $("group-edit-form"), membershipForm = $("membership-form");
  const groupFields = ["name", "calculation_unit", "is_divisible", "daily_usage", "source_text", "version_or_date", "conditions"];
  const conversionFields = ["factor", "source_text", "version_or_date", "conditions"];
  const labels = {name: "需要名", calculation_unit: "共通単位", is_divisible: "分割可否", daily_usage: "使用量", factor: "換算係数", source_text: "根拠・出典", version_or_date: "版・日付", conditions: "適用条件", group_id: "需要", item_id: "品目"};
  let groups = [], items = [], snapshots = new Map(), current = null, rows = [];
  let ready = false, busy = false, needsRefresh = false, editDirty = false, membershipDirty = false, resetCreated = false;
  const node = (tag, text) => { const element = document.createElement(tag); element.textContent = text; return element; };
  const nullable = value => value === "" ? null : value;
  const shown = value => value === null || value === "" ? "未設定" : String(value);
  const groupName = id => groups.find(group => group.group_id === id)?.name || "未所属";
  const itemName = id => items.find(item => item.item_id === id)?.name || `品目 #${id}`;

  function fieldLabel(path) {
    const conversion = path.match(/^\/conversions\/(\d+)\/([^/]+)$/);
    if (conversion) return `${itemName(rows[Number(conversion[1])]?.item_id)}の${labels[conversion[2]] || "入力"}`;
    return labels[path.split("/").at(-1)] || "入力内容";
  }
  async function api(path, method = "GET", values, paged = false) {
    let response, result;
    try {
      response = await fetch(`/api/v1${path}`, {method, headers: {Accept: "application/json", ...(values === undefined ? {} : {"Content-Type": "application/json"})}, ...(values === undefined ? {} : {body: JSON.stringify(values)})});
      result = await response.json();
    } catch {
      if (method !== "GET") needsRefresh = true;
      throw new Error("通信または応答の確認に失敗しました。入力は保持しています。登録済みの条件を再取得して保存結果を確認してから再操作してください。");
    }
    if (!response.ok) {
      throw new Error([result.error?.message || "条件を保存・取得できませんでした。", ...(result.error?.fields || []).map(field => `${fieldLabel(field.path)}：${field.message}`)].join(" "));
    }
    return paged ? result : result.data;
  }
  async function all(resource) {
    const values = [];
    while (true) {
      const result = await api(`/${resource}?limit=200&offset=${values.length}`, "GET", undefined, true);
      values.push(...result.data);
      if (values.length >= result.page.total) return values;
      if (!result.data.length) throw new Error("一覧の続きが取得できませんでした。再取得してください。");
    }
  }
  function option(select, value, text) {
    const element = node("option", text); element.value = value; select.append(element);
  }
  function fill(form, values, fields) {
    for (const field of fields) form.elements[field].value = values[field] === null ? "" : String(values[field]);
  }
  function readGroup(form) {
    return Object.fromEntries(groupFields.map(field => {
      const value = form.elements[field].value;
      return [field, field === "is_divisible" ? value === "" ? null : value === "true" : field === "name" ? value : nullable(value)];
    }));
  }
  function member(itemId) {
    for (const snapshot of snapshots.values()) {
      const conversion = snapshot.conversions.find(row => row.item_id === itemId);
      if (conversion) return {group: snapshot.group, conversion};
    }
    return null;
  }
  function membershipUnit() {
    const group = groups.find(value => value.group_id === $("membership-group").value);
    $("membership-unit").textContent = group ? `共通単位：${shown(group.calculation_unit)}。係数は品目の管理単位1あたりの共通単位量です。` : "保存先の需要を選択してください。";
  }
  function selectItem() {
    const itemId = $("membership-item").value, value = member(itemId);
    const item = items.find(item => item.item_id === itemId);
    $("membership-current").textContent = item ? `管理単位：${item.quantity_unit} ／ 現在の所属：${value?.group.name || "未所属"}${item.registration_state === "closed" ? " ／ 登録終了品目（対応を保持します）" : ""}` : "品目を選択してください。";
    $("membership-group").value = value?.group.group_id || "";
    fill(membershipForm, value?.conversion || Object.fromEntries(conversionFields.map(key => [key, null])), conversionFields);
    membershipDirty = false; membershipUnit();
  }
  function renderSelected(id) {
    current = snapshots.get(id) || null; rows = []; editDirty = false;
    $("conversion-rows").replaceChildren();
    $("group-unselected").hidden = Boolean(current);
    $("selected-group-title").textContent = current ? `${current.group.name}：条件・全所属品目の換算` : "選択需要の条件・全所属品目の換算";
    if (!current) { editForm.reset(); return; }
    fill(editForm, current.group, groupFields);
    $("conversions-empty").hidden = current.conversions.length !== 0;
    for (const conversion of current.conversions) {
      const item = items.find(value => value.item_id === conversion.item_id), tr = document.createElement("tr");
      tr.append(node("td", `${itemName(conversion.item_id)}${item?.registration_state === "closed" ? "（登録終了・保持対象）" : "（登録中）"}`), node("td", item?.quantity_unit || "未確認"));
      const inputs = {};
      for (const field of conversionFields) {
        const cell = document.createElement("td"), input = document.createElement("input");
        input.value = conversion[field] ?? ""; input.setAttribute("aria-label", `${itemName(conversion.item_id)}の${labels[field]}`);
        if (field === "factor") input.inputMode = "decimal";
        cell.append(input); tr.append(cell); inputs[field] = input;
      }
      rows.push({item_id: conversion.item_id, inputs}); $("conversion-rows").append(tr);
    }
  }
  function controls() {
    $("conditions-loading").hidden = !busy;
    $("conditions-refresh").disabled = busy;
    $("create-controls").disabled = busy || !ready || needsRefresh;
    $("select-controls").disabled = busy || !ready || !groups.length || needsRefresh;
    $("group-controls").disabled = busy || !ready || !current || needsRefresh;
    $("membership-controls").disabled = busy || !ready || !groups.length || !items.length || needsRefresh;
  }
  async function action(operation) {
    if (busy) return;
    busy = true; $("conditions-error").hidden = true; $("conditions-success").hidden = true; controls();
    try { await operation(); }
    catch (error) { $("conditions-error").textContent = error.message; $("conditions-error").hidden = false; }
    finally { busy = false; controls(); }
  }
  async function reload(preferred = current?.group.group_id) {
    const [nextGroups, nextItems] = await Promise.all([all("demand-groups"), all("items")]);
    const nextSnapshots = await Promise.all(nextGroups.map(group => api(`/demand-groups/${group.group_id}/conditions`)));
    groups = nextGroups; items = nextItems; snapshots = new Map(nextSnapshots.map(value => [value.group.group_id, value]));
    $("groups-count").textContent = `${groups.length}件`; $("groups-empty").hidden = groups.length !== 0;
    const select = $("condition-group"), memberGroup = $("membership-group"), memberItem = $("membership-item");
    for (const element of [select, memberGroup, memberItem]) { element.replaceChildren(); option(element, "", "選択してください"); }
    for (const group of groups) {
      option(select, group.group_id, `${group.name} ／ 単位 ${shown(group.calculation_unit)} ／ 使用量 ${shown(group.daily_usage)}`);
      option(memberGroup, group.group_id, `${group.name}（${shown(group.calculation_unit)}）`);
    }
    for (const item of items) option(memberItem, item.item_id, `${item.name}（${item.quantity_unit}・${item.registration_state === "closed" ? "登録終了" : "登録中"}）`);
    select.value = snapshots.has(preferred) ? preferred : "";
    renderSelected(select.value); memberItem.value = ""; membershipForm.dataset.itemId = ""; selectItem();
    $("membership-empty").hidden = Boolean(groups.length && items.length);
    if (resetCreated) { createForm.reset(); resetCreated = false; }
    ready = true; needsRefresh = false;
  }
  function discardNotice(except) {
    return (editDirty && except !== editForm) || (membershipDirty && except !== membershipForm)
      ? "\n他の編集欄の未保存入力は再取得で破棄されます。" : "";
  }
  function description(group) {
    return `需要：${group.name}\n共通単位：${shown(group.calculation_unit)} ／ 分割：${group.is_divisible === null ? "未設定" : group.is_divisible ? "可" : "不可"}\n1人1日の使用量：${shown(group.daily_usage)}\n根拠：${shown(group.source_text)}\n版・日付：${shown(group.version_or_date)}\n適用条件：${shown(group.conditions)}`;
  }
  async function saved(message, preferred) {
    $("conditions-success").textContent = message; $("conditions-success").hidden = false;
    needsRefresh = true;
    try { await reload(preferred); }
    catch (error) { throw new Error(`保存は完了しましたが、再取得に失敗しました。${error.message}`); }
  }

  editForm.addEventListener("input", () => { editDirty = true; });
  membershipForm.addEventListener("input", event => { if (event.target !== $("membership-item")) membershipDirty = true; });
  $("membership-item").addEventListener("change", () => {
    if (membershipDirty && !window.confirm("未保存の所属・換算入力を破棄して品目を切り替えますか？")) { $("membership-item").value = membershipForm.dataset.itemId || ""; return; }
    membershipForm.dataset.itemId = $("membership-item").value; selectItem();
  });
  $("membership-group").addEventListener("change", membershipUnit);
  $("conditions-refresh").addEventListener("click", () => action(async () => {
    if ((editDirty || membershipDirty) && !window.confirm("未保存の条件・所属入力を破棄し、登録済みの内容を再取得しますか？")) return;
    await reload();
  }));
  $("group-select-form").addEventListener("submit", event => {
    event.preventDefault(); return action(async () => {
      if (editDirty && !window.confirm("未保存の需要条件を破棄して条件を開きますか？")) return;
      renderSelected($("condition-group").value);
    });
  });
  createForm.addEventListener("submit", event => {
    event.preventDefault(); return action(async () => {
      const group = readGroup(createForm);
      if (!window.confirm(`${description(group)}\nこの需要を全備蓄計算の対象へ追加します。条件不足の場合は総合結果が計算不可になります。追加しますか？${discardNotice(createForm)}`)) return;
      const value = await api("/demand-groups", "POST", group); resetCreated = true;
      await saved(`需要「${value.name}」を追加しました。品目の対応と換算も設定してください。`, value.group_id);
    });
  });
  editForm.addEventListener("submit", event => {
    event.preventDefault(); return action(async () => {
      if (!current) throw new Error("需要を選択して条件を開いてください。");
      const group = readGroup(editForm), conversions = rows.map(row => ({item_id: row.item_id, ...Object.fromEntries(conversionFields.map(field => [field, nullable(row.inputs[field].value)]))}));
      const changedUnit = group.calculation_unit !== current.group.calculation_unit;
      const notice = changedUnit ? "\n共通単位を変更します。全所属品目の換算と根拠を再確認し、未確認係数を空欄にしたことを確認してください。" : "";
      if (!window.confirm(`${description(group)}\n登録終了品目を含む全${conversions.length}品目の換算・根拠を一括保存します。表の入力を確認しましたか？${notice}${discardNotice(editForm)}`)) return;
      await api(`/demand-groups/${current.group.group_id}/conditions`, "PUT", {group, conversions});
      await saved("需要条件と全所属品目の換算を保存しました。次の試算に反映されます。", current.group.group_id);
    });
  });
  membershipForm.addEventListener("submit", event => {
    event.preventDefault(); return action(async () => {
      const itemId = $("membership-item").value, groupId = $("membership-group").value;
      if (!itemId || !groupId) throw new Error("品目と保存先の需要を選択してください。");
      const conversion = Object.fromEntries(conversionFields.map(field => [field, nullable(membershipForm.elements[field].value)]));
      const previous = member(itemId), destination = groups.find(group => group.group_id === groupId);
      const operation = previous && previous.group.group_id !== groupId ? "別需要へ移動" : previous ? "換算を更新" : "新しく対応";
      if (!window.confirm(`${itemName(itemId)}を${operation}します。\n現在：${previous?.group.name || "未所属"} → 保存先：${groupName(groupId)}\n共通単位：${shown(destination.calculation_unit)} ／ 係数：${shown(conversion.factor)}\n根拠：${shown(conversion.source_text)}\n版・日付：${shown(conversion.version_or_date)}\n適用条件：${shown(conversion.conditions)}\n確認して保存しますか？${discardNotice(membershipForm)}`)) return;
      await api(`/items/${itemId}/conversion`, "PUT", {group_id: groupId, ...conversion});
      await saved(`${itemName(itemId)}の所属・換算を保存しました。`, groupId);
    });
  });
  await action(() => reload());
})();
