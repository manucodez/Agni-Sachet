"""
The core "discovered site" endpoints. These back the dashboard's map
markers, the detail panel when a marker is clicked, and the graph overlay.

GET /clusters                       -> list, filterable by class / min risk
GET /clusters/geojson                -> same, as GeoJSON points for Leaflet
GET /clusters/{id}                   -> single cluster detail
GET /clusters/{id}/history            -> per-sensor FRP/brightness time series
GET /clusters/{id}/connections        -> graph edges (physical + wind), both directions
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.cluster import DiscoveredCluster
from app.models.edge import ClusterEdge
from app.models.hotspot import Hotspot
from app.schemas.cluster import ClusterConnection, ClusterHistoryPoint, ClusterOut

router = APIRouter()


@router.get("", response_model=list[ClusterOut])
def list_clusters(
    predicted_class: str | None = Query(None),
    min_risk: float | None = Query(None, ge=0, le=100),
    risk_tier: str | None = Query(None, description="L0 | L1 | L2 | L3"),
    db: Session = Depends(get_db),
) -> list[DiscoveredCluster]:
    stmt = select(DiscoveredCluster)
    if predicted_class is not None:
        stmt = stmt.where(DiscoveredCluster.predicted_class == predicted_class)
    if min_risk is not None:
        stmt = stmt.where(DiscoveredCluster.risk_score >= min_risk)
    if risk_tier is not None:
        stmt = stmt.where(DiscoveredCluster.risk_tier == risk_tier)
    return list(db.execute(stmt.order_by(DiscoveredCluster.risk_score.desc())).scalars().all())


@router.get("/geojson")
def list_clusters_geojson(
    predicted_class: str | None = Query(None),
    min_risk: float | None = Query(None, ge=0, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(DiscoveredCluster)
    if predicted_class is not None:
        stmt = stmt.where(DiscoveredCluster.predicted_class == predicted_class)
    if min_risk is not None:
        stmt = stmt.where(DiscoveredCluster.risk_score >= min_risk)
    rows = db.execute(stmt).scalars().all()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c.centroid_lon, c.centroid_lat]},
            "properties": {
                "cluster_id": c.cluster_id,
                "predicted_class": c.predicted_class,
                "classification_confidence": c.classification_confidence,
                "risk_score": c.risk_score,
                "risk_tier": c.risk_tier,
                "total_detections": c.total_detections,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            },
        }
        for c in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/{cluster_id}", response_model=ClusterOut)
def get_cluster(cluster_id: int, db: Session = Depends(get_db)) -> DiscoveredCluster:
    cluster = db.get(DiscoveredCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"cluster {cluster_id} not found")
    return cluster


@router.get("/{cluster_id}/history", response_model=list[ClusterHistoryPoint])
def get_cluster_history(cluster_id: int, db: Session = Depends(get_db)) -> list[Hotspot]:
    stmt = (
        select(Hotspot)
        .where(Hotspot.cluster_id == cluster_id)
        .order_by(Hotspot.acq_datetime.asc())
    )
    rows = list(db.execute(stmt).scalars().all())
    if not rows:
        raise HTTPException(status_code=404, detail=f"no history for cluster {cluster_id}")
    return rows


@router.get("/{cluster_id}/connections", response_model=list[ClusterConnection])
def get_cluster_connections(cluster_id: int, db: Session = Depends(get_db)) -> list[ClusterEdge]:
    """Both edge types, either direction — a cluster can be the source of a
    pipeline edge and the target of a wind edge at the same time."""
    stmt = select(ClusterEdge).where(
        or_(ClusterEdge.source_cluster_id == cluster_id, ClusterEdge.target_cluster_id == cluster_id)
    )
    edges = list(db.execute(stmt).scalars().all())
    return [
        ClusterConnection(
            target_cluster_id=(e.target_cluster_id if e.source_cluster_id == cluster_id else e.source_cluster_id),
            edge_type=e.edge_type,
            connection_detail=e.connection_detail,
            weight=e.weight,
        )
        for e in edges
    ]
