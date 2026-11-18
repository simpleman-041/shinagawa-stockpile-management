/* Actual form script on a DOM substitute; this does not verify browser layout. */
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const {Element, response, settle} = require("./master-ui-harness.cjs");
const fields = ["name", "category", "quantity_unit", "unit_volume_m3", "is_divisible", "near_expiry_days"];
const defaults = {name: "架空品目", category: "試験用", quantity_unit: "本", unit_volume_m3: "0.01", is_divisible: "false", near_expiry_days: "180"};
function item(values = {}) {
  return {item_id: "1", ...defaults, is_divisible: false, near_expiry_days: 180, registration_state: "active", ...values};
}
function formHarness({mode = "create", itemId = "1", transport, html, values = {}, confirm = () => true, timers = {}} = {}) {
  html ??= fs.readFileSync(path.join(__dirname, "../../app/templates/items_form.html"), "utf8");
  const nodes = {};
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*?\sid="([^"]+)"[^>]*)>([^<]*)/g)) {
    nodes[match[3]] = Object.assign(new Element(match[1]), {
      hidden: /\bhidden\b/.test(match[2]), disabled: /\bdisabled\b/.test(match[2]), textContent: match[4],
    });
  }
  // The unit harness models the create/edit branches; integration tests pass rendered HTML.
  if (mode === "create") {
    delete nodes["item-form-recheck"];
    delete nodes["item-form-current"];
  }
  const form = nodes["item-form"];
  form.dataset = {mode, ...(mode === "edit" ? {itemId} : {})};
  for (const name of fields) form.elements[name] = Object.assign(new Element("input"), {value: {...defaults, ...values}[name]});
  const calls = [], location = {href: "unchanged"}, confirmations = [];
  class FormData {
    constructor(source) {
      this.values = new Map(Object.entries(source.elements).filter(([, control]) => !control.disabled).map(([name, control]) => [name, control.value]));
    }
    get(name) { return this.values.get(name) ?? null; }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../app/static/js/items-form.js"), "utf8"), {
    document: {querySelector: selector => nodes[selector.slice(1)] || null}, FormData, AbortController,
    setTimeout: timers.setTimeout || setTimeout, clearTimeout: timers.clearTimeout || clearTimeout,
    fetch: async (url, options) => { calls.push({url, options}); return transport(url, options); },
    window: {location, confirm: message => { confirmations.push(message); return confirm(message); }},
  });
  return {nodes, form, calls, location, confirmations, settle,
    submit: () => form.dispatch("submit"),
    recheck: () => nodes["item-form-recheck"].dispatch("click"),
    resume: () => nodes["item-form-resume"].dispatch("click"),
  };
}
module.exports = {formHarness, fields, defaults, item, response};
