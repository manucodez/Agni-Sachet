"""
One full ingestion pass: FIRMS + OSM + WorldCover + WorldPop + WRI power
plants, fused into the `hotspots` table (Steps 1-2 of the architecture).

Run with:  python -m app.jobs.run_ingestion
or:        make ingest   (runs it inside the backend container)

Designed to run on a schedule (see app/jobs/__init__.py note on
APScheduler) — every adapter failure is caught and logged rather than
aborting the whole run, since a stale WorldCover tile shouldn't block a
fresh FIRMS pull.
"""
from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import SessionLocal
from app.ingestion.firms import FirmsAdapter
from app.ingestion.india_boundary import filter_within_india
from app.ingestion.osm import OsmAdapter
from app.ingestion.power_plants import PowerPlantsAdapter
from app.ingestion.worldcover import WorldCoverAdapter, sample_land_cover
from app.ingestion.worldpop import WorldPopAdapter, sample_population_density
from app.models.hotspot import Hotspot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _nearest_from(lat: float, lon: float, candidates: list[dict]) -> tuple[float | None, str | None]:
    """Rough nearest-centroid distance in meters against a list of
    {"osm_id"/"wri_id"/id-ish key, "coordinates": [[lon,lat], ...]} dicts.

    Generalized (was `_nearest_industrial`) so the same rough-and-ready
    centroid distance is used consistently for industrial polygons, power
    plants and responders — one join strategy, three candidate lists,
    rather than three slightly-different distance functions drifting apart
    over time.

    Fine for a hackathon-scale join; swap for a proper PostGIS ST_Distance
    query once the polygons are themselves stored in the DB rather than
    held in memory — see docs/ARCHITECTURE.md, "Known limitations".

    Returns (None, None) when candidates is empty OR when every candidate
    is further away than is meaningful to report — callers decide what
    "meaningful" means (see MAX_RESPONDER_SEARCH_KM below); this function
    itself has no cutoff and always returns the single nearest candidate.
    """
    from app.ml.features import haversine_km

    if not candidates:
        return None, None

    best_dist, best_id = None, None
    for cand in candidates:
        coords = cand.get("coordinates", [])
        if not coords:
            continue
        centroid_lon = sum(c[0] for c in coords) / len(coords)
        centroid_lat = sum(c[1] for c in coords) / len(coords)
        dist_km = haversine_km(lat, lon, centroid_lat, centroid_lon)
        if best_dist is None or dist_km < best_dist:
            best_dist, best_id = dist_km, str(cand.get("id"))
    return (best_dist * 1000 if best_dist is not None else None), best_id


# Beyond this, "nearest responder" stops being a useful number for a SitRep
# (a hospital 400km away isn't an actionable fact) and is reported as null
# instead, so the frontend can render "none nearby" rather than a
# misleadingly precise-looking huge distance.
MAX_RESPONDER_SEARCH_KM = 100


def run_ingestion() -> None:
    logger.info("=== Ingestion pass starting ===")

    # --- Step 1: pull each source, independently fault-tolerant ---
    hotspot_records: list[dict] = []
    try:
        hotspot_records = FirmsAdapter().run()
        logger.info("FIRMS: %d raw detections", len(hotspot_records))
    except Exception:
        logger.exception("FIRMS ingestion failed — aborting this pass (no hotspots = nothing else to do)")
        return

    # Sovereign-boundary filter — see app/ingestion/india_boundary.py for
    # why the FIRMS bbox alone lets in ocean and cross-border noise, and
    # why this fails open (logs a warning, keeps everything) rather than
    # blocking ingestion when the boundary polygon can't be loaded.
    hotspot_records, dropped = filter_within_india(hotspot_records)
    if dropped:
        logger.info("Sovereign boundary filter: dropped %d detections outside India", dropped)
    if not hotspot_records:
        logger.info("No detections remain after boundary filtering — nothing to fuse this pass")
        return

    industrial_polygons: list[dict] = []
    power_plant_candidates: list[dict] = []
    responder_candidates: list[dict] = []
    try:
        osm_records = OsmAdapter().run()
        industrial_polygons = [
            {"id": r["osm_id"], "coordinates": r["coordinates"]}
            for r in osm_records if r["category"] == "industrial_polygon"
        ]
        responder_candidates = [
            {
                "id": r["osm_id"],
                "coordinates": r["coordinates"],
                "responder_type": "fire_station" if r["category"] == "responder_fire_station" else "hospital",
                "name": r.get("name"),
            }
            for r in osm_records if r["category"] in ("responder_fire_station", "responder_hospital")
        ]
        logger.info(
            "OSM: %d industrial polygons, %d responders for the nearest-distance joins",
            len(industrial_polygons), len(responder_candidates),
        )
    except Exception:
        logger.exception(
            "OSM ingestion failed — hotspots will have null nearest_industrial/nearest_responder fields this pass"
        )

    try:
        WorldCoverAdapter().run()
    except Exception:
        logger.exception("WorldCover download failed — hotspots will have null land_cover_class this pass")

    try:
        WorldPopAdapter().run()
    except Exception:
        logger.exception("WorldPop download failed — hotspots will have null population_density_nearby this pass")

    try:
        power_plant_records = PowerPlantsAdapter().run()
        logger.info("WRI power plants: %d records", len(power_plant_records))
        # Kept as its OWN candidate list — not merged into industrial_polygons
        # as earlier versions of this function did. Merging them meant
        # "nearest power plant" and "nearest industrial parcel" collapsed
        # into the same number wherever a power plant happened to be the
        # closest industrial feature, and app/jobs/run_pipeline.py was
        # (silently) copying that one distance into both the
        # distance_to_industrial_m and distance_to_power_plant_m model
        # features — see app/models/hotspot.py docstring. Keeping this list
        # WRI-only (rather than also including OSM power=plant tags) means
        # nearest_power_plant_fuel_type is always a real GPPD fuel_type
        # string, never a guess.
        power_plant_candidates = [
            {"id": f"wri_{r['wri_id']}", "coordinates": [[r["lon"], r["lat"]]], "fuel_type": r.get("fuel_type")}
            for r in power_plant_records
        ]
    except Exception:
        logger.exception("WRI power plant ingestion failed — nearest_power_plant_* will be null this pass")

    # --- Step 2: fuse ---
    for rec in hotspot_records:
        rec["land_cover_class"] = sample_land_cover(rec["lat"], rec["lon"])
        rec["population_density_nearby"] = sample_population_density(rec["lat"], rec["lon"])

        dist_m, nearest_id = _nearest_from(rec["lat"], rec["lon"], industrial_polygons)
        rec["nearest_industrial_distance_m"] = dist_m
        rec["nearest_industrial_id"] = nearest_id

        pp_dist_m, pp_id = _nearest_from(rec["lat"], rec["lon"], power_plant_candidates)
        rec["nearest_power_plant_distance_m"] = pp_dist_m
        rec["nearest_power_plant_id"] = pp_id
        rec["nearest_power_plant_fuel_type"] = next(
            (c["fuel_type"] for c in power_plant_candidates if str(c["id"]) == pp_id), None
        ) if pp_id else None

        resp_dist_m, resp_id = _nearest_from(rec["lat"], rec["lon"], responder_candidates)
        if resp_dist_m is not None and resp_dist_m <= MAX_RESPONDER_SEARCH_KM * 1000:
            resp = next((c for c in responder_candidates if str(c["id"]) == resp_id), None)
            rec["nearest_responder_distance_m"] = resp_dist_m
            rec["nearest_responder_type"] = resp["responder_type"] if resp else None
            rec["nearest_responder_name"] = (resp.get("name") if resp else None) or "Unnamed"
        else:
            rec["nearest_responder_distance_m"] = None
            rec["nearest_responder_type"] = None
            rec["nearest_responder_name"] = None

    # --- Step 2b: upsert into PostGIS ---
    _bulk_upsert_hotspots(hotspot_records)
    logger.info("=== Ingestion pass complete: %d hotspots fused and stored ===", len(hotspot_records))


def _bulk_upsert_hotspots(records: list[dict]) -> None:
    if not records:
        return
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    with SessionLocal() as session:
        for rec in records:
            rec["geom"] = from_shape(Point(rec["lon"], rec["lat"]), srid=4326)
        stmt = pg_insert(Hotspot).values(records)
        # No natural unique key across sensors at exact-same coordinates is
        # guaranteed, so this is an append-only insert; de-duplication (if
        # your FIRMS day_range overlaps between runs) happens in the
        # discovery/query layer via acq_datetime + sensor + rounded lat/lon,
        # not here — see docs/ARCHITECTURE.md.
        session.execute(stmt)
        session.commit()


if __name__ == "__main__":
    run_ingestion()
