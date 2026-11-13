(function () {
  const searchForm = document.querySelector("#shelter-search-form");
  const queryInput = document.querySelector("#shelter-query");
  const loading = document.querySelector("#shelter-loading");
  const empty = document.querySelector("#shelter-empty");
  const error = document.querySelector("#shelter-error");
  const tableWrap = document.querySelector("#shelter-table-wrap");
  const tableBody = document.querySelector("#shelter-table-body");
  const count = document.querySelector("#shelter-count");
  const previous = document.querySelector("#shelter-previous");
  const next = document.querySelector("#shelter-next");
  let offset = 0, total = 0, busy = false, filters = new URLSearchParams();

  function showError(message) {
    error.textContent = message;
    error.hidden = false;
    loading.hidden = true;
    empty.hidden = true;
    tableWrap.hidden = true;
  }

  function makeCell(text) {
    const cell = document.createElement("td");
    cell.textContent = text;
    return cell;
  }

  function render(shelters) {
    tableBody.replaceChildren();
    count.textContent = `${total}件${shelters.length ? ` ／ ${offset + 1}〜${offset + shelters.length}件目` : ""}`;
    loading.hidden = true;
    error.hidden = true;
    empty.hidden = shelters.length !== 0;
    tableWrap.hidden = shelters.length === 0;

    shelters.forEach((shelter) => {
      const row = document.createElement("tr");
      row.appendChild(makeCell(shelter.name));
      row.appendChild(makeCell(shelter.address));
      row.appendChild(makeCell(
        shelter.target_people === null
          ? "未設定"
          : `${shelter.target_people}人 / ${shelter.target_days}日`
      ));
      row.appendChild(makeCell(shelter.setup_state === "complete" ? "完了" : "編集中"));
      const action = document.createElement("td");
      const link = document.createElement("a");
      link.href = `/shelters/${shelter.shelter_id}/edit`;
      link.textContent = "編集";
      action.appendChild(link);
      const settings = document.createElement("a");
      settings.href = `/shelters/${shelter.shelter_id}/warehouse-settings`;
      settings.textContent = " 倉庫対応・共有割当";
      action.appendChild(settings);
      const calculation = document.createElement("a");
      calculation.href = `/calculations?shelter_id=${shelter.shelter_id}`;
      calculation.textContent = " 備蓄計算";
      action.appendChild(calculation);
      row.appendChild(action);
      tableBody.appendChild(row);
    });
  }

  async function loadShelters(start = 0, selectedFilters = filters) {
    if (busy) return;
    busy = true; previous.disabled = next.disabled = true;
    const params = new URLSearchParams(selectedFilters);
    params.set("limit", "50"); params.set("offset", String(start));
    loading.hidden = false;
    empty.hidden = true;
    tableWrap.hidden = true;
    error.hidden = true;
    try {
      const response = await fetch(`/api/v1/shelters?${params.toString()}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || "避難所情報を取得できませんでした。");
      filters = new URLSearchParams(selectedFilters); offset = start; total = result.page.total;
      render(result.data);
    } catch (reason) {
      showError(reason.message);
    } finally {
      busy = false; previous.disabled = offset === 0; next.disabled = offset + 50 >= total;
    }
  }

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (busy) return;
    const selectedFilters = new URLSearchParams();
    if (queryInput.value.trim()) selectedFilters.set("q", queryInput.value.trim());
    return loadShelters(0, selectedFilters);
  });
  previous.addEventListener("click", () => loadShelters(Math.max(0, offset - 50)));
  next.addEventListener("click", () => loadShelters(offset + 50));
  loadShelters();
})();
