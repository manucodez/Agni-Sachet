"""
GET /hotspots            -> filtered list (JSON)
GET /hotspots/geojson     -> same filters, as a GeoJSON FeatureCollection
                             (this is what the Leaflet layer actually consumes)

Example: GET /hotspots?predicted_class=industrial_fire&since=2026-08-01
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.cluster import DiscoveredCluster
from app.models.hotspot import Hotspot
from app.schemas.hotspot import HotspotOut

router = APIRouter()


def _apply_filters(
    stmt,
    predicted_class: str | None,
    since: datetime | None,
    min_frp: float | None,
):
    if since is not None:
        stmt = stmt.where(Hotspot.acq_datetime >= since)
    if min_frp is not None:
        stmt = stmt.where(Hotspot.frp >= min_frp)
    if predicted_class is not None:
        stmt = stmt.join(DiscoveredCluster, Hotspot.cluster_id == DiscoveredCluster.cluster_id).where(
            DiscoveredCluster.predicted_class == predicted_class
        )
    return stmt


@router.get("", response_model=list[HotspotOut])
def list_hotspots(
    predicted_class: str | None = Query(None, description="industrial_fire | gas_flare | mining | agricultural_burn | wildfire | other | unclassified"),
    since: datetime | None = Query(None, description="ISO timestamp lower bound on acq_datetime"),
    min_frp: float | None = Query(None, description="Minimum Fire Radiative Power (MW)"),
    limit: int = Query(1000, le=10000),
    db: Session = Depends(get_db),
) -> list[Hotspot]:
    stmt = select(Hotspot).order_by(Hotspot.acq_datetime.desc()).limit(limit)
    stmt = _apply_filters(stmt, predicted_class, since, min_frp)
    return list(db.execute(stmt).scalars().all())


@router.get("/geojson")
def list_hotspots_geojson(
    predicted_class: str | None = Query(None),
    since: datetime | None = Query(None),
    min_frp: float | None = Query(None),
    limit: int = Query(5000, le=20000),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Hotspot).order_by(Hotspot.acq_datetime.desc()).limit(limit)
    stmt = _apply_filters(stmt, predicted_class, since, min_frp)
    rows = db.execute(stmt).scalars().all()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [h.lon, h.lat]},
            "properties": {
                "id": str(h.id),
                "acq_datetime": h.acq_datetime.isoformat(),
                "sensor": h.sensor,
                "frp": h.frp,
                "brightness_temp": h.brightness_temp,
                "confidence": h.confidence,
                "cluster_id": h.cluster_id,
            },
        }
        for h in rows
    ]
    return {"type": "FeatureCollection", "features": features}
