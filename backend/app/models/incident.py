"""
`incidents` — one row per triggered tiered-escalation workflow.

This is a DIFFERENT thing from `alerts` (app/models/alert.py): an Alert is
a single fire-and-forget CAP-style webhook payload with no notion of
"did anyone see this" — dispatch_alert() sends it and the row is written,
full stop. An Incident is stateful: it tracks who's been notified so far,
whether anyone has acknowledged it, and escalates to the next tier if
nobody has within escalation_interval_seconds. The two are complementary,
not a replacement for each other — see docs/ARCHITECTURE.md, "Alerting:
two layers." A single risk_tier L2/L3 pipeline pass writes both an Alert
(the CAP payload, for any system already consuming that feed) and, via
app/alerts/incident_dispatch.py, opens or escalates an Incident (the
human-facing, acknowledgeable workflow).

DELIBERATELY NO POSTGIS GEOMETRY COLUMN
------------------------------------------
Hotspot and DiscoveredCluster both carry a `geom` column for spatial
indexing/joins because they're queried spatially (nearest-X, bbox
filters). Incidents are looked up by id or ack_token and listed by
status/recency — never spatially joined — so centroid_lat/centroid_lon as
plain floats is sufficient and, as a side benefit, means this table (and
its tests) don't require a PostGIS-enabled database at all. If a future
need comes up (e.g. "show me all incidents within 5km of X"), add a geom
column then, following the Hotspot/DiscoveredCluster pattern.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Terminal and in-progress states. "auto_resolved" is distinct from
# "acknowledged": it means a later pipeline pass found the cluster's own
# risk_tier had dropped back to L0/L1 before any human acknowledged it —
# i.e. the fire likely burned out or was already handled, not that someone
# confirmed receipt. Keeping the two separate matters for any after-action
# review of response times.
STATUS_OPEN = "open"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_AUTO_RESOLVED = "auto_resolved"


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[int] = mapped_column(Integer, ForeignKey("discovered_clusters.cluster_id"), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_escalated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Snapshot of the triggering cluster state — kept even if the cluster
    # row itself changes later, so the incident record reads coherently on
    # its own during an after-action review.
    predicted_class: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(4), nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lon: Mapped[float] = mapped_column(Float, nullable=False)
    nearest_responder_distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nearest_responder_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    nearest_responder_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    current_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0, 1, 2
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_OPEN)

    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Unguessable token embedded in the tier-email "acknowledge" link
    # (see app/alerts/email_channel.py) — a UUID4 hex string, not a
    # sequential id, so the link can't be walked/enumerated.
    ack_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # JSON array of {"tier": int, "channel": str, "status": str, "at": iso timestamp, "recipient": str}
    # dicts — one entry per dispatch attempt, success or failure. This is
    # the audit trail for "did Tier 2 actually get notified, and when" —
    # see app/alerts/incident_dispatch.py's DispatchStatus.
    dispatch_log_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Incident {self.id} cluster={self.cluster_id} tier={self.current_tier} status={self.status}>"
