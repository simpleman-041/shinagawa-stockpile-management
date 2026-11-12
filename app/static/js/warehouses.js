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
    const stockLink = document.createElement("a");
    stockLink.href = `/stocks?warehouse_id=${encodeURIComponent(warehouse.warehouse_id)}`;
    stockLink.textContent = "在庫を見る";
    stockLink.setAttribute("aria-label", `${warehouse.name}の在庫を見る`);
    actionCell.append(" ／ ", stockLink);
    tr.appendChild(actionCell);
    return tr;
  }

  async function loadWarehouses(event) {
    if (event) event.preventDefault();
    setState("loading");
    body.replaceChildren();
    count.textContent = "";

    const params = new URLSearchParams();
    if (query.value) params.set("q", query.value);
    if (coordinates.value) params.set("coordinates", coordinates.value);

    try {
      const response = await fetch(`/api/v1/warehouses?${params.toString()}`, {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || "倉庫一覧を取得できませんでした。");

      if (!payload.data.length) {
        setState("empty");
      } else {
        payload.data.forEach((warehouse) => body.appendChild(row(warehouse)));
        count.textContent = `${payload.page.total}件`;
        setState("data");
      }
    } catch (reason) {
      error.textContent = reason.message || "通信に失敗しました。時間をおいて再度お試しください。";
      setState("error");
    }
  }

  form.addEventListener("submit", loadWarehouses);
  loadWarehouses();
})();
