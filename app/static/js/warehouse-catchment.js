(() => {
  "use strict";

  const earthRadius = 6371000;
  const radians = Math.PI / 180;

  function localProjection(latitude, longitude) {
    const sinCenter = Math.sin(latitude * radians);
    const cosCenter = Math.cos(latitude * radians);

    // 倉庫中心からの距離と方位を保って、座標をメートルに変換する。
    return ([lon, lat]) => {
      const difference = (lon - longitude) * radians;
      const sinLat = Math.sin(lat * radians);
      const cosLat = Math.cos(lat * radians);
      const east = cosLat * Math.sin(difference);
      const north = cosCenter * sinLat - sinCenter * cosLat * Math.cos(difference);
      const distance = Math.hypot(east, north);
      if (distance === 0) return [0, 0];
      const angle = Math.atan2(distance, sinCenter * sinLat + cosCenter * cosLat * Math.cos(difference));
      const scale = earthRadius * angle / distance;
      return [east * scale, north * scale];
    };
  }

  const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1];

  function clippedEdgeArea(a, b, radiusSquared) {
    const change = [b[0] - a[0], b[1] - a[1]];
    const lengthSquared = dot(change, change);
    if (lengthSquared === 0) return 0;

    // 円との交点で辺を分割し、内側は三角形、外側は扇形の符号付き面積を足す。
    const nearest = -dot(a, change) / lengthSquared;
    const offsetSquared = (radiusSquared - cross(a, b) ** 2 / lengthSquared) / lengthSquared;
    const cuts = [0];
    if (offsetSquared > 0) {
      const offset = Math.sqrt(offsetSquared);
      for (const cut of [nearest - offset, nearest + offset]) {
        if (cut > 0 && cut < 1) cuts.push(cut);
      }
    }
    cuts.push(1);

    const pointAt = fraction => [a[0] + change[0] * fraction, a[1] + change[1] * fraction];
    let area = 0;
    for (let i = 1; i < cuts.length; i++) {
      const start = pointAt(cuts[i - 1]);
      const end = pointAt(cuts[i]);
      const middle = pointAt((cuts[i - 1] + cuts[i]) / 2);
      area += dot(middle, middle) < radiusSquared
        ? cross(start, end) / 2
        : radiusSquared * Math.atan2(cross(start, end), dot(start, end)) / 2;
    }
    return area;
  }

  function areasWithinRange(polygons, project, radiusSquared) {
    let total = 0;
    let overlap = 0;
    for (const polygon of polygons) {
      polygon.forEach((ring, index) => {
        const points = ring.map(project);
        let ringArea = 0;
        let ringOverlap = 0;
        for (let i = 1; i < points.length; i++) {
          ringArea += cross(points[i - 1], points[i]) / 2;
          ringOverlap += clippedEdgeArea(points[i - 1], points[i], radiusSquared);
        }
        // GeoJSONの最初のリングは外周、以降は穴。巻き方向に依存せず穴を引く。
        const sign = index === 0 ? 1 : -1;
        total += sign * Math.abs(ringArea);
        overlap += sign * Math.abs(ringOverlap);
      });
    }
    return {total, overlap};
  }

  function estimate(features, populations, {latitude, longitude}, radius) {
    const project = localProjection(latitude, longitude);
    const latitudeSpan = radius / earthRadius / radians;
    let total = 0;
    let hasCoverage = false;
    for (const feature of features) {
      const {type, coordinates} = feature.geometry;
      const polygons = type === "Polygon" ? [coordinates] : coordinates;
      // 緯度が集計範囲に届かない区域を除き、遠方の座標を局所投影しない。
      const outerPoints = polygons.flatMap(polygon => polygon[0]);
      if (!outerPoints.some(([, lat]) => lat >= latitude - latitudeSpan) ||
          !outerPoints.some(([, lat]) => lat <= latitude + latitudeSpan)) continue;
      const {total: area, overlap} = areasWithinRange(polygons, project, radius ** 2);
      // 非交差の辺が作る扇形の相殺で残る浮動小数点誤差を除く。
      if (overlap <= 1e-6) continue;
      const population = populations.get(feature.id)?.population;
      if (!Number.isSafeInteger(population) || area <= 0) return {state: "incomplete"};
      hasCoverage = true;
      total += population * Math.min(overlap / area, 1);
    }
    return hasCoverage ? {state: "available", population: Math.round(total)} : {state: "outside"};
  }

  globalThis.UnfireCatchment = {estimate};
})();
