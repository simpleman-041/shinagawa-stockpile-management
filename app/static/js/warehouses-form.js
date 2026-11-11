(function () {
    "use strict";

    const form = document.querySelector("#warehouse-form");
    const errorMessage = document.querySelector("#warehouse-form-error");

    if (!form) {
        return;
    }

    function numberOrNull(value) {
        return value === "" ? null : Number(value);
    }

    form.addEventListener("submit", async function (event) {
        event.preventDefault();

        const formData = new FormData(form);
        const payload = {
            name: formData.get("name"),
            facility_type: formData.get("facility_type"),
            address: formData.get("address"),
            latitude: numberOrNull(formData.get("latitude")),
            longitude: numberOrNull(formData.get("longitude")),
            capacity_m3: numberOrNull(formData.get("capacity_m3")),
        };

        const mode = form.dataset.mode;
        const warehouseId = form.dataset.warehouseId;
        const url =
            mode === "edit"
                ? `/api/v1/warehouses/${warehouseId}`
                : "/api/v1/warehouses";
        const method = mode === "edit" ? "PATCH" : "POST";

        try {
            const response = await fetch(url, {
                method: method,
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json",
                },
                body: JSON.stringify(payload),
            });

            const result = await response.json();

            if (response.ok) {
                window.location.href = "/warehouses";
                return;
            }

            if (errorMessage) {
                errorMessage.textContent =
                    result.message || "倉庫情報の保存に失敗しました。";
                errorMessage.hidden = false;
            }
        } catch (error) {
            if (errorMessage) {
                errorMessage.textContent =
                    "通信に失敗しました。時間をおいて再度お試しください。";
                errorMessage.hidden = false;
            }
        }
    });
})();
