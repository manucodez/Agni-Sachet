"""
Tiered incident-escalation workflow — app/alerts/incident_dispatch.py and
the /incidents API routes. Uses the same `client` fixture (a real DB
connection, see conftest.py) as the rest of this test suite, and asserts
against a fresh DiscoveredCluster row created per-test rather than mocking
the DB, matching this suite's existing style.

ALERT_DISPATCH_ENABLED is deliberately left at its default (False) here —
these tests confirm the state machine and the safety gate BOTH work, not
that a real email leaves the process (which would need real SMTP creds).
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.alerts.incident_dispatch import acknowledge_incident, trigger_or_escalate_incident
from app.core.db import SessionLocal
from app.models.cluster import DiscoveredCluster


@pytest.fixture
def cluster_id():
    """Creates a minimal real DiscoveredCluster row (the incidents table
    has a foreign-key constraint against it) and cleans up afterward."""
    with SessionLocal() as session:
        cluster = DiscoveredCluster(
            centroid_lat=26.9, centroid_lon=75.8,
            centroid_geom="SRID=4326;POINT(75.8 26.9)",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            total_detections=1, predicted_class="industrial_fire",
        )
        session.add(cluster)
        session.commit()
        session.refresh(cluster)
        cid = cluster.cluster_id

    yield cid

    with SessionLocal() as session:
        session.execute(text("DELETE FROM incidents WHERE cluster_id = :cid"), {"cid": cid})
        session.execute(text("DELETE FROM discovered_clusters WHERE cluster_id = :cid"), {"cid": cid})
        session.commit()


def test_trigger_creates_open_incident_at_tier_zero(cluster_id):
    with SessionLocal() as session:
        incident = trigger_or_escalate_incident(
            session, cluster_id=cluster_id, predicted_class="industrial_fire",
            risk_score=75.0, risk_tier="L2", centroid_lat=26.9, centroid_lon=75.8,
        )
        session.commit()
        assert incident is not None
        assert incident.status == "open"
        assert incident.current_tier == 0


def test_high_risk_score_dispatches_all_tiers_in_parallel(cluster_id):
    with SessionLocal() as session:
        incident = trigger_or_escalate_incident(
            session, cluster_id=cluster_id, predicted_class="industrial_fire",
            risk_score=95.0, risk_tier="L3", centroid_lat=26.9, centroid_lon=75.8,
        )
        session.commit()
        assert incident.current_tier == 2  # MAX_TIER — jumped straight there


def test_retriggering_open_incident_does_not_create_a_second_one(cluster_id):
    with SessionLocal() as session:
        first = trigger_or_escalate_incident(
            session, cluster_id=cluster_id, predicted_class="industrial_fire",
            risk_score=75.0, risk_tier="L2", centroid_lat=26.9, centroid_lon=75.8,
        )
        session.commit()
        first_id = first.id

        # Re-trigger immediately — escalation_interval_seconds hasn't
        # elapsed, so this should be a no-op (returns None), not a new
        # incident or an immediate escalation.
        second = trigger_or_escalate_incident(
            session, cluster_id=cluster_id, predicted_class="industrial_fire",
            risk_score=75.0, risk_tier="L2", centroid_lat=26.9, centroid_lon=75.8,
        )
        session.commit()
        assert second is None

        from sqlalchemy import select
        from app.models.incident import Incident
        count = len(session.execute(select(Incident).where(Incident.cluster_id == cluster_id)).scalars().all())
        assert count == 1


def test_acknowledge_stops_future_escalation(cluster_id):
    with SessionLocal() as session:
        incident = trigger_or_escalate_incident(
            session, cluster_id=cluster_id, predicted_class="industrial_fire",
            risk_score=75.0, risk_tier="L2", centroid_lat=26.9, centroid_lon=75.8,
        )
        session.commit()
        ack_token = incident.ack_token

        acked = acknowledge_incident(session, ack_token=ack_token, acknowledged_by="test-operator")
        session.commit()
        assert acked.status == "acknowledged"
        assert acked.acknowledged_by == "test-operator"


def test_acknowledge_unknown_token_returns_none(cluster_id):
    with SessionLocal() as session:
        assert acknowledge_incident(session, ack_token="not-a-real-token") is None


def test_simulate_endpoint_creates_incident_for_real_cluster(client, cluster_id):
    resp = client.post(f"/incidents/{cluster_id}/simulate", params={"risk_score": 80.0, "risk_tier": "L2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["cluster_id"] == cluster_id
    assert body["status"] == "open"


def test_simulate_endpoint_404s_for_nonexistent_cluster(client):
    resp = client.post("/incidents/999999999/simulate")
    assert resp.status_code == 404


def test_acknowledge_via_link_returns_html_confirmation(client, cluster_id):
    client.post(f"/incidents/{cluster_id}/simulate", params={"risk_score": 80.0, "risk_tier": "L2"})

    with SessionLocal() as session:
        from sqlalchemy import select
        from app.models.incident import Incident
        incident = session.execute(select(Incident).where(Incident.cluster_id == cluster_id)).scalars().first()
        ack_token = incident.ack_token

    resp = client.get(f"/incidents/{ack_token}/acknowledge")
    assert resp.status_code == 200
    assert "acknowledged" in resp.text.lower()
