from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HotspotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lat: float
    lon: float
    acq_datetime: datetime
    sensor: str
    frp: Optional[float] = None
    brightness_temp: Optional[float] = None
    confidence: Optional[str] = None
    daynight: Optional[str] = None
    land_cover_class: Optional[int] = None
    nearest_industrial_distance_m: Optional[float] = None
    nearest_industrial_id: Optional[str] = None
    population_density_nearby: Optional[float] = None
    cluster_id: Optional[int] = None
