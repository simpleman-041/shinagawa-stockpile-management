const {test} = require("node:test");
const assert = require("node:assert/strict");

require("../app/static/js/warehouse-catchment.js");
const {estimate} = globalThis.UnfireCatchment;
const center = {latitude: 0, longitude: 0};
const rectangle = (west, south, east, north) => [
  [west, south], [east, south], [east, north], [west, north], [west, south],
];
const polygon = (id, ...rings) => ({id, geometry: {type: "Polygon", coordinates: rings}});

test("円が町丁目内に収まる場合と境界で二分される場合の面積按分", () => {
  const whole = polygon("a", rectangle(-0.01, -0.01, 0.01, 0.01));
  const half = polygon("a", rectangle(0, -0.01, 0.01, 0.01));
  const populations = new Map([["a", {population: 10000}]]);

  // 赤道付近では1度が約111195 m。正方形に占める円の面積率は約15.88%と63.52%。
  assert.deepEqual(estimate([whole], populations, center, 500), {state: "available", population: 1588});
  assert.deepEqual(estimate([whole], populations, center, 1000), {state: "available", population: 6352});
  // 区域と円の両方が二分されるため、按分率は同じ。
  assert.deepEqual(estimate([half], populations, center, 500), {state: "available", population: 1588});
});

test("穴を除いて按分し、飛び地の面積は区域全体に含める", () => {
  const outer = rectangle(-0.01, -0.01, 0.01, 0.01);
  const hole = rectangle(-0.001, -0.001, 0.001, 0.001);
  const populations = new Map([["hole", {population: 10000}], ["multi", {population: 200}]]);
  // 円と正方形から同じ穴の面積を引くと、面積率は約15.03%。
  for (const ring of [hole, [...hole].reverse()]) {
    assert.deepEqual(estimate([polygon("hole", outer, ring)], populations, center, 500),
      {state: "available", population: 1503});
  }

  const multi = {id: "multi", geometry: {type: "MultiPolygon", coordinates: [
    [hole], [rectangle(0.019, -0.001, 0.021, 0.001)],
  ]}};
  assert.deepEqual(estimate([multi], populations, center, 500), {state: "available", population: 100});
});

test("収録範囲外、人口欠損、確認済み0を区別する", () => {
  const near = rectangle(-0.001, -0.001, 0.001, 0.001);
  const outside = polygon("outside", rectangle(0.019, -0.001, 0.021, 0.001));
  const zero = polygon("zero", near);
  const missing = polygon("missing", near);
  const populations = new Map([["zero", {population: 0}]]);

  assert.deepEqual(estimate([outside], populations, center, 500), {state: "outside"});
  assert.deepEqual(estimate([zero, outside], populations, center, 500), {state: "available", population: 0});
  assert.deepEqual(estimate([zero, missing], populations, center, 500), {state: "incomplete"});
});
