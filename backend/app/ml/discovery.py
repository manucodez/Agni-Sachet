"""
Step 3 — persistent thermal source discovery.

Runs HDBSCAN over 3-5 years of historical hotspots (haversine metric, since
lat/lon degrees aren't equal-area) to find sites that light up repeatedly —
refineries, flare stacks, steel plants — as distinct from one-off wildfire
or agricultural-burn detections that never recur at the same coordinates.

This is the PS's "persistent thermal sources" requirement, directly: a
cluster here becomes a `DiscoveredCluster` row, and every hotspot in it
gets tagged with `cluster_id` for everything downstream (anomaly detection,
classification, graph, risk).
"""
from __future__ import annotations

import logging

import hdbscan
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0


def discover_clusters(
    hotspots: pd.DataFrame,
    min_cluster_size: int = 5,
    min_samples: int = 3,
    cluster_selection_epsilon_km: float = 1.0,
) -> pd.DataFrame:
    """
    Args:
        hotspots: must have `lat`, `lon`, `acq_datetime` columns — the full
            historical batch you're discovering sites from.
        min_cluster_size: minimum repeat detections to call something a
            "persistent" source rather than noise (HDBSCAN's own concept).
        cluster_selection_epsilon_km: merges sub-clusters closer than this,
            useful since a large facility can produce several slightly
            offset detections across different satellite passes.

    Returns a DataFrame with one row per `hotspots` row, adding a
    `cluster_id` column (-1 = noise / not part of a persistent source —
    these still matter downstream as one-off events, they're just not
    "persistent").
    """
    if hotspots.empty:
        return hotspots.assign(cluster_id=pd.Series(dtype=int))

    coords_rad = np.radians(hotspots[["lat", "lon"]].to_numpy())
    epsilon_rad = cluster_selection_epsilon_km / EARTH_RADIUS_KM

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="haversine",
        cluster_selection_epsilon=epsilon_rad,
    )
    labels = clusterer.fit_predict(coords_rad)

    out = hotspots.copy()
    out["cluster_id"] = labels
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    logger.info(
        "HDBSCAN: %d persistent clusters found from %d hotspots (%d flagged as noise)",
        n_clusters, len(out), int((labels == -1).sum()),
    )
    return out


def summarize_clusters(labeled_hotspots: pd.DataFrame) -> pd.DataFrame:
    """Collapses labeled hotspots into one row per cluster — the shape that
    gets upserted into `discovered_clusters`. Excludes cluster_id == -1
    (noise points aren't persistent sources and don't get a cluster row)."""
    persistent = labeled_hotspots[labeled_hotspots["cluster_id"] != -1]
    if persistent.empty:
        return pd.DataFrame(
            columns=["cluster_id", "centroid_lat", "centroid_lon", "first_seen", "last_seen", "total_detections"]
        )

    grouped = persistent.groupby("cluster_id").agg(
        centroid_lat=("lat", "mean"),
        centroid_lon=("lon", "mean"),
        first_seen=("acq_datetime", "min"),
        last_seen=("acq_datetime", "max"),
        total_detections=("acq_datetime", "count"),
    ).reset_index()
    return grouped
