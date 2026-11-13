"""API1.0 GIS01/02・WH05、T23/24。隔離DB・架空区域で境界条件を検証。"""

import hashlib
import json
from datetime import date

import pytest

from app import create_app, db
from app.services import stocks
from app.services.gis import load_dataset


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app({"TESTING": True, "DATABASE": tmp_path / "gis.sqlite3", "GIS_DATA_ROOT": tmp_path / "gis", "GIS_CURRENT_DATASET": "test-v1"})
    monkeypatch.setattr(stocks,"today",lambda:date(2026,11,13))
    with application.app_context():
        db.init_db()
        with db.transaction(db.get_db()) as c:
            c.execute("INSERT INTO warehouses(warehouse_id,name,facility_type,address,latitude,longitude,capacity_m3) VALUES(1,'架空倉庫%','試験','架空住所',35.6,139.7,1),(2,'座標未確認','試験','架空住所',NULL,NULL,NULL)")
            c.execute("INSERT INTO shelters(shelter_id,name,address) VALUES(1,'架空避難所','試験')")
            c.execute("INSERT INTO items(item_id,name,category,quantity_unit,is_divisible,unit_volume_m3,near_expiry_days) VALUES(1,'試験飲料','試験','L',1,0.1,7),(2,'基準だけの品目','試験','箱',0,NULL,7)")
            c.execute("INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state,expiry_date) VALUES(1,1,1,'棚1',4,'dated','2026-11-12'),(2,1,1,'棚2',3,'unconfirmed',NULL),(3,1,1,'棚3',2,'none',NULL),(4,1,1,'棚4',1,'dated','2026-11-13')")
            c.execute("INSERT INTO stock_allocations VALUES(1,1,2)")
            c.execute("INSERT INTO stock_thresholds VALUES(1,1,5),(1,2,0)")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def dataset(app, *, population="001,10,2020-10-01\n002,50,2020-10-01\n", modify=None):
    root = app.config["GIS_DATA_ROOT"] / "test-v1"
    root.mkdir(parents=True, exist_ok=True)
    areas = {"type":"FeatureCollection","features":[{"type":"Feature","id":code,"properties":{"area_name":"試験区域"+code,"area_km2":area},"geometry":{"type":"Polygon","coordinates":[[[139,35],[140,35],[140,36],[139,35]]]}} for code,area in [("001",.5),("002",1)]]}
    manifest = {"dataset_id":"test-v1","version":"1","population_date":"2020-10-01","boundary_version":"試験境界1","area_code_system":"試験文字列コード","sources":[{"url":"https://example.com/source","usage_terms":"https://example.com/terms"}],"area_definition":"試験区域、架空データ","area_unit":"km2","crs":"EPSG:4326","sha256":{}}
    if modify:
        modify(manifest, areas)
    raw = json.dumps(areas).encode()
    csv = ("area_code,population,population_date\n"+population).encode()
    manifest["sha256"] = {"areas_geojson":hashlib.sha256(raw).hexdigest(),"population_csv":hashlib.sha256(csv).hexdigest()}
    (root / "areas.geojson").write_bytes(raw)
    (root / "population.csv").write_bytes(csv)
    (root / "manifest.json").write_text(json.dumps(manifest),encoding="utf8")
    return root


def stored(app):
    with app.app_context():
        c=db.get_db()
        return {r[0]:[tuple(v) for v in c.execute(f'SELECT * FROM "{r[0]}" ORDER BY 1')] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def test_locations_no_population_dependency_and_read_only(app,client):
    before = stored(app)
    r=client.get("/api/v1/gis/warehouses")
    assert r.status_code==200
    assert [w["warehouse_id"] for w in r.json["data"]["located"]]==["1"]
    assert r.json["data"]["located"][0]["latitude"]==35.6
    assert r.json["data"]["unlocated"][0]["latitude"] is None
    assert r.json["data"]["stock_data_kind"]=="sample"
    assert client.get("/api/v1/gis/datasets/current").status_code==503
    assert stored(app)==before


def test_dataset_hashes_types_sources_and_leading_zero_codes(app,client):
    root=dataset(app)
    r=client.get("/api/v1/gis/datasets/current")
    assert r.status_code==200,r.json
    d=r.json["data"]
    assert d["legend"]["classes"]==[{"lower":f"{n*10:.2f}","upper":f"{(n+1)*10:.2f}","color":color} for n,color in enumerate(["#EFF3FF","#BDD7E7","#6BAED6","#3182BD","#08519C"])]
    for name,mime in [("manifest.json","application/json"),("areas.geojson","application/geo+json"),("population.csv","text/csv")]:
        response=client.get("/gis/test-v1/"+name)
        assert response.status_code==200 and response.mimetype==mime
        assert response.data==(root/name).read_bytes()
    assert b'001' in client.get(d["population_url"]).data
    assert "data" not in client.get(d["manifest_url"]).json


@pytest.mark.parametrize("population,count",[("001,0,2020-10-01\n002,0,2020-10-01\n",1),("001,,2020-10-01\n002,,2020-10-01\n",0),("001,0,2020-10-01\n",1)])
def test_zero_and_unknown_densities(app,client,population,count):
    dataset(app,population=population)
    d=client.get("/api/v1/gis/datasets/current").json["data"]
    assert len(d["legend"]["classes"])==count
    assert d["legend"]["unknown_color"]=="#BDBDBD"


@pytest.mark.parametrize("area",[None,0])
def test_unknown_area_not_false_zero_density(app,client,area):
    dataset(app,modify=lambda m,a:[f["properties"].update(area_km2=area) for f in a["features"]])
    assert client.get("/api/v1/gis/datasets/current").json["data"]["legend"]["classes"]==[]


@pytest.mark.parametrize("population",["001,10,2020-10-01\n001,20,2020-10-01\n","001,-1,2020-10-01\n","001,1.1,2020-10-01\n","001,1,2021-10-01\n","003,1,2020-10-01\n","001,9007199254740992,2020-10-01\n"])
def test_invalid_population_not_published(app,client,population):
    dataset(app,population=population)
    for url in ["/api/v1/gis/datasets/current","/gis/test-v1/population.csv"]:
        r=client.get(url)
        assert r.status_code==503 and r.json["error"]["code"]=="GIS_DATA_UNAVAILABLE"


@pytest.mark.parametrize("change",[
    lambda m,a:m.update(crs="EPSG:4612"),lambda m,a:m.update(dataset_id="another"),
    lambda m,a:m.update(sources=[]),lambda m,a:m.update(population_date="2020-02-30"),
    lambda m,a:a["features"][1].update(id="001"),
    lambda m,a:a["features"][0]["properties"].update(area_km2=-1),
    lambda m,a:a["features"][0]["geometry"].update(type="Point"),
    lambda m,a:a["features"][0]["geometry"].update(coordinates=[[[200,35],[140,35],[140,36],[200,35]]]),
    lambda m,a:a["features"][0]["geometry"].update(coordinates=[[[139,35],[140,35],[140,36]]]),
])
def test_invalid_manifest_boundary_and_coordinates(app,client,change):
    dataset(app,modify=change)
    assert client.get("/api/v1/gis/datasets/current").status_code==503


def test_mismatched_hash_unknown_file_and_traversal(app,client):
    root=dataset(app)
    (root/"population.csv").write_text("invalid",encoding="utf8")
    assert client.get("/api/v1/gis/datasets/current").status_code==503
    assert client.get("/gis/test-v1/areas.geojson").status_code==503
    assert client.get("/gis/test-v1/private.txt").status_code==404
    for ident in ["../test-v1","..", "test/v1", "C:\\"]:
        with pytest.raises(Exception) as error:
            load_dataset(app.config["GIS_DATA_ROOT"],ident)
        assert error.value.code=="GIS_DATA_UNAVAILABLE"


def test_warehouse_summary_units_expiry_capacity_and_threshold_union(app,client):
    before=stored(app)
    r=client.get("/api/v1/warehouses/1/summary")
    assert r.status_code==200,r.json
    d=r.json["data"]
    assert d["capacity"]=={"state":"computed","used_volume_m3":"1.00","capacity_m3":"1.00","usage_rate":"100.00","level":"full","issues":[]}
    item=d["items"][0]
    assert item["physical_quantity"]=="10.00" and item["allocated_total"]=="2.00" and item["unallocated_quantity"]=="8.00"
    assert item["expired_quantity"]=="4.00" and item["unconfirmed_quantity"]=="3.00"
    assert item["near_expiry_quantity"]=="1.00" and item["daily_usable_quantity"]=="3.00"
    assert item["below_minimum"] and d["items"][1]["minimum_quantity"]=="0.00"
    assert not d["items"][1]["below_minimum"]
    assert stored(app)==before


@pytest.mark.parametrize("sql,code",[("UPDATE warehouses SET capacity_m3=NULL WHERE warehouse_id=1","CAPACITY_MISSING"),("UPDATE warehouses SET capacity_m3=0 WHERE warehouse_id=1","CAPACITY_ZERO"),("UPDATE items SET unit_volume_m3=NULL WHERE item_id=1","UNIT_VOLUME_MISSING")])
def test_missing_capacity_info_is_not_zero_rate(app,client,sql,code):
    with app.app_context(),db.transaction(db.get_db()) as c:c.execute(sql)
    result=client.get("/api/v1/warehouses/1/summary").json["data"]["capacity"]
    assert result["state"]=="unavailable" and result["usage_rate"] is None
    assert any(i["code"]==code for i in result["issues"])


def test_summary_excludes_deleted_and_overage_is_before_rounding(app,client):
    with app.app_context(),db.transaction(db.get_db()) as c:
        c.execute("INSERT INTO stocks(stock_id,warehouse_id,item_id,location,quantity,expiry_state,state) VALUES(5,1,1,'削除',100,'none','deleted')")
        c.execute("UPDATE warehouses SET capacity_m3=0.99999 WHERE warehouse_id=1")
    result=client.get("/api/v1/warehouses/1/summary").json["data"]
    assert result["items"][0]["physical_quantity"]=="10.00"
    assert result["capacity"]["usage_rate"]=="100.00" and result["capacity"]["level"]=="over"


def test_routing_errors_and_pages(client):
    for url in ["/api/v1/gis/warehouses?limit=1","/api/v1/warehouses/1/summary?unknown=1"]:
        assert client.get(url).status_code==422
    assert client.get("/api/v1/gis/warehouses",data="{}").status_code==400
    r=client.post("/api/v1/gis/warehouses")
    assert r.status_code==405 and r.is_json and "GET" in r.headers["Allow"]
    assert client.get("/api/v1/gis/missing").is_json
    assert client.get("/api/v1/warehouses/999/summary").status_code==404
    assert client.get("/warehouses/999").status_code==404
    assert client.get("/warehouses/1").status_code==200
    assert client.get("/map").status_code==200


def test_packaged_real_dataset_is_validated_and_matches_source_totals():
    app=create_app()
    d,raw=load_dataset(app.config["GIS_DATA_ROOT"],app.config["GIS_CURRENT_DATASET"])
    import csv,io
    areas=json.loads(raw["areas.geojson"])
    rows=list(csv.DictReader(io.StringIO(raw["population.csv"].decode())))
    assert len(areas["features"])==len(rows)==131
    assert sum(int(r["population"]) for r in rows)==422488
    assert {f["id"] for f in areas["features"]}=={r["area_code"] for r in rows}
    assert d["legend"]["population_date"]=="2020-10-01"
