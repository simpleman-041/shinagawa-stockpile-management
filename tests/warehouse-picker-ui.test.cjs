const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../app/static/js/warehouse-picker.js"), "utf8");

function setup(selected = "") {
  class Element extends EventTarget {
    constructor() {
      super();
      this.children = [];
      this.attributes = new Map();
      this.hidden = false;
      this.value = "";
    }
    setAttribute(name, value) { this.attributes.set(name, value); }
    removeAttribute(name) { this.attributes.delete(name); }
    setCustomValidity(message) { this.error = message; }
    matches(selector) { return selector === ":disabled" && this.disabled; }
    replaceChildren() { this.children = []; }
    append(child) { this.children.push(child); }
    focus() { this.dispatchEvent(new Event("focus")); }
    scrollIntoView() {}
  }
  const label = new Element(), select = new Element(), input = new Element(), clear = new Element();
  const control = new Element(), status = new Element(), list = new Element();
  select.form = new EventTarget();
  select.options = [
    { value: "", textContent: "すべて" },
    { value: "9007199254740993", textContent: "Ａ東倉庫" },
    { value: "2", textContent: "Ａ東倉庫" },
    { value: "3", textContent: "西倉庫" }
  ];
  select.value = selected;
  Object.defineProperty(select, "selectedOptions", { get: () => select.options.filter((option) => option.value === select.value) });
  input.disabled = true;
  input.id = "warehouse-query";
  list.id = "warehouse-options";
  control.querySelector = (selector) => ({ input, button: clear, ul: list, "[role=status]": status }[selector]);
  const picker = { querySelector: (selector) => ({ label, select, ".warehouse-picker-control": control }[selector]) };
  const document = { querySelectorAll: () => [picker], createElement: () => new Element() };
  const changes = [];
  select.addEventListener("change", () => changes.push(select.value));
  vm.runInNewContext(script, { document, Event, queueMicrotask });
  select.dispatchEvent(new Event("warehouse-options-ready"));
  const setQuery = (value) => { input.value = value; input.dispatchEvent(new Event("input")); };
  const press = (key) => input.dispatchEvent(Object.assign(new Event("keydown", { cancelable: true }), { key }));
  return { label, select, input, clear, list, status, changes, setQuery, press };
}

test("倉庫名を部分一致で絞り込み、同名の候補をIDで区別してクリックやキーで選択する", () => {
  const ui = setup();
  assert.equal(ui.label.htmlFor, ui.input.id);
  ui.setQuery("a東");
  assert.equal(ui.list.children.length, 2);
  assert.match(ui.list.children[0].textContent, /9007199254740993/);
  assert.equal(ui.press("ArrowDown"), false);
  assert.equal(ui.input.attributes.get("aria-activedescendant"), ui.list.children[0].id);
  assert.equal(ui.press("Enter"), false);
  assert.equal(ui.select.value, "9007199254740993");
  assert.equal(ui.input.value, "Ａ東倉庫");
  assert.equal(ui.input.error, "");
  assert.equal(ui.list.hidden, true);

  ui.setQuery("東倉");
  ui.list.children[1].dispatchEvent(new Event("click"));
  assert.equal(ui.select.value, "2");
  assert.deepEqual(ui.changes, ["9007199254740993", "", "2"]);
});

test("候補外の入力は選択を解除し、解除ボタンとフォームのリセットで選び直せる", async () => {
  const ui = setup("2");
  assert.equal(ui.input.value, "Ａ東倉庫");
  ui.setQuery("登録外");
  assert.equal(ui.select.value, "");
  assert.match(ui.status.textContent, /一致する倉庫がありません/);
  assert.match(ui.input.error, /候補から倉庫を選択/);
  ui.clear.dispatchEvent(new Event("click"));
  assert.equal(ui.input.value, "");
  assert.equal(ui.input.error, "");
  assert.equal(ui.clear.hidden, true);

  ui.setQuery("西");
  assert.equal(ui.press("Escape"), false);
  assert.equal(ui.list.hidden, true);
  ui.press("ArrowUp");
  ui.press("Enter");
  assert.equal(ui.select.value, "3");
  ui.select.form.dispatchEvent(new Event("reset"));
  ui.select.value = "";
  await Promise.resolve();
  assert.equal(ui.input.value, "");
  assert.equal(ui.select.value, "");
});
