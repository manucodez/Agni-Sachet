from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness + DB connectivity check. Point your uptime monitor here."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
