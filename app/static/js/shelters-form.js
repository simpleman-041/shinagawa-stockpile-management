(function () {
  "use strict";

  async function request(url, method, payload) {
    let response;
    try {
      response = await fetch(url, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
    } catch {
      throw new Error("通信に失敗しました。入力を保持しています。保存結果を確認してから再操作してください。");
    }
    let result;
    try { result = await response.json(); }
    catch { throw new Error("保存結果を確認できませんでした。現在の登録内容を確認してから再操作してください。"); }
    if (!response.ok) throw new Error(result.error?.message || "保存に失敗しました。");
    return result.data;
  }

  function targets(values) {
    const people = Number(values.get("target_people")), days = Number(values.get("target_days"));
    if (![people, days].every(value => Number.isSafeInteger(value) && value > 0)) {
      throw new Error("目標人数と目標日数は両方とも1以上の整数で入力してください。");
    }
    return { target_people: people, target_days: days };
  }

  function bind(formId, errorId, successId, save) {
    const form = document.querySelector(`#${formId}`);
    if (!form) return;
    const error = document.querySelector(`#${errorId}`), success = document.querySelector(`#${successId}`);
    let busy = false;
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (busy) return;
      const values = new FormData(form);
      const controls = [...form.querySelectorAll("button, input, select")];
      const disabled = controls.map(control => control.disabled);
      busy = true; error.hidden = true; success.hidden = true;
      controls.forEach(control => { control.disabled = true; });
      try {
        const message = await save(values, form);
        if (message) { success.textContent = message; success.hidden = false; }
      } catch (reason) {
        error.textContent = reason.message; error.hidden = false;
      } finally {
        controls.forEach((control, index) => { control.disabled = disabled[index]; });
        busy = false;
      }
    });
  }

  bind("shelter-form", "shelter-form-error", "shelter-form-success", async (values, form) => {
    const name = values.get("name").trim(), address = values.get("address").trim();
    if (!name || !address) throw new Error("施設名と住所を入力してください。");
    const edit = form.dataset.mode === "edit";
    const payload = { name, address };
    if (!edit) {
      const people = values.get("target_people").trim(), days = values.get("target_days").trim();
      if (people || days) Object.assign(payload, targets(values));
    }
    await request(edit ? `/api/v1/shelters/${form.dataset.shelterId}` : "/api/v1/shelters", edit ? "PATCH" : "POST", payload);
    if (edit) return "名称・住所を保存しました。";
    window.location.href = "/shelters";
  });

  bind("shelter-targets-form", "shelter-targets-error", "shelter-targets-success", async (values, form) => {
    const payload = targets(values);
    await request(`/api/v1/shelters/${form.dataset.shelterId}/targets`, "PUT", payload);
    return `正式目標を${payload.target_people}人・${payload.target_days}日に更新しました。備蓄計算を開き直すと初期値に反映されます。`;
  });
})();
