"""API-facing schemas for the tiered incident-escalation workflow."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cluster_id: int
    created_at: datetime
    last_escalated_at: datetime
    predicted_class: str
    risk_score: float
    risk_tier: str
    centroid_lat: float
    centroid_lon: float
    nearest_responder_distance_m: Optional[float] = None
    nearest_responder_type: Optional[str] = None
    nearest_responder_name: Optional[str] = None
    current_tier: int
    status: str
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None


class AcknowledgeRequest(BaseModel):
    acknowledged_by: Optional[str] = None
