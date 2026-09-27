"""
Import every model here so `Base.metadata` (and Alembic's autogenerate,
which diffs against that metadata) knows about all of them. A model that
exists as a file but isn't imported here is invisible to migrations.
"""
from app.models.alert import Alert  # noqa: F401
from app.models.anomaly import AnomalyFlag  # noqa: F401
from app.models.cluster import DiscoveredCluster  # noqa: F401
from app.models.edge import ClusterEdge  # noqa: F401
from app.models.hotspot import Hotspot  # noqa: F401
from app.models.incident import Incident  # noqa: F401

__all__ = ["Hotspot", "DiscoveredCluster", "ClusterEdge", "AnomalyFlag", "Alert", "Incident"]
