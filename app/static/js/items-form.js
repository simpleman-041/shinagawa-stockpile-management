(function () {
    "use strict";

    const form = document.querySelector("#item-form");
    const error = document.querySelector("#item-form-error");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        error.hidden = true;
        const data = new FormData(form);
        const volume = data.get("unit_volume_m3");
        const payload = {
            name: data.get("name"),
            category: data.get("category"),
            quantity_unit: data.get("quantity_unit"),
            unit_volume_m3: volume === "" ? null : volume,
            is_divisible: data.get("is_divisible") === "true",
            near_expiry_days: Number(data.get("near_expiry_days")),
        };
        const edit = form.dataset.mode === "edit";
        const itemId = form.dataset.itemId;

        try {
            const response = await fetch(edit ? `/api/v1/items/${itemId}` : "/api/v1/items", {
                method: edit ? "PATCH" : "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok) {
                error.textContent = result.error?.message || "保存に失敗しました。";
                error.hidden = false;
                return;
            }
            window.location.href = "/items";
        } catch (requestError) {
            error.textContent = "通信に失敗しました。";
            error.hidden = false;
        }
    });
})();
