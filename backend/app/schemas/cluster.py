"""API-facing schemas for clusters. Kept separate from the ORM models so the
wire format can evolve independently of the storage schema."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    centroid_lat: float
    centroid_lon: float
    first_seen: datetime
    last_seen: datetime
    total_detections: int

    predicted_class: str | None = None
    classification_confidence: float | None = None
    classification_override_note: str | None = None

    chem_fingerprint_score: float | None = None
    sar_structural_change_score: float | None = None
    gfm_novelty_score: float | None = None

    centrality_score: float | None = None
    risk_score: float | None = None
    risk_tier: str | None = None


class ClusterHistoryPoint(BaseModel):
    acq_datetime: datetime
    sensor: str
    frp: float | None = None
    brightness_temp: float | None = None


class ClusterConnection(BaseModel):
    target_cluster_id: int
    edge_type: str
    connection_detail: str | None = None
    weight: float | None = None
