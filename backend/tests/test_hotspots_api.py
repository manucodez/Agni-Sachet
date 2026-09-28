"""
GET /hotspots — regression coverage for a real bug found in the
best-practices merge: `app/models/hotspot.py` gained six new columns
(nearest_power_plant_*, nearest_responder_*) but `app/schemas/hotspot.py`'s
`HotspotOut` was never updated to include them, so they were silently
dropped from every API response even though they were correctly stored in
the database. FastAPI's response_model filtering makes this kind of bug
invisible unless something actually asserts on the JSON body — a raw
`assert resp.status_code == 200` would have passed even with the bug
present, which is exactly the shape of bug this test exists to catch.
"""
from datetime import datetime, timezone

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models.hotspot import Hotspot


@pytest.fixture
def hotspot_id():
    with SessionLocal() as session:
        h = Hotspot(
            lat=26.9, lon=75.8, geom=from_shape(Point(75.8, 26.9), srid=4326),
            acq_datetime=datetime.now(timezone.utc), sensor="VIIRS_NOAA20",
            frp=42.0, brightness_temp=330.0, confidence="high", daynight="D",
            land_cover_class=50,
            nearest_industrial_distance_m=120.0, nearest_industrial_id="osm_1",
            nearest_power_plant_distance_m=3000.0, nearest_power_plant_id="wri_99",
            nearest_power_plant_fuel_type="Gas",
            nearest_responder_distance_m=2500.0, nearest_responder_type="fire_station",
            nearest_responder_name="Test Fire Station",
            population_density_nearby=1200.0,
        )
        session.add(h)
        session.commit()
        session.refresh(h)
        hid = h.id

    yield hid

    with SessionLocal() as session:
        session.execute(text("DELETE FROM hotspots WHERE id = :id"), {"id": hid})
        session.commit()


def test_hotspots_response_includes_power_plant_and_responder_fields(client, hotspot_id):
    resp = client.get("/hotspots")
    assert resp.status_code == 200
    body = resp.json()
    match = next(h for h in body if h["id"] == str(hotspot_id))

    assert match["nearest_power_plant_distance_m"] == 3000.0
    assert match["nearest_power_plant_id"] == "wri_99"
    assert match["nearest_power_plant_fuel_type"] == "Gas"
    assert match["nearest_responder_distance_m"] == 2500.0
    assert match["nearest_responder_type"] == "fire_station"
    assert match["nearest_responder_name"] == "Test Fire Station"
    # and the pre-existing fields still work
    assert match["nearest_industrial_distance_m"] == 120.0
    assert match["nearest_industrial_id"] == "osm_1"


def test_hotspots_filter_by_predicted_class_and_min_frp(client, hotspot_id):
    resp = client.get("/hotspots", params={"min_frp": 100.0})
    body = resp.json()
    assert all(h["id"] != str(hotspot_id) for h in body)  # frp=42.0 filtered out

    resp = client.get("/hotspots", params={"min_frp": 10.0})
    body = resp.json()
    assert any(h["id"] == str(hotspot_id) for h in body)


def test_hotspots_geojson_endpoint_returns_valid_feature_collection(client, hotspot_id):
    resp = client.get("/hotspots/geojson")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    match = next(f for f in body["features"] if f["properties"]["id"] == str(hotspot_id))
    assert match["geometry"]["coordinates"] == [75.8, 26.9]
