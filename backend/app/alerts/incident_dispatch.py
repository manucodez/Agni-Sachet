"""
Tiered incident escalation — the stateful workflow layered on top of the
existing single-shot Alert/webhook (app/alerts/sachet.py).

DESIGN, ADAPTED FROM THE SIH26162 REFERENCE IMPLEMENTATION
--------------------------------------------------------------
The reference implementation's escalation engine (see docs/MERGE_NOTES.md)
established the pattern this module follows:

- Tiers are CUMULATIVE, not a handoff. Reaching Tier 2 means Tier 0, 1 AND
  2 have all been notified — escalation is "widen who knows," not "the
  next person takes over from the last."
- Sequential by default (one tier at a time, escalation_interval_seconds
  apart) UNLESS the risk score is high enough that waiting is itself the
  wrong call, in which case every tier is notified at once. A confirmed-
  looking L3 event isn't given the same 15-minute grace period as a
  borderline L2.
- Escalation only continues while the incident is unacknowledged. The
  moment someone acknowledges, escalation stops — the workflow deliberately
  does not use a fixed number of reminders and then stop-anyway, since
  "stop anyway" is exactly how a real fire gets missed.
- Re-triggering an already-open incident for the same cluster does NOT
  create a second incident or re-send tier 0 — see `_find_open_incident`.
  Without this, a cluster that stays at risk_tier L3 for six consecutive
  pipeline passes would generate six separate incidents (and six duplicate
  Tier 0 emails) rather than one incident escalating naturally.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.email_channel import build_incident_email_body, send_tier_email
from app.core.config import settings
from app.models.incident import STATUS_ACKNOWLEDGED, STATUS_AUTO_RESOLVED, STATUS_OPEN, Incident

logger = logging.getLogger(__name__)

MAX_TIER = 2


def get_open_incident_for_cluster(session: Session, cluster_id: int) -> Incident | None:
    """Public lookup — used by callers (e.g. the /incidents/{cluster_id}/simulate
    route) that need "what's the current open incident, if any" without
    triggering a new one."""
    stmt = select(Incident).where(Incident.cluster_id == cluster_id, Incident.status == STATUS_OPEN)
    return session.execute(stmt).scalars().first()


# Internal alias kept for readability at call sites within this module.
_find_open_incident = get_open_incident_for_cluster


def _log_dispatch(incident: Incident, tier: int, channel: str, status: str, recipients: list[str]) -> None:
    log = json.loads(incident.dispatch_log_json) if incident.dispatch_log_json else []
    log.append({
        "tier": tier, "channel": channel, "status": status,
        "recipients": recipients, "at": datetime.now(timezone.utc).isoformat(),
    })
    incident.dispatch_log_json = json.dumps(log)


def _dispatch_tier(incident: Incident, tier: int) -> None:
    # No "/api" prefix — app/main.py mounts routers directly at their
    # prefix (e.g. "/incidents", matching "/alerts", "/clusters" etc.),
    # not under a versioned/api-prefixed path.
    ack_url = f"{settings.public_base_url}/incidents/{incident.ack_token}/acknowledge"
    body = build_incident_email_body(
        tier_label=settings.incident_tier_label(tier),
        predicted_class=incident.predicted_class, risk_score=incident.risk_score, risk_tier=incident.risk_tier,
        lat=incident.centroid_lat, lon=incident.centroid_lon, ack_url=ack_url,
        nearest_responder_name=incident.nearest_responder_name,
        nearest_responder_distance_m=incident.nearest_responder_distance_m,
    )
    subject = f"[AGNI-SACHET] {incident.risk_tier} {incident.predicted_class} — {settings.incident_tier_label(tier)}"
    result = send_tier_email(tier=tier, subject=subject, body=body)
    _log_dispatch(incident, tier, "email", result.status.value, result.recipients)
    logger.info(
        "Incident %s: tier %d (%s) dispatch -> %s%s",
        incident.id, tier, settings.incident_tier_label(tier), result.status.value,
        f" ({result.detail})" if result.detail else "",
    )


def trigger_or_escalate_incident(
    session: Session, *, cluster_id: int, predicted_class: str, risk_score: float, risk_tier: str,
    centroid_lat: float, centroid_lon: float,
    nearest_responder_distance_m: float | None = None,
    nearest_responder_type: str | None = None,
    nearest_responder_name: str | None = None,
) -> Incident | None:
    """Call once per pipeline pass for any cluster whose risk_tier is L2/L3
    (same gate app/jobs/run_pipeline.py already applies before writing an
    Alert). Returns the Incident if one was created or escalated, or None
    if an already-open incident wasn't due for escalation yet.
    """
    now = datetime.now(timezone.utc)
    incident = _find_open_incident(session, cluster_id)

    if incident is None:
        incident = Incident(
            cluster_id=cluster_id, created_at=now, last_escalated_at=now,
            predicted_class=predicted_class, risk_score=risk_score, risk_tier=risk_tier,
            centroid_lat=centroid_lat, centroid_lon=centroid_lon,
            nearest_responder_distance_m=nearest_responder_distance_m,
            nearest_responder_type=nearest_responder_type, nearest_responder_name=nearest_responder_name,
            current_tier=0, status=STATUS_OPEN, ack_token=secrets.token_hex(24),
        )
        session.add(incident)
        session.flush()  # assign incident.id before dispatch builds the ack URL

        if risk_score >= settings.incident_parallel_dispatch_risk_score:
            # High-confidence severe event: don't make Tier 1/2 wait behind
            # a timer for something already unambiguous.
            for tier in range(MAX_TIER + 1):
                _dispatch_tier(incident, tier)
            incident.current_tier = MAX_TIER
        else:
            _dispatch_tier(incident, 0)
            incident.current_tier = 0

        return incident

    # Already open — escalate only if still unacknowledged, not yet at the
    # top tier, and enough time has passed since the last escalation.
    if incident.status != STATUS_OPEN:
        return None
    if incident.current_tier >= MAX_TIER:
        return None
    if now - incident.last_escalated_at < timedelta(seconds=settings.escalation_interval_seconds):
        return None

    incident.current_tier += 1
    incident.last_escalated_at = now
    _dispatch_tier(incident, incident.current_tier)
    return incident


def auto_resolve_if_subsided(session: Session, *, cluster_id: int, risk_tier: str) -> Incident | None:
    """Call for every cluster each pipeline pass, regardless of current
    risk_tier — closes an open incident whose cluster has dropped back to
    L0/L1 without ever being acknowledged. This is a DIFFERENT terminal
    state from acknowledgement (see app/models/incident.py) precisely so
    an after-action review can tell "someone responded" apart from
    "the model just stopped seeing it, nobody confirmed anything."
    """
    if risk_tier in ("L2", "L3"):
        return None
    incident = _find_open_incident(session, cluster_id)
    if incident is None:
        return None
    incident.status = STATUS_AUTO_RESOLVED
    logger.info("Incident %s auto-resolved: cluster %s risk_tier dropped to %s unacknowledged", incident.id, cluster_id, risk_tier)
    return incident


def acknowledge_incident(session: Session, *, ack_token: str, acknowledged_by: str | None = None) -> Incident | None:
    stmt = select(Incident).where(Incident.ack_token == ack_token)
    incident = session.execute(stmt).scalars().first()
    return _apply_acknowledgement(incident, acknowledged_by)


def acknowledge_incident_by_id(session: Session, *, incident_id, acknowledged_by: str | None = None) -> Incident | None:
    """Same effect as acknowledge_incident, keyed by primary key instead of
    the emailed ack_token — for a dashboard where the viewer already has
    API access to the incident list (and so already has the id), rather
    than for the public one-click email link. Kept as a separate function
    (not an overload) so it's obvious at each call site which trust model
    applies — see app/api/routes/incidents.py for both routes."""
    incident = session.get(Incident, incident_id)
    return _apply_acknowledgement(incident, acknowledged_by)


def _apply_acknowledgement(incident: Incident | None, acknowledged_by: str | None) -> Incident | None:
    if incident is None:
        return None
    if incident.status == STATUS_OPEN:
        incident.status = STATUS_ACKNOWLEDGED
        incident.acknowledged_at = datetime.now(timezone.utc)
        incident.acknowledged_by = acknowledged_by or "unspecified"
    return incident
