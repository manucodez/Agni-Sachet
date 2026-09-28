"""
Step 7 — classification. Turns a feature row (app/ml/features.py) into one
of 6 known classes, PLUS a 7th "unclassified" bucket for anything the model
isn't confident about — directly answers the PS's core ask ("classification
and segregation of industrial fires from forest fires and other natural
fires") while refusing to force-fit genuinely novel events into a stale
taxonomy.

CLASSES[0:6] are the trained softmax outputs; "unclassified" is not a
training label — see docs/ARCHITECTURE.md for why over-representing it in
training data would just teach the model to hedge.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from app.ml.features import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

CLASSES = [
    "industrial_fire",
    "gas_flare",
    "mining",
    "agricultural_burn",
    "wildfire",
    "other",
]

DEFAULT_MODEL_PATH = Path("models/classifier.joblib")
UNCLASSIFIED_CONFIDENCE_THRESHOLD = 0.55


@dataclass
class ClassificationResult:
    predicted_class: str  # one of CLASSES, or "unclassified"
    confidence: float
    top_reasons: list[tuple[str, float]]  # top-3 SHAP feature contributions
    raw_probabilities: dict[str, float]


class FireClassifier:
    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH):
        self.model_path = model_path
        self._model: xgb.XGBClassifier | None = None
        self._explainer: shap.TreeExplainer | None = None

    def load(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"No trained model at {self.model_path}. Run `python -m app.ml.train` first "
                "(see docs/SETUP.md, Phase 2)."
            )
        self._model = xgb.XGBClassifier()
        self._model.load_model(str(self.model_path))
        self._explainer = shap.TreeExplainer(self._model)

    def predict(self, feature_row: dict) -> ClassificationResult:
        if self._model is None:
            self.load()

        x = pd.DataFrame([feature_row])[FEATURE_COLUMNS]
        proba = self._model.predict_proba(x)[0]
        pred_idx = int(np.argmax(proba))
        confidence = float(proba[pred_idx])

        shap_values = self._explainer.shap_values(x)
        contributions = shap_values[pred_idx][0] if isinstance(shap_values, list) else shap_values[0]
        top3_idx = np.argsort(np.abs(contributions))[::-1][:3]
        top_reasons = [(FEATURE_COLUMNS[i], round(float(contributions[i]), 4)) for i in top3_idx]

        predicted_class = CLASSES[pred_idx] if confidence >= UNCLASSIFIED_CONFIDENCE_THRESHOLD else "unclassified"

        return ClassificationResult(
            predicted_class=predicted_class,
            confidence=round(confidence, 4),
            top_reasons=top_reasons,
            # strict=True: proba is the model's raw per-class probability
            # output and CLASSES is the fixed 6-class taxonomy it was
            # trained on — these must always be the same length; if a
            # model artifact were ever loaded with a different number of
            # output classes than CLASSES expects, that's a real
            # model/config mismatch that should fail loudly here, not
            # silently zip-truncate and mislabel probabilities.
            raw_probabilities={c: round(float(p), 4) for c, p in zip(CLASSES, proba, strict=True)},
        )

    def apply_evidence_fusion(
        self,
        result: ClassificationResult,
        chem_fingerprint_score: float | None = None,
        sar_structural_change_score: float | None = None,
        gfm_novelty_score: float | None = None,
    ) -> ClassificationResult:
        """PHASE 3 — evidence-fused override. Called only for clusters that
        crossed the anomaly threshold and went through the advanced
        channels (app/jobs/run_pipeline.py). A high GFM novelty score (this
        doesn't look like anything the model has seen) can downgrade a
        confident softmax prediction to "unclassified" even if the raw
        confidence was above threshold — that's the whole point of the
        open-set channel: catching the model being confidently wrong about
        something genuinely new, not just being unsure.
        """
        if gfm_novelty_score is not None and gfm_novelty_score > 0.8:
            logger.info(
                "GFM novelty score %.2f overrides softmax prediction %s -> unclassified",
                gfm_novelty_score, result.predicted_class,
            )
            return ClassificationResult(
                predicted_class="unclassified",
                confidence=result.confidence,
                top_reasons=result.top_reasons + [("gfm_novelty_override", gfm_novelty_score)],
                raw_probabilities=result.raw_probabilities,
            )

        # Chemistry/SAR don't override the class here — they're stored
        # alongside it (see DiscoveredCluster.chem_fingerprint_score /
        # sar_structural_change_score) and folded into the risk score
        # instead (app/risk/scoring.py), since "sulfur-heavy plume" is
        # evidence about severity/confirmation, not a vote for a different
        # taxonomy label.
        return result


def dump_shap_reasons(reasons: list[tuple[str, float]]) -> str:
    return json.dumps([{"feature": f, "contribution": v} for f, v in reasons])
