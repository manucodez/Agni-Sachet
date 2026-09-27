"""
Step 5 — per-cluster anomaly detection against each site's OWN historical
baseline (never a global threshold — a 50MW steel plant's "normal" is a
30MW flare stack's "emergency").

Two things happen here:
  1. `ruptures` bidirectional changepoint detection on the FRP time series
     -> flags "spike" (sudden jump — possible new fire/accident) and
     "silence" (sudden drop to near-zero — possible sensor obstruction,
     smoke occlusion, or genuine extinguishment) events.
  2. A decay-curve fit on the FRP trend around each flagged point -> is the
     signature flat (stable, consistent with a routine flare), cooling
     (consistent with a fire being contained), or rising (consistent with
     an actively spreading event)? This is a cheap upgrade over a bare
     variance feature and becomes a classifier input (see features.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import ruptures as rpt
from scipy.optimize import curve_fit

logger = logging.getLogger(__name__)


@dataclass
class AnomalyEvent:
    cluster_id: int
    sensor: str
    timestamp: pd.Timestamp
    flag_type: str  # "spike" | "silence"
    severity_score: float
    baseline_value: float
    observed_value: float
    frp_trend: str  # "flat" | "cooling" | "rising" | "unknown"


def detect_changepoints(
    series: pd.DataFrame, cluster_id: int, sensor: str, penalty: float = 6.0
) -> list[AnomalyEvent]:
    """
    Args:
        series: rows for ONE cluster + ONE sensor, sorted by acq_datetime,
            with a `frp` column. Keeping sensor separate matters — VIIRS
            and MODIS have different noise floors and revisit cadences, so
            mixing them into one series would create spurious changepoints.
    """
    if len(series) < 8:
        return []  # not enough history for a meaningful changepoint fit

    values = series["frp"].fillna(0).to_numpy()
    algo = rpt.Pelt(model="rbf").fit(values)
    try:
        breakpoints = algo.predict(pen=penalty)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ruptures failed for cluster=%s sensor=%s: %s", cluster_id, sensor, exc)
        return []

    events: list[AnomalyEvent] = []
    prev_idx = 0
    for bp in breakpoints:
        if bp >= len(values):
            break
        window_before = values[prev_idx:bp]
        window_after = values[bp:min(bp + 5, len(values))]
        if len(window_before) == 0 or len(window_after) == 0:
            prev_idx = bp
            continue

        baseline = float(np.mean(window_before))
        observed = float(np.mean(window_after))
        delta = observed - baseline

        if baseline < 1e-6 and observed < 1e-6:
            prev_idx = bp
            continue

        flag_type = "spike" if delta > 0 else "silence"
        severity = abs(delta) / (baseline + 1.0)  # +1 avoids div-by-zero blowing up severity for tiny baselines

        trend_window = values[max(0, bp - 3):min(len(values), bp + 6)]
        trend = _classify_frp_trend(trend_window)

        events.append(
            AnomalyEvent(
                cluster_id=cluster_id,
                sensor=sensor,
                timestamp=series.iloc[bp]["acq_datetime"],
                flag_type=flag_type,
                severity_score=round(severity, 3),
                baseline_value=round(baseline, 2),
                observed_value=round(observed, 2),
                frp_trend=trend,
            )
        )
        prev_idx = bp

    return events


def _exp_decay(t: np.ndarray, a: float, k: float, c: float) -> np.ndarray:
    return a * np.exp(-k * t) + c


def _classify_frp_trend(values: np.ndarray, flat_threshold: float = 0.15) -> str:
    """Fits a simple exponential (decay/growth) curve to a short FRP window
    around a changepoint and buckets the fitted rate `k`:
      k < 0 (growing) and beyond threshold -> "rising"
      k > 0 (decaying) and beyond threshold -> "cooling"
      otherwise -> "flat" (stable — the classic flare signature)
    Falls back to "unknown" if the fit doesn't converge (common for very
    short or very noisy windows — that's fine, it's an optional feature).
    """
    if len(values) < 4 or np.all(values == values[0]):
        return "flat"

    t = np.arange(len(values), dtype=float)
    try:
        (a, k, c), _ = curve_fit(_exp_decay, t, values, p0=[values[0] - values[-1], 0.1, values[-1]], maxfev=2000)
    except Exception:  # noqa: BLE001 — fit failure just means "can't tell", not an error
        return "unknown"

    if abs(k) < flat_threshold:
        return "flat"
    return "cooling" if k > 0 else "rising"
