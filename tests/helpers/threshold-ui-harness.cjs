const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const {Element} = require("./master-ui-harness.cjs");
async function harness(fetch, html) {
  const template = html || fs.readFileSync(path.join(__dirname, "../../app/templates/warehouse_detail.html"), "utf8");
  const nodes = Object.fromEntries([...template.matchAll(/<([a-z]+)\b[^>]*\bid="([^"]+)"/g)].map(m => [m[2], new Element(m[1])]));
  const select = nodes["threshold-item"];
  select.append = function (...children) { this.children.push(...children); if (!this.value) this.value = children[0]?.value || ""; };
  const calls = [], confirmations = []; let confirmed = true;
  await vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../app/static/js/warehouse-thresholds.js"), "utf8"), {
    document: {body: {dataset: {warehouseId: "1"}}, getElementById: id => nodes[id], createElement: tag => new Element(tag)},
    fetch: (url, options) => { calls.push({url, options}); return fetch(url, options); },
    window: {confirm: message => { confirmations.push(message); return confirmed; }}, AbortController, setTimeout, clearTimeout,
  });
  return {nodes, calls, confirmations, setConfirmed: value => confirmed = value};
}
module.exports = {harness};
