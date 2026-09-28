"""
Tiered incident-escalation endpoints. See app/alerts/incident_dispatch.py
for the state machine these wrap, and app/models/incident.py for why this
is a separate table/workflow from the existing /alerts feed.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.incident_dispatch import (
    acknowledge_incident,
    acknowledge_incident_by_id,
    get_open_incident_for_cluster,
    trigger_or_escalate_incident,
)
from app.api.deps import get_db
from app.models.cluster import DiscoveredCluster
from app.models.incident import Incident
from app.schemas.incident import AcknowledgeRequest, IncidentOut

router = APIRouter()


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    status: str | None = Query(None, description="open | acknowledged | auto_resolved"),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(Incident.status == status)
    return list(db.execute(stmt).scalars().all())


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: str, db: Session = Depends(get_db)) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/{ack_token}/acknowledge", response_class=HTMLResponse)
def acknowledge_via_link(ack_token: str, by: str | None = Query(None), db: Session = Depends(get_db)) -> str:
    """The link embedded in tier-escalation emails (app/alerts/email_channel.py)
    — a plain GET so it works as a one-click link from any mail client,
    which is why this is separate from the JSON POST endpoint below rather
    than the same route doing double duty."""
    incident = acknowledge_incident(db, ack_token=ack_token, acknowledged_by=by)
    if incident is None:
        return "<html><body><h3>Unknown or expired acknowledgement link.</h3></body></html>"
    db.commit()
    return (
        "<html><body style='font-family: sans-serif; max-width: 480px; margin: 4rem auto;'>"
        f"<h2>Incident acknowledged</h2>"
        f"<p>Cluster {incident.cluster_id} ({incident.predicted_class}, {incident.risk_tier}) "
        f"marked as acknowledged{' by ' + incident.acknowledged_by if incident.acknowledged_by else ''}. "
        "Escalation to further tiers has stopped.</p>"
        "</body></html>"
    )


@router.post("/{ack_token}/acknowledge", response_model=IncidentOut)
def acknowledge_via_api(ack_token: str, body: AcknowledgeRequest, db: Session = Depends(get_db)) -> Incident:
    incident = acknowledge_incident(db, ack_token=ack_token, acknowledged_by=body.acknowledged_by)
    if incident is None:
        raise HTTPException(status_code=404, detail="Unknown acknowledgement token")
    db.commit()
    return incident


@router.post("/id/{incident_id}/acknowledge", response_model=IncidentOut)
def acknowledge_by_id(incident_id: str, body: AcknowledgeRequest, db: Session = Depends(get_db)) -> Incident:
    """Same effect as the ack_token route above, for a caller that already
    has the incident id (e.g. the frontend dashboard, which lists incidents
    via GET /incidents and deliberately isn't sent the ack_token — that
    token is for the one-click email link, not general API reads). Trust
    model differs: this route assumes whoever can call it already has
    legitimate API access to see the incident, same as any other
    authenticated dashboard action."""
    incident = acknowledge_incident_by_id(db, incident_id=incident_id, acknowledged_by=body.acknowledged_by)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    db.commit()
    return incident


@router.post("/{cluster_id}/simulate", response_model=IncidentOut)
def simulate_incident(
    cluster_id: int,
    risk_score: float = Query(95.0, description="Override risk score for the demo trigger"),
    risk_tier: str = Query("L3", description="Override risk tier for the demo trigger"),
    db: Session = Depends(get_db),
) -> Incident:
    """Manually fires the escalation workflow for an existing, already-
    discovered cluster — for live demos and judge Q&A ("show me what
    happens when a fire is confirmed") without waiting for a real
    detection to cross the risk threshold naturally. Requires a real
    cluster_id (the incidents table has a foreign-key constraint against
    discovered_clusters) rather than accepting an arbitrary fake location,
    so a demo trigger always points at real ingested data, never at
    coordinates invented for the occasion.
    """
    cluster = db.get(DiscoveredCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"No discovered cluster with id {cluster_id}")

    incident = trigger_or_escalate_incident(
        db, cluster_id=cluster_id,
        predicted_class=cluster.predicted_class or "industrial_fire",
        risk_score=risk_score, risk_tier=risk_tier,
        centroid_lat=cluster.centroid_lat, centroid_lon=cluster.centroid_lon,
    )
    db.commit()
    if incident is None:
        # An open incident already existed and wasn't due for escalation —
        # return its current state rather than erroring, since "nothing
        # changed" is a legitimate outcome, not a failure.
        incident = get_open_incident_for_cluster(db, cluster_id)
    if incident is None:  # pragma: no cover — defensive, shouldn't happen
        raise HTTPException(status_code=500, detail="Incident trigger did not return a row")
    return incident
