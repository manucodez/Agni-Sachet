from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HotspotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lat: float
    lon: float
    acq_datetime: datetime
    sensor: str
    frp: float | None = None
    brightness_temp: float | None = None
    confidence: str | None = None
    daynight: str | None = None
    land_cover_class: int | None = None
    nearest_industrial_distance_m: float | None = None
    nearest_industrial_id: str | None = None
    nearest_power_plant_distance_m: float | None = None
    nearest_power_plant_id: str | None = None
    nearest_power_plant_fuel_type: str | None = None
    nearest_responder_distance_m: float | None = None
    nearest_responder_type: str | None = None
    nearest_responder_name: str | None = None
    population_density_nearby: float | None = None
    cluster_id: int | None = None
