(function () {
    "use strict";

    const form = document.querySelector("#item-form");
    const error = document.querySelector("#item-form-error");
    if (!form) return;

    const submit = document.querySelector("#item-form-submit");
    const status = document.querySelector("#item-form-status");
    const recovery = document.querySelector("#item-form-recovery");
    const recheck = document.querySelector("#item-form-recheck");
    const current = document.querySelector("#item-form-current");
    const resume = document.querySelector("#item-form-resume");
    const edit = form.dataset.mode === "edit";
    const itemId = form.dataset.itemId;
    const fields = ["name", "category", "quantity_unit", "unit_volume_m3", "is_divisible", "near_expiry_days"];
    const submitLabel = submit.textContent;
    let state = "idle", checkedCurrent = false;

    function updateControls() {
        const busy = state === "saving" || state === "checking";
        form.setAttribute("aria-busy", String(busy));
        submit.disabled = state !== "idle";
        submit.textContent = state === "saving" ? "保存中…" : submitLabel;
        for (const name of fields) form.elements[name].disabled = state !== "idle";
        if (recheck) recheck.disabled = state !== "uncertain";
        resume.disabled = state !== "uncertain" || (edit && !checkedCurrent);
    }

    function showStatus(message) {
        status.textContent = message;
        status.hidden = false;
    }

    // The timeout covers reading the body too. Aborting cannot undo a server commit.
    async function request(url, options) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal});
            return {response, result: await response.json()};
        } finally {
            clearTimeout(timer);
        }
    }

    function validItem(item) {
        return item && typeof item.item_id === "string" && /^[1-9][0-9]*$/.test(item.item_id)
            && (!edit || item.item_id === itemId)
            && ["name", "category", "quantity_unit"].every(name => typeof item[name] === "string" && item[name].trim() !== "")
            && (item.unit_volume_m3 === null || (typeof item.unit_volume_m3 === "string" && /^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$/.test(item.unit_volume_m3)))
            && typeof item.is_divisible === "boolean"
            && Number.isInteger(item.near_expiry_days) && item.near_expiry_days >= 1 && item.near_expiry_days <= 3650
            && ["active", "closed"].includes(item.registration_state);
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (state !== "idle") return;
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
        state = "saving";
        checkedCurrent = false;
        recovery.hidden = true;
        if (current) current.hidden = true;
        showStatus("保存中です。結果が表示されるまでお待ちください。");
        updateControls();

        try {
            const {response, result} = await request(edit ? `/api/v1/items/${itemId}` : "/api/v1/items", {
                method: edit ? "PATCH" : "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok && response.status >= 400 && response.status < 500
                && typeof result?.error?.code === "string" && result.error.code.trim() !== ""
                && typeof result.error.message === "string" && result.error.message.trim() !== "") {
                state = "idle";
                status.hidden = true;
                error.textContent = result.error.message;
                error.hidden = false;
                return;
            }
            if (!response.ok || response.status !== (edit ? 200 : 201) || !validItem(result?.data)) {
                throw new Error("保存応答を確認できませんでした。");
            }
            state = "saved";
            showStatus("保存を確認しました。一覧へ移動します。");
            window.location.href = "/items";
        } catch {
            state = "uncertain";
            status.hidden = true;
            error.textContent = "通信またはサーバー応答を確認できず、保存結果は不明です。保存できなかったとは限りません。下の案内に従って登録内容を確認してください。自動で再送はしません。";
            error.hidden = false;
            recovery.hidden = false;
        } finally {
            updateControls();
        }
    });

    if (recheck) recheck.addEventListener("click", async () => {
        if (state !== "uncertain") return;
        state = "checking";
        checkedCurrent = false;
        current.hidden = true;
        showStatus("現在の保存内容を確認中です…");
        updateControls();
        try {
            const {response, result} = await request(`/api/v1/items/${itemId}`, {
                headers: {Accept: "application/json"}, cache: "no-store",
            });
            if (!response.ok || !validItem(result?.data)) throw new Error("確認応答不正");
            const item = result.data;
            for (const name of fields) {
                let value = item[name];
                if (name === "unit_volume_m3" && value === null) value = "未設定";
                if (name === "is_divisible") value = value ? "分割可" : "分割不可";
                if (name === "near_expiry_days") value = `${value}日`;
                document.querySelector(`#item-current-${name}`).textContent = value;
            }
            current.hidden = false;
            checkedCurrent = true;
            showStatus("現在の保存内容を取得しました。保持している入力と照合してください。この取得だけで前の保存の成否は断定できません。");
        } catch {
            showStatus("保存内容を確認できませんでした。保存結果は不明のままです。通信の復旧後に、時間をおいて再確認してください。");
        } finally {
            state = "uncertain";
            updateControls();
        }
    });

    resume.addEventListener("click", () => {
        if (state !== "uncertain" || (edit && !checkedCurrent)) return;
        const message = edit
            ? "現在の保存内容と入力を照合しましたか？ 前の保存が後から反映される可能性もあります。もう一度保存すると変更を上書きする場合があります。入力を修正して再操作できる状態に戻しますか？"
            : "一覧と編集画面で登録内容を確認しましたか？ 同名品目だけでは今回の保存成功とは断定できません。再登録すると重複する可能性があります。入力を修正して再操作できる状態に戻しますか？";
        if (!window.confirm(message)) return;
        state = "idle";
        error.hidden = true;
        recovery.hidden = true;
        showStatus("入力を保持しています。登録内容を確認したうえで、必要な場合だけ修正して保存してください。");
        updateControls();
        submit.focus();
    });
    updateControls();
})();
