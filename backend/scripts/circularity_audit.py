"""
Circularity audit — measures how much of the classifier's reported
accuracy is the model just learning to recite the weak-labeling rule that
generated its own training labels, rather than finding real, independent
thermal signal (FRP shape, recurrence, timing) beyond what the rule
already used directly.

WHY THIS MATTERS
------------------
app/ml/weak_labeling.py assigns a label using distance_to_industrial_m,
distance_to_power_plant_m, land_cover_class, month and recurrence
(RULE_DEFINING_FEATURES). Those same fields are ALSO in FEATURE_COLUMNS
that the model trains on. A model that "achieves 0.85 macro-F1" on a
weakly-labeled test set may just be re-deriving the label-generating rule
from its own inputs — which would be a real, measurable result (the model
learned to run the rule), but a materially different and much weaker claim
than "the model learned to recognize industrial fires," and a judging
panel that knows to ask "how were these labeled?" will immediately see
through a headline number that doesn't distinguish the two.

This mirrors the circularity audit performed in the SIH26162 reference
implementation with the fully-validated pipeline (see docs/MERGE_NOTES.md),
adapted to agni-sachet's own weak-labeling rule and feature set.

METHODOLOGY
------------
1. Train once on the FULL feature set, spatial-block holdout (identical to
   app/ml/train.py) — this is the headline number already reported there.
2. Train again on FEATURE_COLUMNS with weak_labeling.RULE_DEFINING_FEATURES
   removed, same spatial-block split (same train/test rows — only the
   columns differ) — this is what the model can do WITHOUT the exact
   fields the rule used.
3. Report both numbers and the delta.

READING THE RESULT
--------------------
- Small drop (ablated score close to full score): the remaining features
  (FRP, brightness, recurrence shape, timing) carry real signal on their
  own — reassuring, not circular.
- Large drop: most of the reported accuracy comes from re-deriving
  distance/land-cover/month facts the rule already used — report this
  honestly rather than the headline number alone. It does NOT mean the
  model is useless; it means the NEXT priority is real per-incident labels
  (hand-curated, or from data/reference/verified_events.csv), not more
  weakly-labeled rows from the same rule.
- This audit only means something when some or all of labels.csv came
  from app/ml/weak_labeling.py (check the weak_label_rule_version
  column). If every row is hand-curated from real incident reports, skip
  this — there's no rule to be circular with.

Run with:
    python -m scripts.circularity_audit --labels data/processed/labeled_clusters.csv
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import xgboost as xgb
from sklearn.metrics import f1_score

from app.ml.classifier import CLASSES
from app.ml.features import FEATURE_COLUMNS
from app.ml.train import spatial_block_split
from app.ml.weak_labeling import RULE_DEFINING_FEATURES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _train_and_score(train_df: pd.DataFrame, test_df: pd.DataFrame, feature_columns: list[str]) -> float:
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        objective="multi:softprob", num_class=len(CLASSES), eval_metric="mlogloss",
    )
    model.fit(train_df[feature_columns], train_df["y"])
    preds = model.predict(test_df[feature_columns])
    return f1_score(test_df["y"], preds, average="macro")


def run_circularity_audit(labels_path: Path) -> dict:
    df = pd.read_csv(labels_path, parse_dates=["acq_datetime"])
    missing = set(FEATURE_COLUMNS + ["label", "lat", "lon"]) - set(df.columns)
    if missing:
        raise ValueError(f"labels file is missing required columns: {missing}")

    if "weak_label_rule_version" not in df.columns:
        logger.warning(
            "labels file has no weak_label_rule_version column — this audit assumes at least some rows "
            "came from app/ml/weak_labeling.py. If every row is hand-curated, this result isn't meaningful; "
            "see this script's module docstring."
        )

    label_to_idx = {c: i for i, c in enumerate(CLASSES)}
    df = df[df["label"].isin(CLASSES)].copy()
    df["y"] = df["label"].map(label_to_idx)

    train_df, test_df = spatial_block_split(df)

    full_f1 = _train_and_score(train_df, test_df, FEATURE_COLUMNS)
    ablated_features = [c for c in FEATURE_COLUMNS if c not in RULE_DEFINING_FEATURES]
    ablated_f1 = _train_and_score(train_df, test_df, ablated_features)
    drop = full_f1 - ablated_f1
    drop_pct = (drop / full_f1 * 100) if full_f1 > 0 else float("nan")

    logger.info("=== Circularity audit ===")
    logger.info("Full-feature spatial-block macro-F1:            %.3f", full_f1)
    logger.info("Ablated (rule-defining features removed) macro-F1: %.3f  (features used: %s)", ablated_f1, ablated_features)
    logger.info("Drop: %.3f absolute (%.0f%% of full-feature score)", drop, drop_pct)
    if drop_pct >= 50:
        logger.warning(
            "More than half the full-feature score disappears when the label-defining features are "
            "removed. Report the ablated number alongside the headline one, and prioritize real "
            "per-incident labels over more rows from the same weak-labeling rule."
        )
    else:
        logger.info(
            "Less than half the score depends on the label-defining features — there's real signal in "
            "FRP/recurrence/timing beyond what the rule used directly."
        )

    return {"full_f1": full_f1, "ablated_f1": ablated_f1, "drop": drop, "drop_pct": drop_pct, "ablated_features": ablated_features}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    run_circularity_audit(args.labels)
