(function () {
    "use strict";

    const form = document.querySelector("#warehouse-form");
    const errorMessage = document.querySelector("#warehouse-form-error");

    if (!form) {
        return;
    }
    let busy = false;
    const fields = ["name", "facility_type", "address", "latitude", "longitude", "capacity_m3"];
    function clearErrors() {
        errorMessage.hidden = true; errorMessage.textContent = "";
        for (const name of fields) {
            const output = document.querySelector(`#warehouse-error-${name}`);
            if (output) { output.textContent = ""; output.hidden = true; }
            form.elements[name]?.removeAttribute("aria-invalid");
        }
    }

    function numberOrNull(value) {
        return value === "" ? null : Number(value);
    }

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        if (busy) return;
        clearErrors();

        const formData = new FormData(form);
        const payload = {
            name: formData.get("name"),
            facility_type: formData.get("facility_type"),
            address: formData.get("address"),
            latitude: numberOrNull(formData.get("latitude")),
            longitude: numberOrNull(formData.get("longitude")),
            capacity_m3: formData.get("capacity_m3") === "" ? null : formData.get("capacity_m3"),
        };

        const mode = form.dataset.mode;
        const warehouseId = form.dataset.warehouseId;
        const url =
            mode === "edit"
                ? `/api/v1/warehouses/${warehouseId}`
                : "/api/v1/warehouses";
        const method = mode === "edit" ? "PATCH" : "POST";
        busy = true;
        const submit = form.querySelector('button[type="submit"]');
        submit.disabled = true;

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
                errorMessage.textContent = response.status >= 500
                    ? "サーバーで保存を確認できませんでした。入力は保持しています。倉庫一覧で保存結果を確認してください。"
                    : result.error?.message || "倉庫情報の保存に失敗しました。";
                errorMessage.hidden = false;
                const errors = result.error?.fields;
                for (const field of Array.isArray(errors) ? errors : errors ? [errors] : []) {
                    const name = field.path?.replace(/^\/body\//, "/").slice(1);
                    if (!fields.includes(name)) {
                        if (field.message && response.status < 500) errorMessage.textContent += ` ${field.message}`;
                        continue;
                    }
                    const output = document.querySelector(`#warehouse-error-${name}`);
                    if (output && response.status < 500) {
                        output.textContent = field.message; output.hidden = false;
                        form.elements[name].setAttribute("aria-invalid", "true");
                    }
                }
            }
        } catch (error) {
            if (errorMessage) {
                errorMessage.textContent =
                    "通信または応答の確認に失敗しました。入力は保持しています。倉庫一覧で保存結果を確認してから再操作してください。";
                errorMessage.hidden = false;
            }
        } finally {
            busy = false; submit.disabled = false;
        }
    });
})();
