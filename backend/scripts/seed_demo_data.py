"""
Loads a small, realistic demo dataset so the dashboard isn't empty on
first run — useful for rehearsing a demo without depending on a live
FIRMS pull working on stage. Run with:

    python -m scripts.seed_demo_data
    (or: make seed)

The three seeded clusters are loosely modeled on public reporting about
real facility types (a refinery flare, a thermal power plant, an open-cast
mine) at plausible-but-nonspecific Indian coordinates — NOT claimed to be
live detections of any real, named incident. Swap in your own curated
real-incident example before a judged demo; see docs/ARCHITECTURE.md,
"Being honest about what's a 7-day build and what isn't".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.core.db import SessionLocal, init_postgis_extension
from app.models.cluster import DiscoveredCluster
from app.models.hotspot import Hotspot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEMO_CLUSTERS = [
    {"cluster_id": 1, "lat": 22.3072, "lon": 73.1812, "class_": "gas_flare", "risk": 22.0, "tier": "L0"},
    {"cluster_id": 2, "lat": 21.6417, "lon": 69.6293, "class_": "industrial_fire", "risk": 78.0, "tier": "L2"},
    {"cluster_id": 3, "lat": 23.6693, "lon": 86.1511, "class_": "mining", "risk": 35.0, "tier": "L1"},
]


def seed() -> None:
    init_postgis_extension()
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        for c in DEMO_CLUSTERS:
            session.merge(
                DiscoveredCluster(
                    cluster_id=c["cluster_id"],
                    centroid_lat=c["lat"],
                    centroid_lon=c["lon"],
                    centroid_geom=from_shape(Point(c["lon"], c["lat"]), srid=4326),
                    first_seen=now - timedelta(days=30),
                    last_seen=now,
                    total_detections=42,
                    predicted_class=c["class_"],
                    classification_confidence=0.87,
                    risk_score=c["risk"],
                    risk_tier=c["tier"],
                    centrality_score=0.3,
                )
            )
            for i in range(10):
                ts = now - timedelta(hours=i * 6)
                session.add(
                    Hotspot(
                        lat=c["lat"] + (i * 0.001), lon=c["lon"] + (i * 0.001),
                        geom=from_shape(Point(c["lon"] + i * 0.001, c["lat"] + i * 0.001), srid=4326),
                        acq_datetime=ts, sensor="VIIRS_NOAA20",
                        frp=15.0 + i, brightness_temp=330.0, confidence="nominal", daynight="D",
                        cluster_id=c["cluster_id"],
                    )
                )
        session.commit()

    logger.info("Seeded %d demo clusters with 10 hotspots each", len(DEMO_CLUSTERS))


if __name__ == "__main__":
    seed()
