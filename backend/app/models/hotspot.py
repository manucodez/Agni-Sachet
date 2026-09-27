"""
`hotspots` — one row per fused thermal detection.

This is Step 2's output table from the architecture doc: every FIRMS
detection after it's been joined against OSM (nearest industrial polygon),
WorldCover (land-cover class) and WorldPop (population density).

nearest_power_plant_* and nearest_responder_* were added in the
best-practices merge (docs/MERGE_NOTES.md) to fix a real gap: this table
used to have only nearest_industrial_distance_m, and app/jobs/run_pipeline.py
copied that single value into BOTH the `distance_to_industrial_m` and
`distance_to_power_plant_m` model features — i.e. "distance to nearest
power plant" was never actually computed, it was a duplicate of "distance
to nearest industrial land parcel". The WRI Global Power Plant Database
(app/ingestion/power_plants.py) already carries a real per-plant
`fuel_type`, which is exactly what a gas-flare classifier needs and a
generic OSM `landuse=industrial` polygon can't give you, so it's worth a
dedicated join.
"""
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Hotspot(Base):
    __tablename__ = "hotspots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # --- raw FIRMS fields ---
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    acq_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sensor: Mapped[str] = mapped_column(String(32), nullable=False)  # MODIS | VIIRS_NOAA20 | VIIRS_NOAA21
    frp: Mapped[float] = mapped_column(Float, nullable=True)  # Fire Radiative Power (MW)
    brightness_temp: Mapped[float] = mapped_column(Float, nullable=True)  # K
    confidence: Mapped[str] = mapped_column(String(16), nullable=True)  # low | nominal | high
    daynight: Mapped[str] = mapped_column(String(1), nullable=True)  # D | N

    # --- fused context (Step 2) ---
    land_cover_class: Mapped[int] = mapped_column(Integer, nullable=True)
    nearest_industrial_distance_m: Mapped[float] = mapped_column(Float, nullable=True)
    nearest_industrial_id: Mapped[str] = mapped_column(String(64), nullable=True)
    population_density_nearby: Mapped[float] = mapped_column(Float, nullable=True)

    # Distinct from nearest_industrial_* above — see module docstring.
    # Sourced only from the WRI power-plant list, never from generic OSM
    # industrial polygons, so fuel_type is meaningful (not guessed).
    nearest_power_plant_distance_m: Mapped[float] = mapped_column(Float, nullable=True)
    nearest_power_plant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    nearest_power_plant_fuel_type: Mapped[str] = mapped_column(String(32), nullable=True)

    # Emergency-responder proximity (app/ingestion/osm.py responders layer).
    # Populated on a best-effort basis: None means "no fire station/hospital
    # found within the search radius," not "none exists" — see
    # run_ingestion.py's _nearest_from docstring.
    nearest_responder_distance_m: Mapped[float] = mapped_column(Float, nullable=True)
    nearest_responder_type: Mapped[str] = mapped_column(String(32), nullable=True)  # fire_station | hospital
    nearest_responder_name: Mapped[str] = mapped_column(String(256), nullable=True)

    # --- discovery (Step 3) ---
    cluster_id: Mapped[int] = mapped_column(Integer, ForeignKey("discovered_clusters.cluster_id"), nullable=True, index=True)

    cluster: Mapped["DiscoveredCluster"] = relationship(back_populates="hotspots")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Hotspot {self.sensor} {self.acq_datetime} ({self.lat:.3f},{self.lon:.3f})>"
