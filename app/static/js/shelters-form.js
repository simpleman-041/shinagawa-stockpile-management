(function () {
  const form = document.querySelector("#shelter-form");
  const error = document.querySelector("#shelter-form-error");
  const setupButton = document.querySelector("#setup-state-button");

  function showError(message) {
    error.textContent = message;
    error.hidden = false;
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error?.message || "保存に失敗しました。");
    return result.data;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    const values = new FormData(form);
    const name = values.get("name").trim();
    const address = values.get("address").trim();
    const people = values.get("target_people").trim();
    const days = values.get("target_days").trim();
    if (!name || !address) return showError("施設名と住所を入力してください。");
    if ((people === "") !== (days === "")) return showError("目標人数と目標日数は両方入力してください。");

    const payload = { name, address };
    if (people !== "") {
      payload.target_people = Number(people);
      payload.target_days = Number(days);
    }
    const id = form.dataset.shelterId;
    const isEdit = form.dataset.mode === "edit";
    try {
      const shelter = await request(
        isEdit ? `/api/v1/shelters/${id}` : "/api/v1/shelters",
        {
          method: isEdit ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      if (isEdit && people !== "") {
        await request(`/api/v1/shelters/${id}/targets`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_people: Number(people), target_days: Number(days) }),
        });
      }
      window.location.href = "/shelters";
    } catch (reason) {
      showError(reason.message);
    }
  });

  if (setupButton) {
    setupButton.addEventListener("click", async () => {
      error.hidden = true;
      const current = setupButton.dataset.state;
      const next = current === "complete" ? "editing" : "complete";
      try {
        await request(`/api/v1/shelters/${form.dataset.shelterId}/warehouse-setup`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ setup_state: next }),
        });
        window.location.reload();
      } catch (reason) {
        showError(reason.message);
      }
    });
  }
})();
