"""
Step 8 — risk scoring. Combines classification confidence, anomaly
severity, graph centrality, and population exposure into one 0-100 score,
then buckets it into an NDMA-style L0-L3 tier — a raw number is harder for
a non-technical judge or analyst to act on at a glance than "L2: Elevated".

Weights below are a starting point, not a calibrated model — tune them
against whatever real/synthetic incidents you validate against, and treat
the weights themselves as a documented assumption in the judging deck
rather than presenting the score as more principled than it is.
"""
from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {
    "anomaly_severity": 0.35,
    "population_exposure": 0.25,
    "graph_centrality": 0.20,
    "classification_severity": 0.20,
}

# How much each predicted class contributes to "classification_severity"
# before weighting — an unconfirmed industrial_fire is worse news than an
# equally-confident gas_flare, independent of anomaly/population/graph terms.
CLASS_SEVERITY = {
    "industrial_fire": 1.0,
    "unclassified": 0.8,  # unknown is treated as high-caution, not low-risk
    "mining": 0.4,
    "gas_flare": 0.3,
    "agricultural_burn": 0.2,
    "wildfire": 0.5,
    "other": 0.1,
}

RISK_TIERS = [
    (85, "L3"),  # Critical
    (60, "L2"),  # Elevated
    (30, "L1"),  # Watch
    (0, "L0"),   # Low
]


@dataclass
class RiskInput:
    anomaly_severity: float | None  # from AnomalyFlag.severity_score, 0+ (unbounded — normalize before scoring)
    population_density_nearby: float | None  # people/km^2, from WorldPop sample
    graph_centrality_score: float | None  # 0-1, from compute_centrality()
    predicted_class: str
    classification_confidence: float
    # Phase 3 evidence-fusion boosts — additive, capped, all optional
    chem_fingerprint_score: float | None = None  # 0-1, higher = more anomalous chemical signature
    sar_structural_change_score: float | None = None  # 0-1, higher = more physical change detected


def _normalize_anomaly_severity(raw: float | None) -> float:
    if raw is None:
        return 0.0
    return min(1.0, raw / 3.0)  # severity above ~3x baseline is already "as bad as it gets" for this score


def _normalize_population(raw: float | None) -> float:
    if raw is None:
        return 0.0
    return min(1.0, raw / 5000.0)  # 5000 people/km^2 treated as the saturating high end


def compute_risk_score(inp: RiskInput) -> tuple[float, str]:
    anomaly_term = _normalize_anomaly_severity(inp.anomaly_severity)
    population_term = _normalize_population(inp.population_density_nearby)
    centrality_term = inp.graph_centrality_score or 0.0
    class_severity = CLASS_SEVERITY.get(inp.predicted_class, 0.3)
    classification_term = class_severity * inp.classification_confidence

    base_score = (
        WEIGHTS["anomaly_severity"] * anomaly_term
        + WEIGHTS["population_exposure"] * population_term
        + WEIGHTS["graph_centrality"] * centrality_term
        + WEIGHTS["classification_severity"] * classification_term
    ) * 100

    # Phase 3 evidence-fusion boost: confirmed chemistry/structural change
    # nudges the score up, capped so a single advanced channel can't alone
    # push a low-confidence event to Critical.
    boost = 0.0
    if inp.chem_fingerprint_score:
        boost += min(10.0, inp.chem_fingerprint_score * 10)
    if inp.sar_structural_change_score:
        boost += min(10.0, inp.sar_structural_change_score * 10)

    final_score = min(100.0, base_score + boost)
    tier = next(tier for threshold, tier in RISK_TIERS if final_score >= threshold)
    return round(final_score, 1), tier
