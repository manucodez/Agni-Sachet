"""API-facing schemas for clusters. Kept separate from the ORM models so the
wire format can evolve independently of the storage schema."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    centroid_lat: float
    centroid_lon: float
    first_seen: datetime
    last_seen: datetime
    total_detections: int

    predicted_class: Optional[str] = None
    classification_confidence: Optional[float] = None
    classification_override_note: Optional[str] = None

    chem_fingerprint_score: Optional[float] = None
    sar_structural_change_score: Optional[float] = None
    gfm_novelty_score: Optional[float] = None

    centrality_score: Optional[float] = None
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None


class ClusterHistoryPoint(BaseModel):
    acq_datetime: datetime
    sensor: str
    frp: Optional[float] = None
    brightness_temp: Optional[float] = None


class ClusterConnection(BaseModel):
    target_cluster_id: int
    edge_type: str
    connection_detail: Optional[str] = None
    weight: Optional[float] = None
