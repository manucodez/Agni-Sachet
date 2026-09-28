"""
Trains the XGBoost classifier and validates it with a spatial-block
holdout — NOT a random split. Run with:

    python -m app.ml.train --labels data/processed/labeled_clusters.csv

VALIDATION METHODOLOGY (read before changing the split logic):
González-Martínez & Soltan (2026) showed FIRMS-based classifiers can
report a random-split F1 of ~0.98 that collapses to ~0.63 under a spatial
holdout, because random splits let the model see other detections from
the same site in training and just memorize it. We hold out entire spatial
blocks (a coarse lat/lon grid cell) so every test-set site is completely
unseen during training — this is a strictly harder, more honest number,
and it's the number that goes in the judging deck, not the random-split one.

Both numbers get printed and logged so the gap itself is visible — a large
gap is itself informative (it tells you how much the model is leaning on
site memorization vs. transferable signal).
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import train_test_split

from app.ml.classifier import CLASSES, DEFAULT_MODEL_PATH
from app.ml.features import FEATURE_COLUMNS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPATIAL_BLOCK_DEGREES = 0.5  # ~55km blocks at India's latitudes


def _spatial_block_id(lat: float, lon: float) -> str:
    return f"{int(lat / SPATIAL_BLOCK_DEGREES)}_{int(lon / SPATIAL_BLOCK_DEGREES)}"


def spatial_block_split(df: pd.DataFrame, test_size: float = 0.2, seed: int = 42):
    """Splits by whole spatial block, not by row — a block is entirely in
    train or entirely in test. This is what makes it leakage-safe."""
    blocks = df.apply(lambda r: _spatial_block_id(r["lat"], r["lon"]), axis=1)
    unique_blocks = blocks.unique()
    train_blocks, test_blocks = train_test_split(unique_blocks, test_size=test_size, random_state=seed)
    train_mask = blocks.isin(train_blocks)
    return df[train_mask], df[~train_mask]


def train(labels_path: Path, model_out: Path = DEFAULT_MODEL_PATH) -> None:
    df = pd.read_csv(labels_path, parse_dates=["acq_datetime"])
    missing = set(FEATURE_COLUMNS + ["label", "lat", "lon"]) - set(df.columns)
    if missing:
        raise ValueError(f"labels file is missing required columns: {missing}")

    label_to_idx = {c: i for i, c in enumerate(CLASSES)}
    df = df[df["label"].isin(CLASSES)].copy()  # "unclassified" is never a training label
    df["y"] = df["label"].map(label_to_idx)

    # --- The number that matters: spatial-block holdout ---
    train_df, test_df = spatial_block_split(df)
    logger.info(
        "Spatial-block split: %d train rows (%d blocks), %d test rows (%d blocks)",
        len(train_df), train_df.apply(lambda r: _spatial_block_id(r["lat"], r["lon"]), axis=1).nunique(),
        len(test_df), test_df.apply(lambda r: _spatial_block_id(r["lat"], r["lon"]), axis=1).nunique(),
    )
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        objective="multi:softprob", num_class=len(CLASSES), eval_metric="mlogloss",
    )
    model.fit(train_df[FEATURE_COLUMNS], train_df["y"])
    spatial_preds = model.predict(test_df[FEATURE_COLUMNS])
    spatial_f1 = f1_score(test_df["y"], spatial_preds, average="macro")
    logger.info("Spatial-block holdout macro-F1: %.3f  <-- report THIS one", spatial_f1)
    logger.info("\n%s", classification_report(test_df["y"], spatial_preds, target_names=CLASSES, zero_division=0))

    # --- The number that's misleading on its own: random split ---
    # Printed only for contrast, to show the gap explicitly — never present
    # this figure alone in the judging deck.
    rand_train, rand_test = train_test_split(df, test_size=0.2, random_state=42, stratify=df["y"])
    rand_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        objective="multi:softprob", num_class=len(CLASSES), eval_metric="mlogloss",
    )
    rand_model.fit(rand_train[FEATURE_COLUMNS], rand_train["y"])
    rand_f1 = f1_score(rand_test["y"], rand_model.predict(rand_test[FEATURE_COLUMNS]), average="macro")
    logger.info(
        "Random-split macro-F1: %.3f (for contrast only — gap of %.3f vs spatial-block is the honesty check)",
        rand_f1, rand_f1 - spatial_f1,
    )

    # --- Final model trained on ALL data (train+test) for deployment ---
    final_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        objective="multi:softprob", num_class=len(CLASSES), eval_metric="mlogloss",
    )
    final_model.fit(df[FEATURE_COLUMNS], df["y"])
    model_out.parent.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(model_out))
    logger.info("Saved deployable model to %s", model_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True, help="CSV with FEATURE_COLUMNS + label + lat + lon")
    parser.add_argument("--out", type=Path, default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train(args.labels, args.out)
