/* 実画面のJSを実行するためのDOM代替。ブラウザ描画・入力制約を代替するものではない。 */
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");

async function harness(fetch, renderedHTML) {
  class Element {
    constructor(tag = "div") {
      this.tag = tag; this.children = []; this.elements = {}; this.events = {}; this.dataset = {};
      this.value = ""; this.textContent = ""; this.hidden = false; this.disabled = false;
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = [...children]; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(type, fn) { (this.events[type] ??= []).push(fn); }
    reset() { for (const field of Object.values(this.elements)) field.value = ""; }
    async dispatch(type, target = this) {
      for (const fn of this.events[type] || []) await fn({preventDefault() {}, currentTarget: this, target});
    }
  }
  const template = renderedHTML || fs.readFileSync(path.join(__dirname, "../../app/templates/calculation_conditions.html"), "utf8");
  const nodes = Object.fromEntries([...template.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element()]));
  // 実テンプレートのフォームとnameを使い、IDやフィールドの接続漏れを検出する。
  for (const match of template.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/g)) {
    const id = match[1].match(/\bid="([^"]+)"/)[1], form = nodes[id]; form.tag = "form";
    for (const control of match[2].matchAll(/<(input|select|textarea)\b([^>]*)>/g)) {
      const name = control[2].match(/\bname="([^"]+)"/)?.[1];
      if (!name) continue;
      const controlId = control[2].match(/\bid="([^"]+)"/)?.[1];
      const element = controlId ? nodes[controlId] : new Element(control[1]);
      form.elements[name] = element;
    }
  }
  const confirmations = []; let confirmed = true;
  await vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../app/static/js/calculation-conditions.js"), "utf8"), {
    document: {getElementById: id => nodes[id], createElement: tag => new Element(tag)}, fetch,
    window: {confirm: message => { confirmations.push(message); return confirmed; }},
  });
  function set(formId, values) {
    for (const [field, value] of Object.entries(values)) nodes[formId].elements[field].value = value;
  }
  async function selectGroup(id) {
    nodes["condition-group"].value = id; await nodes["group-select-form"].dispatch("submit");
  }
  async function selectItem(id) {
    nodes["membership-item"].value = id; await nodes["membership-item"].dispatch("change");
  }
  return {nodes, set, selectGroup, selectItem, confirmations, setConfirmed: value => confirmed = value};
}
module.exports = {harness};
