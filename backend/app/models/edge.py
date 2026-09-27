"""
`cluster_edges` — the heterogeneous correlation graph from Step 4.

Two edge types live in the same table, distinguished by `edge_type`:
  - "physical": clusters share OSM pipeline/transmission/rail infrastructure
  - "wind": cluster B was downwind of cluster A within a plausible
            plume-travel window at the time of A's anomaly (Phase 3 addition)

Keeping both in one table (rather than a separate wind-edges table) makes
cross-graph correlation (Step 6) a single query instead of a union.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ClusterEdge(Base):
    __tablename__ = "cluster_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    source_cluster_id: Mapped[int] = mapped_column(ForeignKey("discovered_clusters.cluster_id"), nullable=False, index=True)
    target_cluster_id: Mapped[int] = mapped_column(ForeignKey("discovered_clusters.cluster_id"), nullable=False, index=True)

    edge_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "physical" | "wind"
    # for physical edges: pipeline | transmission | rail
    # for wind edges: the wind bearing (degrees) that produced the link, as a string
    connection_detail: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Wind edges are time-scoped (a given wind direction only holds for hours);
    # physical edges leave these null since infrastructure doesn't expire.
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # e.g. plume-alignment confidence for wind edges

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Edge {self.source_cluster_id}->{self.target_cluster_id} ({self.edge_type})>"
