(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const node = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  const link = (url, text) => { const a = node("a", text); a.href = url; return a; };
  const colors = ["#EFF3FF", "#BDD7E7", "#6BAED6", "#3182BD", "#08519C"];
  let data = {located: [], unlocated: []}, regions = null, warehousesVersion = 0, populationVersion = 0, selectionVersion = 0;
  let searchVersion = 0, matchingWarehouseIds = null;
  function error(id, text = "") { $(id).textContent = text; $(id).hidden = !text; }
  function csv(text) {
    const rows = []; let row = [], value = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') { if (quoted && text[i + 1] === '"') { value += '"'; i++; } else quoted = !quoted; }
      else if (!quoted && (c === "," || c === "\n")) { row.push(value); value = ""; if (c === "\n") { rows.push(row); row = []; } }
      else if (c !== "\r" || quoted) value += c;
    }
    if (quoted) throw Error("人口CSVの引用符が不正です。");
    if (value || row.length) { row.push(value); rows.push(row); }
    if (rows.shift()?.join(",") !== "area_code,population,population_date") throw Error("人口CSVの形式が不正です。");
    const result = new Map();
    for (const r of rows) {
      if (r.length !== 3 || result.has(r[0]) || (r[1] !== "" && (!/^(0|[1-9][0-9]*)$/.test(r[1]) || !Number.isSafeInteger(Number(r[1]))))) throw Error("人口CSVの区域・数量が不正です。");
      result.set(r[0], {population: r[1] === "" ? null : Number(r[1]), date: r[2]});
    }
    return result;
  }
  function density(feature, populations) {
    const population = populations.get(feature.id)?.population, area = feature.properties.area_km2;
    return population === null || population === undefined || area === null || area <= 0 ? null : population / area;
  }
  function decimalRatio(value) {
    const [mantissa, exponent = "0"] = String(value).toLowerCase().split("e");
    const [whole, fraction = ""] = mantissa.split(".");
    const power = Number(exponent) - fraction.length;
    return {n: BigInt(whole + fraction) * 10n ** BigInt(Math.max(0,power)), d: 10n ** BigInt(Math.max(0,-power))};
  }
  function densityRatio(feature, populations) {
    if (density(feature,populations) === null) return null;
    const area = decimalRatio(feature.properties.area_km2);
    return {n: BigInt(populations.get(feature.id).population) * area.d, d: area.n};
  }
  function densityColor(ratio, maximum) {
    if (ratio === null) return "#BDBDBD";
    if (maximum.n === 0n) return colors[0];
    // 人口整数と面積の十進値を有理数で比較し、表示丸め・二進近似を階級に持ち込まない。
    const index = Number(ratio.n * maximum.d * 5n / (ratio.d * maximum.n));
    return colors[Math.min(4,index)];
  }
  // 純粋処理を画面スクリプト検証でも共用する。
  globalThis.UnfireGIS = {csv, density, densityRatio, densityColor};
  if (typeof L === "undefined") {
    error("warehouse-error", "地図ライブラリを読み込めませんでした。倉庫一覧から情報を確認してください。"); return;
  }
  const map = L.map("map").setView([35.609, 139.73], 13);
  const pins = L.featureGroup().addTo(map);
  L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", {maxZoom: 18, minZoom: 5, attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>'})
    .on("tileerror", () => error("tile-error", "背景地図を取得できません。倉庫・境界の表示と一覧は引き続き利用できます。")).addTo(map);
  async function api(url) {
    const response = await fetch(url, {headers: {Accept: "application/json"}});
    const value = await response.json();
    if (!response.ok) throw Error(value.error?.message || "情報を取得できませんでした。");
    return value.data;
  }
  function fit() { if (pins.getLayers().length) map.fitBounds(pins.getBounds(), {padding: [25,25], maxZoom: 15}); }
  async function selectWarehouse(warehouse) {
    const version = ++selectionVersion;
    $("map-info-title").textContent = warehouse.name;
    const content = $("map-info"); content.replaceChildren(node("p", warehouse.address), node("p", "サンプル在庫の概要を読み込み中…"));
    content.append(link(`/warehouses/${warehouse.warehouse_id}`, "倉庫詳細"), node("span", " ／ "), link(`/stocks?warehouse_id=${warehouse.warehouse_id}`, "在庫を見る"));
    try {
      const result = await api(`/api/v1/warehouses/${warehouse.warehouse_id}/summary`);
      if (version !== selectionVersion) return;
      content.replaceChildren(node("p", result.warehouse.facility_type), node("p", result.warehouse.address));
      const c = result.capacity;
      content.append(node("p", c.state === "computed" ? `容量 ${c.used_volume_m3} / ${c.capacity_m3} m³（${c.usage_rate}%）・${{available:"空きあり",full:"満杯",over:"容量超過"}[c.level]}` : `容量計算不可：${c.issues.map(i => i.message).join(" ")}`));
      content.append(node("p", `在庫は架空サンプル。期限判定日 ${result.base_date}（日本時間）。数量は品目の管理単位です。`));
      if (!result.items.length) content.append(node("p", "有効在庫・日常管理基準は未登録です。"));
      for (const item of result.items) content.append(node("p", `${item.item_name}：現物 ${item.physical_quantity} ${item.quantity_unit} ／ 割当済 ${item.allocated_total} ／ 未割当 ${item.unallocated_quantity}\n期限切れ ${item.expired_quantity} ／ 未確認 ${item.unconfirmed_quantity}${item.below_minimum ? " ／ 日常基準未満" : ""}`));
      content.append(link(`/warehouses/${warehouse.warehouse_id}`, "倉庫詳細"), node("span", " ／ "), link(`/stocks?warehouse_id=${warehouse.warehouse_id}`, "在庫を見る"));
    } catch (reason) { if (version === selectionVersion) content.append(node("p", `概要の取得に失敗しました。${reason.message}`)); }
  }
  function renderWarehouses() {
    pins.clearLayers();
    const q = $("map-query").value;
    const target = $("map-search-target").value || "warehouse";
    const matches = w => (target !== "warehouse" || !q || w.name.includes(q) || w.address.includes(q)) && (matchingWarehouseIds === null || matchingWarehouseIds.has(String(w.warehouse_id)));
    for (const key of ["located", "unlocated"]) {
      const list = $(key === "located" ? "located-list" : "unlocated-list"); list.replaceChildren();
      const rows = data[key].filter(matches);
      if (!rows.length) list.append(node("li", "該当する倉庫はありません。"));
      for (const warehouse of rows) {
        const li = document.createElement("li"), b = node("button", warehouse.name); b.type = "button";
        b.addEventListener("click", () => { selectWarehouse(warehouse); if (key === "located") map.setView([warehouse.latitude, warehouse.longitude], 15); });
        li.append(b); list.append(li);
        if (key === "located") L.marker([warehouse.latitude,warehouse.longitude], {icon: L.divIcon({className:"warehouse-pin",html:"倉",iconSize:[26,26]}),title:warehouse.name,alt:warehouse.name})
          .on("click", () => selectWarehouse(warehouse)).addTo(pins);
      }
    }
    $("warehouse-status").textContent = `表示倉庫 ${data.located.filter(matches).length}件 ／ 座標未確認 ${data.unlocated.filter(matches).length}件（在庫は架空サンプル）`;
  }
  async function searchWarehouses() {
    const version = ++searchVersion, q = $("map-query").value;
    const target = $("map-search-target").value || "warehouse", status = $("map-stock-status").value;
    error("warehouse-error");
    try {
      let ids = null;
      if (status === "below") {
        const summaries = await Promise.all([...data.located,...data.unlocated].map(w => api(`/api/v1/warehouses/${w.warehouse_id}/summary`)));
        ids = new Set(summaries.filter(s => s.items.some(i => i.below_minimum && (target !== "item" || !q || i.item_name.includes(q)))).map(s => String(s.warehouse.warehouse_id)));
      } else if ((target === "item" && q) || status) {
        ids = new Set(); let offset = 0, total;
        do {
          const params = new URLSearchParams({limit:"200",offset:String(offset)});
          if (status) params.set("expiry_status",status);
          const response = await fetch(`/api/v1/stocks?${params}`), result = await response.json();
          if (!response.ok) throw Error(result.error?.message || "在庫条件を取得できませんでした。");
          for (const s of result.data) if (target !== "item" || !q || s.item_name.includes(q)) ids.add(String(s.stock.warehouse_id));
          total = result.page.total; offset += result.data.length;
          if (!result.data.length) break;
        } while (offset < total);
      }
      if (version !== searchVersion) return;
      matchingWarehouseIds = ids; renderWarehouses(); fit();
    } catch (reason) { if (version === searchVersion) error("warehouse-error", `検索失敗：${reason.message} 前回の地図表示を保持しています。`); }
  }
  async function loadWarehouses() {
    const version = ++warehousesVersion;
    error("warehouse-error"); $("warehouse-status").textContent = "倉庫を読み込み中…";
    try { const next = await api("/api/v1/gis/warehouses"); if (version !== warehousesVersion) return; data = next; await searchWarehouses(); }
    catch (reason) { if (version === warehousesVersion) { error("warehouse-error", `倉庫取得失敗：${reason.message} 再取得で確認してください。`); $("warehouse-status").textContent = "取得できた前回の倉庫表示を保持しています。"; } }
  }
  async function verified(url, hash) {
    const response = await fetch(url);
    if (!response.ok) throw Error("固定版のファイルを取得できませんでした。");
    const bytes = await response.arrayBuffer();
    const actual = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), b => b.toString(16).padStart(2,"0")).join("");
    if (actual !== hash) throw Error("固定版のハッシュが一致しません。再取得してください。");
    return new TextDecoder().decode(bytes);
  }
  async function loadPopulation() {
    const version = ++populationVersion;
    error("population-error"); $("population-status").textContent = "人口レイヤーを読み込み中…";
    try {
      const dataset = await api("/api/v1/gis/datasets/current");
      const response = await fetch(dataset.manifest_url); if (!response.ok) throw Error("出典情報を取得できませんでした。");
      const manifest = await response.json();
      if (manifest.dataset_id !== dataset.dataset_id) throw Error("固定版が一致しません。");
      const [geo, csvText] = await Promise.all([verified(dataset.areas_url,manifest.sha256.areas_geojson),verified(dataset.population_url,manifest.sha256.population_csv)]);
      const areas = JSON.parse(geo), populations = csv(csvText);
      if ([...populations.values()].some(p => p.date !== manifest.population_date)) throw Error("人口基準日が一致しません。");
      const densities = areas.features.map(f => densityRatio(f,populations)).filter(v => v !== null);
      const maximum = densities.reduce((max,v) => max === null || v.n * max.d > max.n * v.d ? v : max,null);
      if (version !== populationVersion) return;
      const next = L.geoJSON(areas, {style: f => ({color:"#526674",weight:1,fillColor:densityColor(densityRatio(f,populations),maximum),fillOpacity:.55}), onEachFeature: (f, layer) => layer.on("click", () => {
        ++selectionVersion;
        $("map-info-title").textContent = f.properties.area_name;
        const p = populations.get(f.id)?.population, d = density(f,populations);
        $("map-info").replaceChildren(node("p",`区域コード ${f.id}`),node("p",`総人口 ${p === null || p === undefined ? "不明" : p.toLocaleString()+"人"}（${manifest.population_date}時点）`),node("p",`面積 ${f.properties.area_km2 ?? "不明"} km² ／ 密度 ${d === null ? "不明" : d.toFixed(2)+"人/km²"}`),node("p","供給対象区域や避難者数を示すものではありません。"));
      })});
      if (regions) map.removeLayer(regions); regions = next;
      if ($("population-toggle").checked) regions.addTo(map);
      $("population-status").textContent = `参考人口 ${manifest.population_date}時点 ／ 境界 ${manifest.boundary_version}`;
      $("map-legend").replaceChildren();
      for (const c of [...dataset.legend.classes,{lower:null,color:dataset.legend.unknown_color}]) {
        const n = node("span", c.lower === null ? "密度不明" : `${c.lower}〜${c.upper}`), swatch = node("span", ""); swatch.className="legend-color"; swatch.style.backgroundColor=c.color; n.prepend(swatch); $("map-legend").append(n);
      }
      const sources = $("map-source"); sources.replaceChildren(node("span", "『国勢調査町丁・字等別境界データセット』（CODH作成）／『令和2年国勢調査町丁・字等別境界データ』（e-Stat）を加工。 "));
      for (const s of manifest.sources) sources.append(link(s.url,"出典"),node("span"," ／ "),link(s.usage_terms,"利用条件"),node("span"," "));
      sources.append(node("span",manifest.area_definition));
    } catch (reason) { if (version === populationVersion) { if (regions) map.removeLayer(regions); regions=null; $("map-legend").replaceChildren(); $("map-source").replaceChildren(); error("population-error", `人口レイヤー取得失敗：${reason.message} 倉庫表示は引き続き利用できます。`); $("population-status").textContent="人口レイヤーは表示できません。"; } }
  }
  $("map-search").addEventListener("submit", e => { e.preventDefault(); searchWarehouses(); });
  $("map-clear").addEventListener("click", () => { ++searchVersion; $("map-query").value=""; $("map-search-target").value="warehouse"; $("map-stock-status").value=""; matchingWarehouseIds=null; error("warehouse-error"); renderWarehouses(); fit(); });
  $("map-fit").addEventListener("click",fit);
  $("map-refresh").addEventListener("click", () => { loadWarehouses(); loadPopulation(); });
  $("population-toggle").addEventListener("change", () => { if (regions) { if ($("population-toggle").checked) regions.addTo(map); else map.removeLayer(regions); } });
  loadWarehouses(); loadPopulation();
})();
