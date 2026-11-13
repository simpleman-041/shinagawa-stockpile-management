(function () {
  "use strict";

  const form = document.querySelector("#warehouse-search-form");
  const query = document.querySelector("#warehouse-query");
  const coordinates = document.querySelector("#warehouse-coordinates");
  const loading = document.querySelector("#warehouse-loading");
  const empty = document.querySelector("#warehouse-empty");
  const error = document.querySelector("#warehouse-error");
  const table = document.querySelector("#warehouse-table-wrap");
  const body = document.querySelector("#warehouse-table-body");
  const count = document.querySelector("#warehouse-count");
  const previous = document.querySelector("#warehouse-previous");
  const next = document.querySelector("#warehouse-next");
  let offset = 0, total = 0, busy = false, filters = new URLSearchParams();

  function setState(state) {
    loading.hidden = state !== "loading";
    empty.hidden = state !== "empty";
    error.hidden = state !== "error";
    table.hidden = state !== "data";
  }

  function text(value) {
    return value === null || value === undefined || value === "" ? "—" : String(value);
  }

  function row(warehouse) {
    const tr = document.createElement("tr");
    const cells = [
      warehouse.name,
      warehouse.facility_type,
      warehouse.address,
      warehouse.capacity_m3 === null ? "未設定" : warehouse.capacity_m3,
      warehouse.latitude === null ? "未登録" : `${warehouse.latitude}, ${warehouse.longitude}`,
    ];
    cells.forEach((value) => {
      const td = document.createElement("td");
      td.textContent = text(value);
      tr.appendChild(td);
    });
    const actionCell = document.createElement("td");
    const editLink = document.createElement("a");
    editLink.href = `/warehouses/${warehouse.warehouse_id}/edit`;  editLink.textContent = "編集";
    actionCell.appendChild(editLink);
    const detailLink = document.createElement("a");
    detailLink.href = `/warehouses/${warehouse.warehouse_id}`;
    detailLink.textContent = "詳細・日常基準";
    actionCell.append(" ／ ", detailLink);
    const stockLink = document.createElement("a");
    stockLink.href = `/stocks?warehouse_id=${encodeURIComponent(warehouse.warehouse_id)}`;
    stockLink.textContent = "在庫を見る";
    stockLink.setAttribute("aria-label", `${warehouse.name}の在庫を見る`);
    actionCell.append(" ／ ", stockLink);
    tr.appendChild(actionCell);
    return tr;
  }

  async function loadWarehouses(start = 0, selectedFilters = filters) {
    if (busy) return;
    busy = true; previous.disabled = next.disabled = true;
    setState("loading");
    body.replaceChildren();
    count.textContent = "";

    const params = new URLSearchParams(selectedFilters);
    params.set("limit", "50"); params.set("offset", String(start));

    try {
      const response = await fetch(`/api/v1/warehouses?${params.toString()}`, {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || "倉庫一覧を取得できませんでした。");
      filters = new URLSearchParams(selectedFilters); offset = start; total = payload.page.total;
      count.textContent = `${total}件${payload.data.length ? ` ／ ${offset + 1}〜${offset + payload.data.length}件目` : ""}`;

      if (!payload.data.length) {
        setState("empty");
      } else {
        payload.data.forEach((warehouse) => body.appendChild(row(warehouse)));
        setState("data");
      }
    } catch (reason) {
      error.textContent = reason.message || "通信に失敗しました。時間をおいて再度お試しください。";
      setState("error");
    } finally {
      busy = false; previous.disabled = offset === 0; next.disabled = offset + 50 >= total;
    }
  }

  form.addEventListener("submit", event => {
    event.preventDefault(); if (busy) return;
    const selectedFilters = new URLSearchParams();
    if (query.value) selectedFilters.set("q", query.value);
    if (coordinates.value) selectedFilters.set("coordinates", coordinates.value);
    return loadWarehouses(0, selectedFilters);
  });
  previous.addEventListener("click", () => loadWarehouses(Math.max(0, offset - 50)));
  next.addEventListener("click", () => loadWarehouses(offset + 50));
  loadWarehouses();
})();
