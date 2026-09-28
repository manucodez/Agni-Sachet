
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.alert import Alert
from app.schemas.alert import AlertOut

router = APIRouter()


@router.get("", response_model=list[AlertOut])
def list_alerts(
    severity: str | None = Query(None, description="L0 | L1 | L2 | L3"),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
    return list(db.execute(stmt).scalars().all())
