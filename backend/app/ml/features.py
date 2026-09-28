"""
Feature engineering shared by training (app/ml/train.py) and live scoring
(app/ml/classifier.py). Keeping one function used by both is what
guarantees train/serve consistency.

DESIGN NOTE — read before changing this file:
A July 2026 leakage study on FIRMS-based wildfire classifiers (González-
Martínez & Soltan, GeoHazards 7(3):90) found that raw lat/lon accounted for
~89% of a LightGBM model's split gain, inflated in-distribution accuracy,
and *hurt* generalization to unseen regions (spatial-block F1 dropped from
0.82 to 0.63 when coordinates were added) — the model was memorizing where
known events occurred, not learning transferable structure. The same paper
found that spatiotemporal clustering density only helps if computed
causally (trailing-window, using only past detections at scoring time);
a full-history/full-partition cluster count is a second leakage path.

Consequences applied here:
  1. Raw latitude/longitude are NEVER included as classifier features.
     `nearest_industrial_distance_m` and land-cover class are used instead —
     they carry the same "is this an industrial area" signal without
     encoding *which* industrial area, so they transfer to new regions.
  2. `trailing_detection_count_6h` / `_24h` are computed only from
     detections at-or-before the row's own acq_datetime — never from the
     full historical batch. See build_causal_cluster_density() below.
  3. Model validation (app/ml/train.py) must use a spatial-block or
     event-aware holdout, never a random split — see docs/ARCHITECTURE.md
     Section "Validation methodology" for the exact protocol.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

FEATURE_COLUMNS = [
    "land_cover_class",
    "distance_to_industrial_m",
    "distance_to_power_plant_m",
    "month",
    "hour",
    "is_night",
    "frp",
    "frp_zscore_vs_site_baseline",
    "brightness_temp",
    "trailing_detection_count_6h",
    "trailing_detection_count_24h",
    "is_correlated_with_connected_site",
    "graph_centrality_score",
]


@dataclass
class FeatureRow:
    land_cover_class: int | None
    distance_to_industrial_m: float | None
    distance_to_power_plant_m: float | None
    month: int
    hour: int
    is_night: int
    frp: float | None
    frp_zscore_vs_site_baseline: float | None
    brightness_temp: float | None
    trailing_detection_count_6h: int
    trailing_detection_count_24h: int
    is_correlated_with_connected_site: int
    graph_centrality_score: float | None

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in FEATURE_COLUMNS}


def build_causal_cluster_density(
    hotspots: pd.DataFrame, cluster_id: int, as_of: pd.Timestamp
) -> tuple[int, int]:
    """Count detections in the same cluster within the trailing 6h/24h
    windows, using ONLY rows with acq_datetime <= as_of. This function is
    the one place that enforces causality — call it per-row during both
    training and live scoring rather than precomputing a global count.
    """
    site_history = hotspots[(hotspots["cluster_id"] == cluster_id) & (hotspots["acq_datetime"] <= as_of)]
    count_6h = int((site_history["acq_datetime"] >= as_of - pd.Timedelta(hours=6)).sum())
    count_24h = int((site_history["acq_datetime"] >= as_of - pd.Timedelta(hours=24)).sum())
    return count_6h, count_24h


def build_feature_row(
    *,
    land_cover_class: int | None,
    distance_to_industrial_m: float | None,
    distance_to_power_plant_m: float | None,
    acq_datetime: pd.Timestamp,
    frp: float | None,
    site_frp_mean: float | None,
    site_frp_std: float | None,
    brightness_temp: float | None,
    trailing_detection_count_6h: int,
    trailing_detection_count_24h: int,
    is_correlated_with_connected_site: bool,
    graph_centrality_score: float | None,
) -> FeatureRow:
    frp_z = None
    if frp is not None and site_frp_mean is not None and site_frp_std and site_frp_std > 0:
        frp_z = (frp - site_frp_mean) / site_frp_std

    return FeatureRow(
        land_cover_class=land_cover_class,
        distance_to_industrial_m=distance_to_industrial_m,
        distance_to_power_plant_m=distance_to_power_plant_m,
        month=acq_datetime.month,
        hour=acq_datetime.hour,
        is_night=int(acq_datetime.hour < 6 or acq_datetime.hour >= 18),
        frp=frp,
        frp_zscore_vs_site_baseline=frp_z,
        brightness_temp=brightness_temp,
        trailing_detection_count_6h=trailing_detection_count_6h,
        trailing_detection_count_24h=trailing_detection_count_24h,
        is_correlated_with_connected_site=int(is_correlated_with_connected_site),
        graph_centrality_score=graph_centrality_score,
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Used by discovery (HDBSCAN metric) and by the
    wind-edge geometry check — never skip this for flat Euclidean distance;
    see the walkthrough doc's own note on why that distorts across India's
    ~8-37 degN span."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
