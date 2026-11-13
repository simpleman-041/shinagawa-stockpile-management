"""GIS01/02と検証済み固定版の読取。API1.0 §9。DB・原版を更新しない。"""

import csv
import hashlib
import io
import json
import math
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

from app import db
from app.services.stocks import StockError
from app.services.warehouse_settings import warehouse_dto


COLORS = ("#EFF3FF", "#BDD7E7", "#6BAED6", "#3182BD", "#08519C")
FILES = {"manifest.json": "application/json", "areas.geojson": "application/geo+json", "population.csv": "text/csv; charset=utf-8"}


def warehouses(connection):
    with db.transaction(connection, write=False):
        located, unlocated = [], []
        for row in connection.execute("SELECT * FROM warehouses ORDER BY warehouse_id"):
            lat, lon = row["latitude"], row["longitude"]
            if (lat is None) != (lon is None) or (lat is not None and (not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180)):
                raise StockError("DATA_INTEGRITY_ERROR", "倉庫の緯度・経度が不正です。倉庫編集で確認してください。", status=500)
            (unlocated if lat is None else located).append(warehouse_dto(row))
        return {"located": located, "unlocated": unlocated, "stock_data_kind": "sample"}


def unavailable():
    return StockError("GIS_DATA_UNAVAILABLE", "人口・境界データが未配置または不整合です。管理担当者に固定版の確認を依頼してください。倉庫表示は利用できます。", status=503)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("date")
    return date.fromisoformat(value)


def _geometry(geometry):
    if set(geometry) != {"type", "coordinates"} or geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError("geometry")
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    if not polygons:
        raise ValueError("empty polygons")
    for polygon in polygons:
        if not polygon:
            raise ValueError("empty polygon")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("ring")
            for pair in ring:
                if not isinstance(pair, list) or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair) or not -180 <= pair[0] <= 180 or not -90 <= pair[1] <= 90:
                    raise ValueError("coordinate")
            if len({tuple(p) for p in ring}) < 3:
                raise ValueError("degenerate ring")


def load_dataset(root, dataset_id):
    """全ファイルを一括検証し、配信にも同じ読取バイト列を使用する。"""
    try:
        if not isinstance(dataset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", dataset_id):
            raise ValueError("dataset id")
        root = Path(root).resolve()
        directory = (root / dataset_id).resolve()
        if not directory.is_relative_to(root):
            raise ValueError("path")
        raw = {}
        for filename in FILES:
            target = directory / filename
            if not target.resolve().is_relative_to(directory):
                raise ValueError("symlink")
            raw[filename] = target.read_bytes()
        manifest = _json(raw["manifest.json"])
        expected = {"dataset_id", "version", "population_date", "boundary_version", "area_code_system", "sources", "area_definition", "area_unit", "crs", "sha256"}
        if set(manifest) != expected or manifest["dataset_id"] != dataset_id or manifest["area_unit"] != "km2" or manifest["crs"] != "EPSG:4326":
            raise ValueError("manifest")
        _date(manifest["population_date"])
        if any(not _text(manifest[k]) for k in ("version", "boundary_version", "area_code_system", "area_definition")) or not isinstance(manifest["sources"], list) or not manifest["sources"]:
            raise ValueError("source metadata")
        for source in manifest["sources"]:
            if set(source) != {"url", "usage_terms"} or any(not _text(source[k]) or not source[k].startswith("https://") for k in source):
                raise ValueError("source")
        if set(manifest["sha256"]) != {"areas_geojson", "population_csv"}:
            raise ValueError("hash keys")
        for key, filename in (("areas_geojson", "areas.geojson"), ("population_csv", "population.csv")):
            if hashlib.sha256(raw[filename]).hexdigest() != manifest["sha256"][key]:
                raise ValueError("hash mismatch")
        areas = _json(raw["areas.geojson"])
        if set(areas) != {"type", "features"} or areas["type"] != "FeatureCollection" or not isinstance(areas["features"], list) or not areas["features"]:
            raise ValueError("FeatureCollection")
        codes = set()
        for feature in areas["features"]:
            if set(feature) != {"type", "id", "properties", "geometry"} or feature["type"] != "Feature" or not _text(feature["id"]) or feature["id"] in codes:
                raise ValueError("feature/code")
            codes.add(feature["id"])
            p = feature["properties"]
            if set(p) != {"area_name", "area_km2"} or not _text(p["area_name"]):
                raise ValueError("properties")
            a = p["area_km2"]
            if a is not None and (type(a) not in (int, float) or not math.isfinite(a) or a < 0):
                raise ValueError("area")
            _geometry(feature["geometry"])
        reader = csv.DictReader(io.StringIO(raw["population.csv"].decode("utf-8"), newline=""))
        if reader.fieldnames != ["area_code", "population", "population_date"]:
            raise ValueError("CSV headers")
        population = {}
        for row in reader:
            if set(row) != set(reader.fieldnames) or row["area_code"] not in codes or row["area_code"] in population or row["population_date"] != manifest["population_date"]:
                raise ValueError("CSV code/date")
            value = row["population"]
            if value != "" and (not re.fullmatch(r"0|[1-9][0-9]*", value) or len(value) > 16 or int(value) > 9007199254740991):
                raise ValueError("population")
            population[row["area_code"]] = None if value == "" else int(value)
        with localcontext() as context:
            context.prec = 650
            densities = [Decimal(population[f["id"]]) / Decimal(str(f["properties"]["area_km2"])) for f in areas["features"]
                         if population.get(f["id"]) is not None and f["properties"]["area_km2"] not in (None, 0)]
            maximum = max(densities) if densities else None
            if maximum is not None and not math.isfinite(float(maximum)):
                raise ValueError("density range")
            count = 0 if maximum is None else 1 if maximum == 0 else 5
            def dec(v):
                return format(v.quantize(Decimal(".01"), rounding=ROUND_HALF_UP), "f")
            classes = [{"lower": dec(maximum * n / count), "upper": dec(maximum * (n + 1) / count), "color": COLORS[n]} for n in range(count)]
        dataset = {"dataset_id": dataset_id, "manifest_url": f"/gis/{dataset_id}/manifest.json", "areas_url": f"/gis/{dataset_id}/areas.geojson", "population_url": f"/gis/{dataset_id}/population.csv",
                   "legend": {"population_date": manifest["population_date"], "unit": "people_per_km2", "classes": classes, "unknown_color": "#BDBDBD"}}
        return dataset, raw
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, ArithmeticError):
        raise unavailable() from None
