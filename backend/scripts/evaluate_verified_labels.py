"""
Evaluates the trained classifier against data/reference/verified_events.csv
— a small, independently-sourced (not weak-labeled, not spatial-block-CV)
set of real, cited industrial/wildfire/mining incidents in India, each with
a public source. See that file for the current list and citations.

WHY THIS IS A DIFFERENT CHECK FROM app/ml/train.py's SPATIAL-BLOCK HOLDOUT
------------------------------------------------------------------------------
The spatial-block holdout in app/ml/train.py answers "does the model
generalize to unseen locations, given labels from THIS rule" — it's still
graded against app/ml/weak_labeling.py's own output (or whatever produced
labels.csv). This script answers a different, harder question: "does the
model's prediction match a label nobody derived from the model's own
inputs" — the ground truth here came from Wikipedia/news/NASA citations,
not from distance-to-industrial or land-cover thresholds. A model that
does well on the spatial-block holdout but poorly here is a strong signal
of circularity (see scripts/circularity_audit.py for the complementary,
more direct measurement of that).

A SMALL, HONEST SAMPLE SIZE
------------------------------
Four events (at the time this was written) is nowhere near enough to
report a percentage accuracy with a straight face — treat this as a
smoke test ("does the model get the obvious cases right"), not a
benchmark, and read every per-event result individually rather than
just the summary count. Growing data/reference/verified_events.csv with
more cited incidents (and covering gas_flare and agricultural_burn,
which aren't represented yet — see that file) is one of the highest
-value things a team member can do with a spare afternoon; it's real
research, not busywork, since each row needs an independently checkable
citation, not a guess.

A REAL LIMITATION, STATED PLAINLY
------------------------------------
This script matches against whatever is ALREADY in the `hotspots` table.
app/ingestion/firms.py pulls from FIRMS' near-real-time Area API, which
only covers the trailing firms_day_range window — it will not have 2009,
2019 or 2021 detections unless you've separately backfilled them from
FIRMS' archive download API (https://firms.modaps.eosdis.nasa.gov/api/
country/ or /area/ with a date range, same MAP_KEY, different endpoint
— not yet wired up in app/ingestion/firms.py; see docs/ROADMAP.md).
Until that backfill exists, most rows here will report "no detection
found nearby" — that's an accurate, informative result (it tells you the
harness and the citations are fine, but the archive isn't populated yet),
not a bug in this script.

Run with:
    python -m scripts.evaluate_verified_labels
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.core.db import SessionLocal
from app.ml.classifier import FireClassifier
from app.ml.features import build_feature_row, haversine_km
from app.ml.serving_guards import apply_serving_guards
from app.models.hotspot import Hotspot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VERIFIED_EVENTS_PATH = Path("data/reference/verified_events.csv")
MATCH_RADIUS_KM = 5.0
MATCH_DATE_WINDOW_DAYS = 3


def _find_nearby_hotspots(session, lat: float, lon: float, date, is_persistent: bool) -> list[Hotspot]:
    # A coarse bounding box first (cheap, index-friendly), then an exact
    # haversine filter in Python — consistent with the rest of this
    # codebase's "rough distance is fine at this scale" approach (see
    # app/jobs/run_ingestion.py's _nearest_from).
    deg_pad = MATCH_RADIUS_KM / 111.0  # ~111km per degree latitude
    stmt = select(Hotspot).where(
        Hotspot.lat.between(lat - deg_pad, lat + deg_pad),
        Hotspot.lon.between(lon - deg_pad, lon + deg_pad),
    )
    if not is_persistent and date is not None:
        stmt = stmt.where(
            Hotspot.acq_datetime.between(
                date - timedelta(days=MATCH_DATE_WINDOW_DAYS), date + timedelta(days=MATCH_DATE_WINDOW_DAYS)
            )
        )
    candidates = session.execute(stmt).scalars().all()
    return [h for h in candidates if haversine_km(lat, lon, h.lat, h.lon) <= MATCH_RADIUS_KM]


def evaluate_verified_events(events_path: Path = VERIFIED_EVENTS_PATH) -> list[dict]:
    events = pd.read_csv(events_path, parse_dates=["date"])
    classifier = FireClassifier()
    try:
        classifier.load()
    except FileNotFoundError as exc:
        logger.error("%s — train a model first (python -m app.ml.train)", exc)
        return []

    results = []
    with SessionLocal() as session:
        for _, event in events.iterrows():
            nearby = _find_nearby_hotspots(
                session, event["lat"], event["lon"],
                event["date"] if pd.notna(event["date"]) else None,
                bool(event["is_persistent"]),
            )
            if not nearby:
                results.append({
                    "event": event["event_name"], "verified_class": event["verified_class"],
                    "status": "no_detection_found",
                    "note": "no FIRMS detection within radius/date window — see this script's docstring re: historical backfill",
                })
                continue

            best = max(nearby, key=lambda h: h.frp or 0)
            feature_row = build_feature_row(
                land_cover_class=best.land_cover_class,
                distance_to_industrial_m=best.nearest_industrial_distance_m,
                distance_to_power_plant_m=best.nearest_power_plant_distance_m,
                acq_datetime=best.acq_datetime, frp=best.frp,
                site_frp_mean=None, site_frp_std=None, brightness_temp=best.brightness_temp,
                trailing_detection_count_6h=0, trailing_detection_count_24h=0,
                is_correlated_with_connected_site=False, graph_centrality_score=0.0,
            )
            prediction = classifier.predict(feature_row.as_dict())
            guard = apply_serving_guards(
                prediction.predicted_class, prediction.confidence,
                land_cover_class=best.land_cover_class,
                nearest_industrial_distance_m=best.nearest_industrial_distance_m,
                nearest_power_plant_distance_m=best.nearest_power_plant_distance_m,
                nearest_power_plant_fuel_type=best.nearest_power_plant_fuel_type,
            )
            results.append({
                "event": event["event_name"], "verified_class": event["verified_class"],
                "predicted_class": guard.served_class, "confidence": round(guard.served_confidence, 3),
                "match": guard.served_class == event["verified_class"],
                "matched_hotspot_frp": best.frp, "matched_hotspot_datetime": best.acq_datetime,
                "status": "evaluated",
            })

    evaluated = [r for r in results if r["status"] == "evaluated"]
    if evaluated:
        n_match = sum(1 for r in evaluated if r["match"])
        logger.info("=== Verified-event evaluation: %d/%d evaluated events matched ===", n_match, len(evaluated))
    skipped = len(results) - len(evaluated)
    if skipped:
        logger.info("%d/%d events skipped (no nearby detection found — see per-event notes)", skipped, len(results))
    for r in results:
        logger.info(r)
    return results


if __name__ == "__main__":
    evaluate_verified_events()
