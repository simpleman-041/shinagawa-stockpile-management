const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.events = {}; this.dataset = {}; this.elements = {}; this.value = ""; this.hidden = false; this.disabled = false; this.attributes = {}; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(type, fn) { (this.events[type] ??= []).push(fn); }
  querySelector() { return this.submitButton ??= new Element("button"); }
  async dispatch(type) { for (const fn of this.events[type] || []) await fn({preventDefault() {}, currentTarget: this}); await settle(); }
}
async function settle() { for (let i = 0; i < 6; i++) await new Promise(setImmediate); }
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => structuredClone(data)});
async function harness(key, transport, form = false, timers = {}) {
  const plural = {warehouse: "warehouses", item: "items", shelter: "shelters"}[key];
  const html = fs.readFileSync(path.join(__dirname, `../../app/templates/${plural}${form ? "_form" : ""}.html`), "utf8");
  const nodes = Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const calls = [], location = {href: "unchanged"}, pending = new Set();
  if (form) {
    const f = nodes[`${key}-form`]; f.dataset = {mode: "create"};
    for (const name of ["name", "facility_type", "address", "latitude", "longitude", "capacity_m3"]) f.elements[name] = new Element("input");
    Object.assign(f.elements.name, {value: "架空倉庫"}); Object.assign(f.elements.facility_type, {value: "倉庫"}); Object.assign(f.elements.address, {value: "架空住所"});
  }
  class FormData { constructor(form) { this.form = form; } get(name) { return this.form.elements[name]?.value ?? null; } }
  const context = {document: {querySelector: s => nodes[s.slice(1)] || null, createElement: tag => new Element(tag), createTextNode: text => text},
    fetch: async (url, options) => {
      calls.push({url, options}); const request = Promise.resolve().then(() => transport(url, options)); pending.add(request);
      try { return await request; } finally { pending.delete(request); }
    }, window: {location, confirm: () => true},
    URLSearchParams, FormData, AbortController, setTimeout: timers.setTimeout || setTimeout, clearTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, `../../app/static/js/${plural}${form ? "-form" : ""}.js`), "utf8"), context);
  await settle(); while (pending.size) { await Promise.allSettled([...pending]); await settle(); }
  return {nodes, calls, location, settle};
}
module.exports = {harness, response, settle, Element};
