"""Shared FastAPI dependencies. Re-exported so routes only import from here."""
from app.core.db import get_db  # noqa: F401
