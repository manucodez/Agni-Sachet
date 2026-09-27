"""
`alerts` — Step 12 output. Anything crossing a severity threshold, either
a single-cluster classification or a cross-graph correlated event, lands
here in a shape that maps directly onto NDMA SACHET's expected fields.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # matches predicted_class, or "correlated_event"
    severity: Mapped[str] = mapped_column(String(4), nullable=False)  # L0-L3 risk tier at time of alert
    location_lat: Mapped[float] = mapped_column(Float, nullable=False)
    location_lon: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)

    cluster_ids_involved: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    edge_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # set only for correlated events

    sachet_payload: Mapped[dict] = mapped_column(JSON, nullable=False)  # the exact outbound payload, for audit
    delivered: Mapped[bool] = mapped_column(default=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Alert {self.event_type} {self.severity} {self.created_at}>"
