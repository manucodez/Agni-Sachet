from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    event_type: str
    severity: str
    location_lat: float
    location_lon: float
    description: str
    cluster_ids_involved: list[int]
    edge_id: Optional[int] = None
    sachet_payload: dict[str, Any]
    delivered: bool
