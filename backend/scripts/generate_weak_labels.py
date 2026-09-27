"""
Pulls fused hotspot rows straight out of the `hotspots` table, applies the
deterministic weak-labeling rule (app/ml/weak_labeling.py), and writes a
labels.csv in exactly the shape app/ml/train.py expects
(FEATURE_COLUMNS + label + lat + lon + acq_datetime).

Run with:
    python -m scripts.generate_weak_labels --out data/processed/labeled_clusters.csv
or:
    make weak-labels

This gets a spatially-diverse training set off the ground in seconds
instead of by hand -- see app/ml/weak_labeling.py's module docstring for
why that matters and what this rule is NOT a substitute for (real
per-incident ground truth). Rows the pipeline hasn't yet been able to
compute the recurrence features for (a cluster's very first detection,
before build_causal_cluster_density has anything to count) are dropped
rather than labeled with a misleading zero -- see the NULL-handling note
below.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.core.db import SessionLocal
from app.ml.features import FEATURE_COLUMNS, build_causal_cluster_density
from app.ml.weak_labeling import generate_weak_labels
from app.models.hotspot import Hotspot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_hotspots_df() -> pd.DataFrame:
    with SessionLocal() as session:
        rows = session.execute(select(Hotspot)).scalars().all()
        return pd.DataFrame(
            [
                {
                    "lat": h.lat, "lon": h.lon, "acq_datetime": h.acq_datetime,
                    "sensor": h.sensor, "frp": h.frp, "brightness_temp": h.brightness_temp,
                    "cluster_id": h.cluster_id,
                    "land_cover_class": h.land_cover_class,
                    "distance_to_industrial_m": h.nearest_industrial_distance_m,
                    "distance_to_power_plant_m": h.nearest_power_plant_distance_m,
                }
                for h in rows
            ]
        )


def build_labels_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    """Adds the derived FEATURE_COLUMNS this rule/model need but the
    hotspots table doesn't store directly (month/hour/is_night are cheap
    to derive from acq_datetime; recurrence counts need the same causal,
    trailing-window logic used at serving time in app/jobs/run_pipeline.py
    -- reusing build_causal_cluster_density here, rather than
    reimplementing a simpler version, is what keeps the weak-labeling
    features and the serving-time features honestly comparable)."""
    df = raw.copy()
    df["month"] = df["acq_datetime"].dt.month
    df["hour"] = df["acq_datetime"].dt.hour
    df["is_night"] = (df["hour"] < 6) | (df["hour"] >= 18)
    df["is_correlated_with_connected_site"] = False  # not known ahead of the graph step; conservative default
    df["graph_centrality_score"] = 0.0  # same — see app/ml/features.py FEATURE_COLUMNS docstring

    # site FRP baseline / z-score, computed per-cluster same as run_pipeline.py
    df["frp_zscore_vs_site_baseline"] = 0.0
    for cluster_id, group in df.groupby("cluster_id"):
        if cluster_id is None or len(group) < 2:
            continue
        mean, std = group["frp"].mean(), group["frp"].std()
        if std and std > 0:
            df.loc[group.index, "frp_zscore_vs_site_baseline"] = (group["frp"] - mean) / std

    trailing_6h, trailing_24h = [], []
    for idx, row in df.iterrows():
        if row["cluster_id"] is None:
            trailing_6h.append(None)
            trailing_24h.append(None)
            continue
        c6, c24 = build_causal_cluster_density(df, row["cluster_id"], row["acq_datetime"])
        trailing_6h.append(c6)
        trailing_24h.append(c24)
    df["trailing_detection_count_6h"] = trailing_6h
    df["trailing_detection_count_24h"] = trailing_24h

    # A cluster's very first detection has no trailing history yet — labeling
    # it "0 recurrence" would look identical to a genuinely one-off event and
    # bias the rule toward under-calling gas_flare (which specifically
    # requires high recurrence). Drop rather than mislabel.
    before = len(df)
    df = df.dropna(subset=["cluster_id", "trailing_detection_count_24h"])
    if len(df) < before:
        logger.info("Dropped %d rows with no cluster assignment or no recurrence history yet", before - len(df))

    labeled = generate_weak_labels(df)
    missing = set(FEATURE_COLUMNS + ["label", "lat", "lon", "acq_datetime"]) - set(labeled.columns)
    if missing:
        raise RuntimeError(f"internal error: labels dataframe still missing {missing}")
    return labeled[FEATURE_COLUMNS + ["label", "lat", "lon", "acq_datetime", "weak_label_rule_version", "cluster_id"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/processed/labeled_clusters.csv"))
    args = parser.parse_args()

    raw = _load_hotspots_df()
    if raw.empty:
        logger.warning("No hotspots in the database yet — run ingestion first (make ingest)")
        return

    labeled = build_labels_dataframe(raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    labeled.to_csv(args.out, index=False)
    logger.info("Wrote %d weakly-labeled rows to %s", len(labeled), args.out)
    logger.info("Label distribution:\n%s", labeled["label"].value_counts().to_string())
    logger.info(
        "Next: python -m app.ml.train --labels %s   (and see scripts/circularity_audit.py before trusting the result)",
        args.out,
    )


if __name__ == "__main__":
    main()
