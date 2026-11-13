(function () {
    "use strict";

    const form = document.querySelector("#item-search-form");
    const loading = document.querySelector("#item-loading");
    const empty = document.querySelector("#item-empty");
    const error = document.querySelector("#item-error");
    const table = document.querySelector("#item-table-wrap");
    const body = document.querySelector("#item-table-body");
    const count = document.querySelector("#item-count");
    const previous = document.querySelector("#item-previous");
    const next = document.querySelector("#item-next");
    const retry = document.querySelector("#item-recheck");
    let offset = 0, total = 0, loadingPage = false, filters = new URLSearchParams();
    const closing = new Set(), uncertain = new Set(), confirmedClosed = new Set();

    async function requestItem(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal});
            return {response, result: await response.json()};
        } finally { clearTimeout(timer); }
    }

    function pageButtons() {
        previous.disabled = loadingPage || closing.size > 0 || offset === 0;
        next.disabled = loadingPage || closing.size > 0 || offset + 50 >= total;
    }

    function cell(text) {
        const element = document.createElement("td");
        element.textContent = text ?? "-";
        return element;
    }

    function render(items, total) {
        body.replaceChildren();
        count.textContent = `${total}件${items.length ? ` ／ ${offset + 1}〜${offset + items.length}件目` : ""}`;
        empty.hidden = items.length !== 0;
        table.hidden = items.length === 0;

        for (const item of items) {
            const row = document.createElement("tr");
            row.appendChild(cell(item.name));
            row.appendChild(cell(item.category));
            row.appendChild(cell(item.quantity_unit));
            row.appendChild(cell(item.is_divisible ? "可" : "不可"));
            row.appendChild(cell(`${item.near_expiry_days}日`));
            row.appendChild(cell(item.registration_state === "active" && !confirmedClosed.has(item.item_id) ? "登録中" : "登録終了"));

            const actions = document.createElement("td");
            const edit = document.createElement("a");
            edit.href = `/items/${item.item_id}/edit`;
            edit.textContent = "編集";
            actions.appendChild(edit);

            if (item.registration_state === "active" && !confirmedClosed.has(item.item_id)) {
                const close = document.createElement("button");
                close.type = "button";
                close.dataset.itemId = item.item_id;
                close.textContent = "登録終了";
                close.disabled = closing.has(item.item_id) || uncertain.has(item.item_id);
                close.addEventListener("click", () => closeItem(item.item_id, close));
                actions.appendChild(document.createTextNode(" "));
                actions.appendChild(close);
            }
            row.appendChild(actions);
            body.appendChild(row);
        }
    }

    async function loadItems(start = offset, selectedFilters = filters) {
        if (loadingPage) return;
        loadingPage = true; pageButtons();
        loading.hidden = false;
        empty.hidden = true;
        table.hidden = true;
        error.hidden = true;

        const params = new URLSearchParams(selectedFilters);
        params.set("limit", "50"); params.set("offset", String(start));

        try {
            const response = await fetch(`/api/v1/items?${params}`);
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error?.message || "品目一覧を取得できませんでした。");
            }
            total = result.page.total;
            if (start > 0 && start >= total) {
                loadingPage = false;
                return await loadItems(Math.max(0, Math.ceil(total / 50) * 50 - 50), selectedFilters);
            }
            filters = new URLSearchParams(selectedFilters); offset = start;
            render(result.data, result.page.total);
            return true;
        } catch (loadError) {
            error.textContent = loadError.message;
            error.hidden = false;
            return false;
        } finally {
            loading.hidden = true; loadingPage = false; pageButtons();
        }
    }

    async function recheck(itemId) {
        const {response, result} = await requestItem(`/api/v1/items/${itemId}`, {headers: {Accept: "application/json"}});
        if (!response.ok || !["active", "closed"].includes(result.data?.registration_state)) throw new Error("状態確認失敗");
        uncertain.delete(itemId);
        if (result.data.registration_state === "closed") confirmedClosed.add(itemId);
        return result.data.registration_state;
    }

    async function closeItem(itemId, button) {
        if (closing.has(itemId) || uncertain.has(itemId) || confirmedClosed.has(itemId)) return;
        if (!window.confirm("この品目を登録終了しますか？")) return;
        closing.add(itemId); button.disabled = true; pageButtons(); error.hidden = true;
        try {
            const {response, result} = await requestItem(`/api/v1/items/${itemId}/closure`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" }, body: "{}",
            });
            if (!response.ok) {
                if (response.status >= 500) throw new Error("サーバーで登録終了を確認できませんでした。");
                error.textContent = result.error?.message || "登録終了に失敗しました。入力と品目の状態を確認してください。";
                error.hidden = false; return;
            }
            if (result.data?.registration_state !== "closed") throw new Error("応答不正");
            confirmedClosed.add(itemId);
            closing.delete(itemId);
            await loadItems();
        } catch {
            uncertain.add(itemId);
            let message = "通信・サーバー応答を確認できませんでした。";
            try {
                const state = await recheck(itemId);
                closing.delete(itemId);
                await loadItems();
                message += state === "closed" ? " 再取得で登録終了済みと確認しました。再送は不要です。" : " 再取得で登録中と確認しました。もう一度操作できます。";
            } catch {
                message += " 結果は不明です。「品目の状態を再確認」で確認してから再操作してください。";
            }
            error.textContent = message;
            error.hidden = false;
        } finally {
            closing.delete(itemId);
            button.disabled = uncertain.has(itemId) || confirmedClosed.has(itemId); retry.hidden = uncertain.size === 0; pageButtons();
        }
    }

    retry.addEventListener("click", async () => {
        if (closing.size || loadingPage) return;
        retry.disabled = true;
        try {
            for (const id of [...uncertain]) await recheck(id);
            await loadItems();
        } catch {
            error.textContent = "状態を確認できませんでした。通信の復旧後に再確認してください。"; error.hidden = false;
        } finally { retry.disabled = false; retry.hidden = uncertain.size === 0; }
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (closing.size || loadingPage) return;
        const selectedFilters = new URLSearchParams();
        const query = document.querySelector("#item-query").value;
        const state = document.querySelector("#item-state").value;
        if (query) selectedFilters.set("q", query);
        if (state) selectedFilters.set("registration_state", state);
        return loadItems(0, selectedFilters);
    });
    previous.addEventListener("click", () => loadItems(Math.max(0, offset - 50)));
    next.addEventListener("click", () => loadItems(offset + 50));
    loadItems();
})();
