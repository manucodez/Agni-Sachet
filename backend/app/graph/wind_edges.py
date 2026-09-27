"""
PHASE 3 — wind-transport edges: the second, independent propagation
pathway alongside physical infrastructure (app/graph/build_graph.py).

A toxic release doesn't need a shared pipeline to threaten the facility
next door — it needs the wind blowing the wrong way. For a cluster that
just triggered a spike anomaly, check every OTHER cluster within a
plausible plume-travel distance and bearing: is it roughly downwind, and
close enough that a plume could reach it within a few hours?

This is deliberately a geometry check, not a full Gaussian-plume or
HYSPLIT dispersion simulation — that level of atmospheric modeling is a
real future upgrade (see docs/ROADMAP.md) but the downwind-cone heuristic
below is free, needs no training, and is genuinely buildable in a day.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from app.ingestion.weather import WeatherAdapter
from app.ml.features import haversine_km

logger = logging.getLogger(__name__)

MAX_PLUME_TRAVEL_KM = 40.0  # generous upper bound for a few hours at typical near-surface wind speeds
PLUME_CONE_HALF_ANGLE_DEG = 30.0  # how tightly "downwind" is defined
WIND_EDGE_VALIDITY_HOURS = 6


@dataclass
class WindEdge:
    source_cluster_id: int
    target_cluster_id: int
    wind_bearing_deg: float
    weight: float  # 1.0 = dead-center downwind and close; falls off with angle/distance
    valid_from: datetime
    valid_to: datetime


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angular_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def find_wind_edges(
    source_cluster: dict, all_clusters: pd.DataFrame, event_time: datetime
) -> list[WindEdge]:
    """
    Args:
        source_cluster: dict with cluster_id, centroid_lat, centroid_lon —
            the cluster that just crossed an anomaly threshold.
        all_clusters: every OTHER discovered cluster to test as a possible
            downwind target.
        event_time: when the anomaly was detected (used to fetch the wind
            reading and set edge validity).
    """
    wind = WeatherAdapter().fetch_wind(source_cluster["centroid_lat"], source_cluster["centroid_lon"], event_time)
    if wind is None:
        logger.warning("No wind reading for cluster %s at %s — skipping wind-edge check", source_cluster["cluster_id"], event_time)
        return []

    # Wind direction is "blowing FROM" by meteorological convention; a
    # plume travels the opposite way, i.e. TOWARD (direction + 180).
    plume_bearing = (wind.wind_direction_deg + 180) % 360

    edges: list[WindEdge] = []
    for _, target in all_clusters.iterrows():
        if int(target["cluster_id"]) == source_cluster["cluster_id"]:
            continue

        distance_km = haversine_km(
            source_cluster["centroid_lat"], source_cluster["centroid_lon"],
            target["centroid_lat"], target["centroid_lon"],
        )
        if distance_km > MAX_PLUME_TRAVEL_KM:
            continue

        bearing_to_target = _bearing_deg(
            source_cluster["centroid_lat"], source_cluster["centroid_lon"],
            target["centroid_lat"], target["centroid_lon"],
        )
        angle_off = _angular_diff(plume_bearing, bearing_to_target)
        if angle_off > PLUME_CONE_HALF_ANGLE_DEG:
            continue

        angle_score = 1 - (angle_off / PLUME_CONE_HALF_ANGLE_DEG)
        distance_score = 1 - (distance_km / MAX_PLUME_TRAVEL_KM)
        weight = round(0.5 * angle_score + 0.5 * distance_score, 3)

        edges.append(
            WindEdge(
                source_cluster_id=source_cluster["cluster_id"],
                target_cluster_id=int(target["cluster_id"]),
                wind_bearing_deg=round(plume_bearing, 1),
                weight=weight,
                valid_from=event_time,
                valid_to=event_time + timedelta(hours=WIND_EDGE_VALIDITY_HOURS),
            )
        )

    logger.info("Wind edges from cluster %s: %d candidates within cone/range", source_cluster["cluster_id"], len(edges))
    return edges
