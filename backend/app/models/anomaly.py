"""
`anomaly_flags` — Step 5 output. One row per changepoint event detected
against a cluster's own historical baseline (never a global threshold).
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AnomalyFlag(Base):
    __tablename__ = "anomaly_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("discovered_clusters.cluster_id"), nullable=False, index=True)
    sensor: Mapped[str] = mapped_column(String(32), nullable=False)

    flag_type: Mapped[str] = mapped_column(String(8), nullable=False)  # "spike" | "silence"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    severity_score: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # decay-curve fit result (Phase 1 upgrade to the plain variance feature):
    # "flat" (stable flare) | "cooling" (being contained) | "rising" (spreading)
    frp_trend: Mapped[str | None] = mapped_column(String(16), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnomalyFlag cluster={self.cluster_id} {self.flag_type} sev={self.severity_score:.2f}>"
