"""
Runs HDBSCAN discovery over the full hotspots history, upserts
`discovered_clusters`, and back-fills `cluster_id` on every `hotspots` row.

Run with:  python -m app.jobs.run_discovery

STABLE IDENTITY, not raw HDBSCAN labels:
HDBSCAN's fit_predict() returns arbitrary integer labels (0, 1, 2, ...)
that are NOT stable across runs — the same physical refinery can come back
as cluster "2" today and cluster "0" tomorrow depending on fit order. Using
those labels directly as the DiscoveredCluster primary key (an earlier
version of this file did exactly that) means every re-run either silently
creates duplicate rows for sites that already exist, or reassigns
classification/risk history built up on a cluster_id to the wrong site.

This version matches each newly-clustered group against EXISTING
DiscoveredCluster rows by centroid proximity first — a new group found
within STABLE_MATCH_RADIUS_KM of an existing cluster's centroid is treated
as the same site (its stable cluster_id is kept, only last_seen/
total_detections update); only a genuinely new location gets a new id
(max existing + 1). This is a deliberately simple nearest-centroid matcher,
not a Hungarian/optimal assignment — see docs/ROADMAP.md for why a proper
assignment algorithm is a reasonable upgrade once you have enough clusters
for mismatches to actually occur in practice.
"""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import select

from app.core.db import SessionLocal
from app.ml.discovery import discover_clusters, summarize_clusters
from app.ml.features import haversine_km
from app.models.cluster import DiscoveredCluster
from app.models.hotspot import Hotspot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STABLE_MATCH_RADIUS_KM = 1.5  # should be >= discover_clusters' cluster_selection_epsilon_km


def _match_or_assign_stable_ids(
    cluster_summary: pd.DataFrame, existing: list[DiscoveredCluster]
) -> dict[int, int]:
    """Returns {raw_hdbscan_label: stable_cluster_id}."""
    raw_to_stable: dict[int, int] = {}
    next_new_id = (max((c.cluster_id for c in existing), default=0)) + 1
    # a site can only absorb one new group per run, and a new group can
    # only match one existing site — track both to avoid double-matching
    claimed_existing_ids: set[int] = set()

    for _, row in cluster_summary.iterrows():
        raw_label = int(row["cluster_id"])
        best_match, best_dist = None, None
        for c in existing:
            if c.cluster_id in claimed_existing_ids:
                continue
            dist = haversine_km(row["centroid_lat"], row["centroid_lon"], c.centroid_lat, c.centroid_lon)
            if dist <= STABLE_MATCH_RADIUS_KM and (best_dist is None or dist < best_dist):
                best_match, best_dist = c.cluster_id, dist

        if best_match is not None:
            raw_to_stable[raw_label] = best_match
            claimed_existing_ids.add(best_match)
        else:
            raw_to_stable[raw_label] = next_new_id
            next_new_id += 1

    return raw_to_stable


def run_discovery() -> None:
    logger.info("=== Discovery pass starting ===")

    with SessionLocal() as session:
        rows = session.execute(select(Hotspot)).scalars().all()
        if not rows:
            logger.warning("No hotspots in the database yet — run ingestion first")
            return

        df = pd.DataFrame(
            [{"id": r.id, "lat": r.lat, "lon": r.lon, "acq_datetime": r.acq_datetime} for r in rows]
        )
        labeled = discover_clusters(df)
        cluster_summary = summarize_clusters(labeled)

        if cluster_summary.empty:
            logger.warning("HDBSCAN found no persistent clusters (all noise) — nothing to upsert")
            return

        existing = list(session.execute(select(DiscoveredCluster)).scalars().all())
        raw_to_stable = _match_or_assign_stable_ids(cluster_summary, existing)
        existing_ids_before = {c.cluster_id for c in existing}
        existing_by_id = {c.cluster_id: c for c in existing}

        # --- upsert cluster rows using STABLE ids, not raw HDBSCAN labels ---
        for _, row in cluster_summary.iterrows():
            stable_id = raw_to_stable[int(row["cluster_id"])]
            if stable_id in existing_by_id:
                cluster = existing_by_id[stable_id]
                cluster.last_seen = row["last_seen"]
                cluster.total_detections = int(row["total_detections"])
                # first_seen, classification, and risk fields are deliberately
                # left untouched here — discovery only re-confirms membership,
                # it never overwrites classification/risk state that
                # run_pipeline.py owns.
            else:
                from geoalchemy2.shape import from_shape
                from shapely.geometry import Point

                session.add(
                    DiscoveredCluster(
                        cluster_id=stable_id,
                        centroid_lat=row["centroid_lat"],
                        centroid_lon=row["centroid_lon"],
                        centroid_geom=from_shape(Point(row["centroid_lon"], row["centroid_lat"]), srid=4326),
                        first_seen=row["first_seen"],
                        last_seen=row["last_seen"],
                        total_detections=int(row["total_detections"]),
                    )
                )

        # --- back-fill hotspot.cluster_id using STABLE ids ---
        # strict=True: id_to_raw_label maps every row of `labeled` by
        # position, and the two columns come from the same DataFrame — if
        # they were ever different lengths that would mean an upstream
        # bug (a dropped/misaligned row), and silently zip()-truncating
        # would mean SOME hotspots quietly get no cluster_id backfilled
        # at all rather than the mismatch failing loudly here.
        id_to_raw_label = dict(zip(labeled["id"], labeled["cluster_id"], strict=True))
        for hotspot_row in rows:
            raw_label = id_to_raw_label.get(hotspot_row.id)
            stable_id = raw_to_stable.get(raw_label) if raw_label is not None and raw_label != -1 else None
            hotspot_row.cluster_id = stable_id

        session.commit()

    n_clusters = len(cluster_summary)
    n_matched = len(existing_ids_before & set(raw_to_stable.values()))
    logger.info(
        "=== Discovery pass complete: %d persistent clusters (%d matched to existing sites, %d new) ===",
        n_clusters, n_matched, n_clusters - n_matched,
    )


if __name__ == "__main__":
    run_discovery()
