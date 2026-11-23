(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const stateLabels = { near: "期限間近", expired: "期限切れ", unconfirmed: "期限未確認", below: "在庫不足" };

  async function api(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    let payload;
    try { payload = await response.json(); } catch { throw new Error("応答を読み取れませんでした。"); }
    if (!response.ok) throw new Error(payload.error?.message || "情報を取得できませんでした。");
    return payload.data;
  }

  function number(value) {
    if (value === null || value === undefined || value === "") return "未設定";
    return Number(value).toLocaleString("ja-JP", { maximumFractionDigits: 2 });
  }

  function warehouseName(warehouses, id) {
    return warehouses.find((warehouse) => String(warehouse.warehouse_id) === String(id))?.name || `倉庫${id}`;
  }

  function alertLink(item) {
    if (item.kind === "below") return `/stocks?warehouse_id=${encodeURIComponent(item.warehouseId)}`;
    return `/stocks?expiry_status=${encodeURIComponent(item.kind)}`;
  }

  function renderAlerts(alerts) {
    const list = $("alert-list");
    list.replaceChildren();
    alerts.slice(0, 8).forEach((item) => {
      const row = document.createElement("a");
      row.className = "alert-row";
      row.href = alertLink(item);
      const badge = document.createElement("span");
      badge.className = `alert-badge ${item.kind}`;
      badge.textContent = stateLabels[item.kind];
      const name = document.createElement("span");
      name.className = "alert-item";
      name.textContent = item.itemName;
      name.title = `${item.itemName}（${item.warehouseName}）`;
      const detail = document.createElement("span");
      detail.className = "alert-detail";
      detail.textContent = item.detail;
      const arrow = document.createElement("span");
      arrow.className = "alert-arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "›";
      row.append(badge, name, detail, arrow);
      list.append(row);
    });
    $("alert-empty").hidden = alerts.length > 0;
  }

  function renderWarehouses(values) {
    const body = $("warehouse-table-body");
    body.replaceChildren();
    values.slice(0, 8).forEach(({ warehouse, capacity }) => {
      const row = document.createElement("tr");
      const rate = capacity.state === "computed" ? Number(capacity.usage_rate) : null;
      const over = capacity.level === "over" || capacity.level === "full";
      const unavailable = capacity.level === "unknown" || capacity.state !== "computed";
      const used = capacity.state === "computed" ? capacity.used_volume_m3 : null;
      [warehouse.name, number(capacity.capacity_m3), number(used), rate === null ? "未計算" : `${number(rate)}%`]
        .forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); });

      const usageCell = document.createElement("td");
      const bar = document.createElement("div");
      bar.className = "usage-bar";
      bar.setAttribute("role", "progressbar");
      bar.setAttribute("aria-label", `${warehouse.name}の使用状況`);
      if (rate !== null) bar.setAttribute("aria-valuenow", String(rate));
      bar.setAttribute("aria-valuemin", "0");
      bar.setAttribute("aria-valuemax", "100");
      const fill = document.createElement("span");
      if (over) fill.className = "over";
      fill.style.width = `${Math.min(Math.max(rate || 0, 0), 100)}%`;
      bar.append(fill); usageCell.append(bar); row.append(usageCell);

      const stateCell = document.createElement("td");
      const state = document.createElement("span");
      state.className = `state-badge${over ? " over" : unavailable ? " unknown" : ""}`;
      state.textContent = over ? "超過" : unavailable ? "計算不可" : "正常";
      stateCell.append(state); row.append(stateCell);
      if (unavailable) {
        const reason = document.createElement("small");
        reason.className = "capacity-reason";
        reason.textContent = (capacity.issues || []).map((issue) => issue.message).join(" ") || "容量を計算できません。";
        stateCell.append(reason);
      }
      body.append(row);
    });
    $("warehouse-empty").hidden = values.length > 0;
  }

  function popupContent(warehouse, capacity) {
    const root = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = warehouse.name;
    const status = document.createElement("span");
    const over = capacity.level === "over" || capacity.level === "full";
    const unavailable = capacity.level === "unknown" || capacity.state !== "computed";
    status.textContent = over ? "超過" : unavailable ? "計算不可" : `使用率 ${number(capacity.usage_rate)}%`;
    root.append(title, document.createElement("br"), status);
    if (unavailable) {
      const reason = document.createElement("span");
      reason.textContent = `（${(capacity.issues || []).map((issue) => issue.message).join(" ") || "容量を計算できません。"}）`;
      root.append(reason);
    }
    root.append(document.createElement("br"));
    const link = document.createElement("a");
    link.href = `/warehouses/${encodeURIComponent(warehouse.warehouse_id)}`;
    link.textContent = "詳細を見る";
    root.append(link);
    return root;
  }

  function initMap(values) {
    if (typeof L === "undefined") {
      $("map-caption").textContent = "地図を読み込めませんでした。倉庫一覧は利用できます。";
      return;
    }
    const map = L.map("home-map", { zoomControl: false }).setView([35.609, 139.73], 12);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "地理院タイル" }).addTo(map);
    const markers = [];
    values.filter(({ warehouse }) => warehouse.latitude !== null && warehouse.longitude !== null).forEach(({ warehouse, capacity }) => {
      const level = capacity.level === "over" || capacity.level === "full" ? "over" : capacity.level === "available" ? "available" : "unknown";
      const icon = L.divIcon({ className: `home-pin ${level}`, iconSize: [14, 14], iconAnchor: [7, 7] });
      const marker = L.marker([warehouse.latitude, warehouse.longitude], { icon })
        .bindPopup(popupContent(warehouse, capacity))
        .addTo(map);
      markers.push(marker);
    });
    if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds(), { padding: [20, 20], maxZoom: 13 });
    const located = values.filter(({ warehouse }) => warehouse.latitude !== null && warehouse.longitude !== null).length;
    $("map-caption").textContent = `${located}件の倉庫を表示中。色は使用状況を示します。`;
  }

  async function load() {
    try {
      const gis = await api("/api/v1/gis/warehouses");
      const warehouses = [...gis.located, ...gis.unlocated];
      const summaries = await Promise.all(warehouses.map(async (warehouse) => ({
        warehouse,
        summary: await api(`/api/v1/warehouses/${warehouse.warehouse_id}/summary`),
      })));
      renderWarehouses(summaries.map(({ warehouse, summary }) => ({ warehouse, capacity: summary.capacity })));
      initMap(summaries.map(({ warehouse, summary }) => ({ warehouse, capacity: summary.capacity })));

      const kinds = ["near", "expired", "unconfirmed"];
      const stockAlerts = (await Promise.all(kinds.map(async (kind) => (await api(`/api/v1/stocks?expiry_status=${kind}&limit=200&offset=0`)).map((view) => ({
        kind,
        itemName: view.item_name,
        warehouseId: view.stock.warehouse_id,
        warehouseName: warehouseName(warehouses, view.stock.warehouse_id),
        detail: kind === "unconfirmed" ? "期限未確認" : (view.stock.expiry_date || stateLabels[kind]),
      }))))).flat();
      const below = summaries.flatMap(({ warehouse, summary }) => summary.items.filter((item) => item.below_minimum).map((item) => ({
        kind: "below",
        itemName: item.item_name,
        warehouseId: warehouse.warehouse_id,
        warehouseName: warehouse.name,
        detail: `必要量 ${number(item.minimum_quantity)} ${item.quantity_unit}`,
      })));
      renderAlerts([...stockAlerts, ...below]);
    } catch (reason) {
      $("home-error").textContent = reason.message || "ホーム情報を取得できませんでした。";
      $("home-error").hidden = false;
      $("map-caption").textContent = "情報を取得できませんでした。倉庫一覧を確認してください。";
    } finally {
      $("home-loading").hidden = true;
    }
  }

  load();
})();
