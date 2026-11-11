(function () {
  const searchForm = document.querySelector("#shelter-search-form");
  const queryInput = document.querySelector("#shelter-query");
  const loading = document.querySelector("#shelter-loading");
  const empty = document.querySelector("#shelter-empty");
  const error = document.querySelector("#shelter-error");
  const tableWrap = document.querySelector("#shelter-table-wrap");
  const tableBody = document.querySelector("#shelter-table-body");
  const count = document.querySelector("#shelter-count");

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
    count.textContent = `${shelters.length}件`;
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
      row.appendChild(action);
      tableBody.appendChild(row);
    });
  }

  async function loadShelters() {
    const params = new URLSearchParams();
    const query = queryInput.value.trim();
    if (query) params.set("q", query);
    loading.hidden = false;
    empty.hidden = true;
    tableWrap.hidden = true;
    error.hidden = true;
    try {
      const response = await fetch(`/api/v1/shelters?${params.toString()}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || "避難所情報を取得できませんでした。");
      render(result.data);
    } catch (reason) {
      showError(reason.message);
    }
  }

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadShelters();
  });
  loadShelters();
})();
