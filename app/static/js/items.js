(function () {
    "use strict";

    const form = document.querySelector("#item-search-form");
    const loading = document.querySelector("#item-loading");
    const empty = document.querySelector("#item-empty");
    const error = document.querySelector("#item-error");
    const table = document.querySelector("#item-table-wrap");
    const body = document.querySelector("#item-table-body");
    const count = document.querySelector("#item-count");

    function cell(text) {
        const element = document.createElement("td");
        element.textContent = text ?? "-";
        return element;
    }

    function render(items, total) {
        body.replaceChildren();
        count.textContent = `${total}件`;
        empty.hidden = items.length !== 0;
        table.hidden = items.length === 0;

        for (const item of items) {
            const row = document.createElement("tr");
            row.appendChild(cell(item.name));
            row.appendChild(cell(item.category));
            row.appendChild(cell(item.quantity_unit));
            row.appendChild(cell(item.is_divisible ? "可" : "不可"));
            row.appendChild(cell(`${item.near_expiry_days}日`));
            row.appendChild(cell(item.registration_state === "active" ? "登録中" : "登録終了"));

            const actions = document.createElement("td");
            const edit = document.createElement("a");
            edit.href = `/items/${item.item_id}/edit`;
            edit.textContent = "編集";
            actions.appendChild(edit);

            if (item.registration_state === "active") {
                const close = document.createElement("button");
                close.type = "button";
                close.dataset.itemId = item.item_id;
                close.textContent = "登録終了";
                close.addEventListener("click", () => closeItem(item.item_id));
                actions.appendChild(document.createTextNode(" "));
                actions.appendChild(close);
            }
            row.appendChild(actions);
            body.appendChild(row);
        }
    }

    async function loadItems() {
        loading.hidden = false;
        empty.hidden = true;
        table.hidden = true;
        error.hidden = true;

        const params = new URLSearchParams();
        const query = document.querySelector("#item-query").value;
        const state = document.querySelector("#item-state").value;
        if (query) params.set("q", query);
        if (state) params.set("registration_state", state);

        try {
            const response = await fetch(`/api/v1/items?${params}`);
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error?.message || "品目一覧を取得できませんでした。");
            }
            render(result.data, result.page.total);
        } catch (loadError) {
            error.textContent = loadError.message;
            error.hidden = false;
        } finally {
            loading.hidden = true;
        }
    }

    async function closeItem(itemId) {
        if (!window.confirm("この品目を登録終了しますか？")) return;
        const response = await fetch(`/api/v1/items/${itemId}/closure`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: "{}",
        });
        if (!response.ok) {
            const result = await response.json();
            error.textContent = result.error?.message || "登録終了に失敗しました。";
            error.hidden = false;
            return;
        }
        await loadItems();
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        loadItems();
    });
    loadItems();
})();
