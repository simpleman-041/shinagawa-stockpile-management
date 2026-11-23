"use strict";

for (const picker of document.querySelectorAll("[data-warehouse-picker]")) {
  const label = picker.querySelector("label");
  const select = picker.querySelector("select");
  const control = picker.querySelector(".warehouse-picker-control");
  const input = control.querySelector("input");
  const clear = control.querySelector("button");
  const list = control.querySelector("ul");
  const status = control.querySelector("[role=status]");
  const normalize = (value) => value.normalize("NFKC").trim().toLowerCase();
  let matches = [];
  let active = -1;

  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function show() {
    if (input.matches(":disabled")) return;
    const query = select.value ? "" : normalize(input.value);
    const options = Array.from(select.options).filter((option) => option.value && !option.disabled);
    matches = options.filter((option) => normalize(option.textContent).includes(query));
    list.replaceChildren();
    for (const [index, option] of matches.entries()) {
      const row = document.createElement("li");
      row.id = `${list.id}-${index}`;
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(option.value === select.value));
      row.textContent = `${option.textContent}（倉庫ID ${option.value}）`;
      row.addEventListener("mousedown", (event) => event.preventDefault());
      row.addEventListener("click", () => choose(option.value));
      list.append(row);
    }
    close();
    if (matches.length) {
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
    status.textContent = matches.length ? `候補 ${matches.length}件` :
      options.length ? "一致する倉庫がありません。入力を変えて検索してください。" : "選択できる倉庫がありません。";
  }

  function sync() {
    const option = select.selectedOptions[0];
    input.value = option?.value ? option.textContent : "";
    input.setCustomValidity("");
    input.removeAttribute("aria-invalid");
    clear.hidden = !input.value;
    status.textContent = option?.value ? `選択中：倉庫ID ${option.value}` :
      input.required ? "" : `未選択：${select.options[0].textContent}`;
    close();
  }

  function choose(value) {
    const previous = select.value;
    select.value = value;
    sync();
    if (previous !== select.value) select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function search() {
    if (select.value) {
      select.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const hasQuery = input.value !== "";
    input.setCustomValidity(hasQuery ? "候補から倉庫を選択するか、入力を解除してください。" : "");
    if (hasQuery) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
    clear.hidden = !hasQuery;
    show();
  }

  input.addEventListener("focus", show);
  input.addEventListener("click", () => { if (list.hidden) show(); });
  input.addEventListener("blur", () => {
    close();
    if (select.value) status.textContent = `選択中：倉庫ID ${select.value}`;
    else if (!input.value && !input.required) status.textContent = `未選択：${select.options[0].textContent}`;
  });
  input.addEventListener("input", (event) => { if (!event.isComposing) search(); });
  input.addEventListener("compositionend", search);
  input.addEventListener("keydown", (event) => {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) show();
      if (!matches.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      const first = step === 1 ? 0 : matches.length - 1;
      active = active < 0 ? first : Math.max(0, Math.min(matches.length - 1, active + step));
      for (const [index, row] of Array.from(list.children).entries()) {
        row.setAttribute("aria-selected", String(index === active));
      }
      const row = list.children[active];
      input.setAttribute("aria-activedescendant", row.id);
      row.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter" && !list.hidden && active !== -1) {
      event.preventDefault();
      choose(matches[active].value);
    } else if (event.key === "Escape" && !list.hidden) {
      event.preventDefault();
      close();
    }
  });
  clear.addEventListener("click", () => {
    input.focus();
    choose("");
  });
  select.addEventListener("warehouse-options-ready", () => {
    input.disabled = false;
    sync();
  });
  select.form?.addEventListener("reset", () => queueMicrotask(sync));

  label.htmlFor = input.id;
  select.required = false;
  select.hidden = true;
  control.hidden = false;
}
