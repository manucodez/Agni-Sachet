"""
Shared pytest fixtures. The `client` fixture spins up the FastAPI app
against whatever DATABASE_URL is set in the test environment — CI points
this at a throwaway PostGIS service (see .github/workflows/ci.yml); running
locally, `make test` runs inside the backend container against the same
postgis service as the dev stack, so no separate test DB setup is needed
for a hackathon-scale project.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
