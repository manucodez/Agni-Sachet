"""
`discovered_clusters` — one row per persistent thermal source found by
HDBSCAN (Step 3), enriched with classification (Step 7), risk score
(Step 8) and graph centrality (Step 4).

This is the row a judge or analyst actually looks at: "this specific
facility, classified as X, with this risk score."
"""
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DiscoveredCluster(Base):
    __tablename__ = "discovered_clusters"

    cluster_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lon: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_geom = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_detections: Mapped[int] = mapped_column(Integer, default=0)

    # --- classification (Step 7) ---
    # industrial_fire | gas_flare | mining | agricultural_burn | wildfire | other | unclassified
    predicted_class: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_reasons_json: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON-encoded SHAP top-3

    # Set only when app/ml/serving_guards.py overrides the raw model output
    # (e.g. "reclassified other -> wildfire: dense forest cover, no
    # industrial override applies"). NULL means the served class is exactly
    # what the classifier predicted. This is deliberately visible on the
    # row (and surfaced in the API/alert payload) rather than silently
    # swapping the label — see docs/ARCHITECTURE.md "Serving guards".
    classification_override_note: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- advanced evidence fusion (Phase 3) — nullable, filled only when run ---
    chem_fingerprint_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sar_structural_change_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gfm_novelty_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- graph (Step 4) ---
    centrality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- risk (Step 8) ---
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100
    risk_tier: Mapped[str | None] = mapped_column(String(4), nullable=True)  # L0 | L1 | L2 | L3

    # "Hotspot" as a string here is a forward reference to the model in
    # app/models/hotspot.py, resolved by SQLAlchemy at mapper-configuration
    # time (after both model modules have been imported via
    # app/models/__init__.py) — not a name ruff's static analysis can see,
    # hence the noqa. This is the standard SQLAlchemy 2.0 pattern for a
    # relationship between two models that would otherwise need a circular
    # import.
    hotspots: Mapped[list["Hotspot"]] = relationship(back_populates="cluster")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Cluster {self.cluster_id} {self.predicted_class} risk={self.risk_score}>"
