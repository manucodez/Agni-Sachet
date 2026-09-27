"""
app/ingestion/india_boundary.py — exercised against a small synthetic
polygon rather than the real ~10MB India boundary file, so this test
needs no network access and runs in milliseconds. See that module's
`IndiaBoundary.from_geojson_dict` docstring for why this constructor
exists specifically to make that possible.
"""
from app.ingestion.india_boundary import IndiaBoundary, filter_within_india

# A simple square "country": lon/lat (0,0) to (10,10).
SQUARE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        }
    ],
}


def test_point_inside_boundary():
    boundary = IndiaBoundary.from_geojson_dict(SQUARE_GEOJSON)
    assert boundary.contains(lat=5, lon=5) is True


def test_point_outside_boundary():
    boundary = IndiaBoundary.from_geojson_dict(SQUARE_GEOJSON)
    assert boundary.contains(lat=50, lon=50) is False


def test_ocean_like_point_just_outside_edge_is_excluded():
    boundary = IndiaBoundary.from_geojson_dict(SQUARE_GEOJSON)
    assert boundary.contains(lat=-1, lon=5) is False


def test_filter_within_india_drops_outside_points(monkeypatch):
    import app.ingestion.india_boundary as mod

    monkeypatch.setattr(mod.settings, "enforce_india_boundary", True)
    monkeypatch.setattr(mod, "get_boundary", lambda: IndiaBoundary.from_geojson_dict(SQUARE_GEOJSON))

    records = [{"lat": 5, "lon": 5}, {"lat": 50, "lon": 50}, {"lat": 3, "lon": 3}]
    kept, dropped = filter_within_india(records)
    assert dropped == 1
    assert len(kept) == 2


def test_filter_within_india_disabled_by_config_keeps_everything(monkeypatch):
    import app.ingestion.india_boundary as mod

    monkeypatch.setattr(mod.settings, "enforce_india_boundary", False)
    records = [{"lat": 5, "lon": 5}, {"lat": 999, "lon": 999}]
    kept, dropped = filter_within_india(records)
    assert dropped == 0
    assert len(kept) == 2


def test_filter_within_india_fails_open_when_boundary_unavailable(monkeypatch):
    import app.ingestion.india_boundary as mod

    monkeypatch.setattr(mod.settings, "enforce_india_boundary", True)
    monkeypatch.setattr(mod, "get_boundary", lambda: None)  # simulates a failed download

    records = [{"lat": 999, "lon": 999}]  # would be dropped if enforcement were active
    kept, dropped = filter_within_india(records)
    assert dropped == 0
    assert kept == records
