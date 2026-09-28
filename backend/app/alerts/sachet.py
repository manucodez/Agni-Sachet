"""
Step 12 — formats a classified/scored cluster (or a correlated cross-graph
event) into a payload shaped like NDMA SACHET's Common Alerting Protocol
(CAP)-derived schema, so this system's output could plug into an existing
alert-distribution pipeline rather than inventing a parallel one.

SACHET_WEBHOOK_URL is optional — leave it blank in dev and alerts just get
persisted + shown in the dashboard feed (app/api/routes/alerts.py).
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

EVENT_DESCRIPTIONS = {
    "industrial_fire": "Possible industrial fire or accident detected",
    "gas_flare": "Persistent gas flare thermal signature",
    "mining": "Mining-related thermal activity",
    "agricultural_burn": "Agricultural burning detected",
    "wildfire": "Wildfire / forest fire detected",
    "other": "Unclassified persistent thermal source",
    "unclassified": "Anomalous thermal event not matching known categories — needs manual review",
    "correlated_event": "Correlated anomaly across connected facilities",
}


def build_sachet_payload(
    *,
    cluster_id: int,
    predicted_class: str,
    lat: float,
    lon: float,
    risk_score: float,
    risk_tier: str,
    involved_cluster_ids: list[int] | None = None,
    extra_evidence: dict | None = None,
) -> dict:
    return {
        "identifier": str(uuid.uuid4()),
        "sender": "agni-sachet@team-neuron",
        "sent": datetime.now(UTC).isoformat(),
        "status": "Actual",
        "msgType": "Alert",
        "scope": "Restricted",
        "info": {
            "category": "Fire",
            "event": EVENT_DESCRIPTIONS.get(predicted_class, "Thermal anomaly detected"),
            "urgency": {"L3": "Immediate", "L2": "Expected", "L1": "Future", "L0": "Past"}[risk_tier],
            "severity": {"L3": "Extreme", "L2": "Severe", "L1": "Moderate", "L0": "Minor"}[risk_tier],
            "certainty": "Likely" if risk_score >= 60 else "Possible",
            "area": {
                "areaDesc": f"cluster_{cluster_id}",
                "circle": f"{lat},{lon} 2.0",  # 2km radius, CAP's "lat,lon radius_km" format
            },
            "parameter": [
                {"valueName": "predicted_class", "value": predicted_class},
                {"valueName": "risk_score", "value": str(risk_score)},
                {"valueName": "involved_clusters", "value": ",".join(map(str, involved_cluster_ids or [cluster_id]))},
                *[{"valueName": k, "value": str(v)} for k, v in (extra_evidence or {}).items()],
            ],
        },
    }


def dispatch_alert(payload: dict) -> bool:
    """Returns True if delivered (or if no webhook is configured, in which
    case it's a local-only alert and that's a valid dev-mode outcome, not
    a failure).

    Gated on settings.alert_dispatch_enabled (default False) as well as
    the webhook URL being set — the SAME master switch that gates tier
    emails in app/alerts/incident_dispatch.py. Before this, a stale
    SACHET_WEBHOOK_URL left in a .env from a previous session would fire
    for real on the next demo/test run with no way to disable just this
    channel independently; now there's one switch that reliably silences
    every outbound alert channel this codebase has, which matters most
    exactly when you're least thinking about it (replaying historical
    data, running CI, or demoing on a judge's network).
    """
    if not settings.alert_dispatch_enabled:
        logger.info("[DRY RUN] ALERT_DISPATCH_ENABLED=false — alert %s stored locally only, not sent", payload["identifier"])
        return False
    if not settings.sachet_webhook_url:
        logger.info("SACHET_WEBHOOK_URL not set — alert %s stored locally only", payload["identifier"])
        return False

    try:
        resp = requests.post(settings.sachet_webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Failed to dispatch alert %s to SACHET: %s", payload["identifier"], exc)
        return False
