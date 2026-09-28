"""
Sovereign-boundary filter — drops FIRMS detections that fall inside the
configured bounding box but outside India's actual border: ocean pixels,
sensor edge noise, and slivers of Pakistan/Bangladesh/Nepal/China/Myanmar/
Sri Lanka that a rectangular bbox necessarily includes.

WHY A BBOX ISN'T ENOUGH
------------------------
`settings.firms_bbox` (see app/core/config.py) is a rectangle because the
FIRMS Area API only accepts a rectangle — but India's coastline and land
border are not a rectangle, and the bbox is drawn generously so it doesn't
accidentally clip Andaman & Nicobar or the northeastern states. That
generosity is exactly what lets in the Arabian Sea, the Bay of Bengal, and
strips of five neighboring countries. Every one of those can carry real
VIIRS/MODIS detections (ships, flaring, agricultural burning across the
border) that would otherwise be discovered, classified and risk-scored as
if they were Indian industrial sites.

This mirrors the approach documented in the SIH26162 "AI-Based Detection
and Classification of Industrial Fires" reference implementation: filter
against a real national boundary polygon with a point-in-polygon test,
not just a bounding box. There it's done in PostGIS with `ST_Within`
against a stored `india_boundary` table; here it's done in Python with
Shapely against a boundary polygon loaded once and cached, so it applies
uniformly regardless of which database backend a deployment chooses.

DATA SOURCE
-----------
DataMeet's composite India boundary (CC BY 4.0) — a community-maintained,
commonly-used open boundary that merges Survey of India and OSM sources.
See docs/DATA_SOURCES.md for the license note and why "composite" (not
the OSM-only or SOI-only variant) is the default.

FAIL-OPEN, NOT FAIL-SILENT
---------------------------
If the boundary can't be downloaded (no network on a judging-day laptop,
GitHub rate limit, etc.), this module does NOT block ingestion — a missing
optional layer shouldn't take down the whole pipeline, matching every
other adapter in app/ingestion/. Instead it logs a clear, impossible-to-miss
warning and disables enforcement for that run, falling back to bbox-only
filtering. That's a materially different (weaker) guarantee than when the
boundary loads, so it's surfaced as a warning rather than swallowed —
check the logs before trusting a "0 dropped" count.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

INDIA_BOUNDARY_URL = "https://raw.githubusercontent.com/datameet/maps/master/Country/india-composite.geojson"
CACHE_PATH = Path("data/raw/india_boundary/india-composite.geojson")

_lock = threading.Lock()
_singleton: IndiaBoundary | None = None
_disabled_by_config_logged = False


class IndiaBoundary:
    """A prepared Shapely geometry answering point-in-polygon containment.

    Construct via `IndiaBoundary.load()` (network + disk cache) in normal
    use, or `IndiaBoundary.from_geojson_dict(...)` directly in tests so the
    containment logic can be exercised without a network call or a 10MB+
    fixture file.
    """

    def __init__(self, geometry) -> None:
        from shapely.prepared import prep

        self._geometry = geometry
        # Prepared geometries cache the internal index used for repeated
        # `contains` calls — ingestion tests hundreds to thousands of
        # points per pass, and re-building a spatial index per point would
        # be the dominant cost of this whole module otherwise.
        self._prepared = prep(geometry)

    def contains(self, lat: float, lon: float) -> bool:
        from shapely.geometry import Point

        return bool(self._prepared.contains(Point(lon, lat)))

    @classmethod
    def from_geojson_dict(cls, geojson: dict) -> IndiaBoundary:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        features = geojson["features"] if geojson.get("type") == "FeatureCollection" else [geojson]
        geoms = [shape(f["geometry"] if "geometry" in f else f) for f in features]
        return cls(unary_union(geoms))

    @classmethod
    def load(cls) -> IndiaBoundary | None:
        """Downloads (or reads the disk cache of) the boundary polygon.
        Returns None if unavailable — callers must treat that as "fall
        back to bbox-only filtering," never as "nothing is inside India."
        """
        import json

        if not CACHE_PATH.exists():
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                logger.info("Downloading India boundary from %s", INDIA_BOUNDARY_URL)
                resp = requests.get(INDIA_BOUNDARY_URL, timeout=60)
                resp.raise_for_status()
                CACHE_PATH.write_bytes(resp.content)
            except Exception:
                logger.warning(
                    "Could not download the India boundary polygon (%s). Sovereign-boundary "
                    "filtering is DISABLED for this run — hotspots will only be filtered by "
                    "the FIRMS_BBOX rectangle, which includes ocean and neighboring-country "
                    "slivers. Retry once network access is available, or set "
                    "ENFORCE_INDIA_BOUNDARY=false to silence this warning if that's expected.",
                    INDIA_BOUNDARY_URL, exc_info=True,
                )
                return None

        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                geojson = json.load(f)
            return cls.from_geojson_dict(geojson)
        except Exception:
            logger.warning(
                "Downloaded India boundary at %s failed to parse — deleting the cached copy "
                "so the next run re-downloads it. Sovereign-boundary filtering is DISABLED "
                "for this run.",
                CACHE_PATH, exc_info=True,
            )
            CACHE_PATH.unlink(missing_ok=True)
            return None


def get_boundary() -> IndiaBoundary | None:
    """Process-wide cached loader — the boundary polygon is a few MB of
    coordinates; parsing it on every ingestion record would be absurd, and
    it never changes within a run.

    Only a SUCCESSFUL load is cached permanently. A failed load (network
    hiccup, GitHub rate limit) is retried on the next call rather than
    sticking forever — this module is designed to run inside a long-lived
    scheduled process (see this module's docstring, "Designed to run on a
    schedule"), and caching a transient failure as permanent would mean
    one bad network moment silently disables sovereign-boundary
    enforcement for the rest of that process's life, with no further
    warning after the first one. A previous version of this function did
    exactly that — see docs/MERGE_NOTES.md if this comment is still here
    when that's been cleaned up.
    """
    global _singleton, _disabled_by_config_logged
    with _lock:
        if _singleton is not None:
            return _singleton
        if not settings.enforce_india_boundary:
            if not _disabled_by_config_logged:
                logger.info("ENFORCE_INDIA_BOUNDARY=false — skipping sovereign-boundary filtering by config.")
                _disabled_by_config_logged = True
            return None
        _singleton = IndiaBoundary.load()
        return _singleton


def filter_within_india(records: list[dict], lat_key: str = "lat", lon_key: str = "lon") -> tuple[list[dict], int]:
    """Returns (records actually inside India, count dropped).

    Fails open: if the boundary isn't available (disabled by config, or
    couldn't be loaded — see IndiaBoundary.load()'s docstring), every
    record is kept and the drop count is 0. This is a real difference in
    the guarantee you get, not just an implementation detail — it's why
    run_ingestion.py logs how many records were checked, not just how many
    were dropped.
    """
    if not settings.enforce_india_boundary:
        return records, 0

    boundary = get_boundary()
    if boundary is None:
        return records, 0

    kept = [r for r in records if boundary.contains(r[lat_key], r[lon_key])]
    return kept, len(records) - len(kept)
