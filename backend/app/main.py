"""
FastAPI entrypoint. Run with:
    uvicorn app.main:app --reload
(or `make up`, which does this inside Docker).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, clusters, health, hotspots, incidents
from app.core.config import settings
from app.core.db import init_postgis_extension

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("agni_sachet")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    init_postgis_extension()
    yield


app = FastAPI(
    title="Agni Sachet API",
    description=(
        "AI-based classification and monitoring of industrial fires and "
        "persistent thermal sources, fusing NASA FIRMS, OSM, land-cover and "
        "population data over a discovered-site + correlation-graph model."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(hotspots.router, prefix="/hotspots", tags=["hotspots"])
app.include_router(clusters.router, prefix="/clusters", tags=["clusters"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
