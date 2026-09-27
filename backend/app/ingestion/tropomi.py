"""
ADVANCED / PHASE 3 — chemical fingerprint channel.

Pulls Sentinel-5P TROPOMI trace-gas columns (SO2, NO2, CO, aerosol index)
for a single flagged cluster's cell and day, to use as a confirmation
feature alongside the thermal-only classifier — see docs/ARCHITECTURE.md
for the reasoning (sulfur-heavy plumes vs. routine flares vs. biomass
burning's CO/aerosol-dominant, SO2-light profile).

This is deliberately called on-demand for a handful of already-flagged
clusters (from app/ml/anomaly.py), never as a bulk daily pull — TROPOMI
swaths are large and this keeps the free-tier API usage trivial.

Two backends are supported; pick one via USE_GEE_BACKEND in .env:
  - Copernicus Data Space Ecosystem (CDSE) — OAuth2 client-credentials flow
  - Google Earth Engine (GEE) — service-account JSON

Both require a free account. Neither is wired into requirements.txt by
default — see backend/requirements-advanced.txt.
"""
import logging
from dataclasses import dataclass
from datetime import date

from app.core.config import settings

logger = logging.getLogger(__name__)

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"


@dataclass
class ChemicalFingerprint:
    so2_mol_m2: float | None
    no2_mol_m2: float | None
    co_mol_m2: float | None
    aerosol_index: float | None


class TropomiAdapter:
    """Not a full IngestionAdapter subclass — this is called synchronously,
    per-cluster, from the anomaly/classification step, not from the batch
    ingestion job. See app/jobs/run_pipeline.py for where it's invoked."""

    name = "tropomi"

    def fetch_fingerprint(self, lat: float, lon: float, day: date) -> ChemicalFingerprint:
        if settings.use_gee_backend:
            return self._fetch_via_gee(lat, lon, day)
        return self._fetch_via_cdse(lat, lon, day)

    def _get_cdse_token(self) -> str:
        import requests

        resp = requests.post(
            CDSE_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.cdse_client_id,
                "client_secret": settings.cdse_client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _fetch_via_cdse(self, lat: float, lon: float, day: date) -> ChemicalFingerprint:
        """Uses the Sentinel Hub Statistical API (part of CDSE) to get a mean
        value of each trace-gas band over a small bbox around the point for
        the given day. See:
        https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Statistical.html
        """
        import requests

        if not settings.cdse_client_id or not settings.cdse_client_secret:
            logger.warning("CDSE credentials not set — skipping chemical fingerprint")
            return ChemicalFingerprint(None, None, None, None)

        token = self._get_cdse_token()
        buffer_deg = 0.035  # roughly the 3.5km TROPOMI footprint half-width
        bbox = [lon - buffer_deg, lat - buffer_deg, lon + buffer_deg, lat + buffer_deg]

        values = {}
        for band, collection in (
            ("SO2", "sentinel-5p-l2-so2"),
            ("NO2", "sentinel-5p-l2-no2"),
            ("CO", "sentinel-5p-l2-co"),
            ("AER_AI", "sentinel-5p-l2-aer-ai"),
        ):
            payload = {
                "input": {
                    "bounds": {"bbox": bbox},
                    "data": [{"type": collection, "dataFilter": {"timeRange": {
                        "from": f"{day.isoformat()}T00:00:00Z", "to": f"{day.isoformat()}T23:59:59Z"
                    }}}],
                },
                "aggregation": {
                    "timeRange": {"from": f"{day.isoformat()}T00:00:00Z", "to": f"{day.isoformat()}T23:59:59Z"},
                    "aggregationInterval": {"of": "P1D"},
                    "evalscript": _EVALSCRIPTS[band],
                },
            }
            try:
                resp = requests.post(
                    CDSE_PROCESS_URL, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=60
                )
                resp.raise_for_status()
                stats = resp.json()["data"][0]["outputs"]["default"]["bands"]["B0"]["stats"]
                values[band] = stats.get("mean")
            except Exception as exc:  # noqa: BLE001 — best-effort confirmation channel
                logger.warning("TROPOMI %s fetch failed for (%s, %s) on %s: %s", band, lat, lon, day, exc)
                values[band] = None

        return ChemicalFingerprint(
            so2_mol_m2=values.get("SO2"),
            no2_mol_m2=values.get("NO2"),
            co_mol_m2=values.get("CO"),
            aerosol_index=values.get("AER_AI"),
        )

    def _fetch_via_gee(self, lat: float, lon: float, day: date) -> ChemicalFingerprint:
        """Google Earth Engine alternative — simpler auth (one service
        account JSON), no per-band evalscript needed. Requires the
        `earthengine-api` package from requirements-advanced.txt."""
        import ee

        ee.Initialize(ee.ServiceAccountCredentials(None, settings.gee_service_account_json_path))
        point = ee.Geometry.Point([lon, lat])
        day_str = day.isoformat()
        next_day = date.fromordinal(day.toordinal() + 1).isoformat()

        def mean_band(collection_id: str, band: str) -> float | None:
            coll = ee.ImageCollection(collection_id).filterDate(day_str, next_day).select(band)
            img = coll.mean()
            value = img.reduceRegion(ee.Reducer.mean(), point, scale=7000).get(band)
            return value.getInfo() if value is not None else None

        return ChemicalFingerprint(
            so2_mol_m2=mean_band("COPERNICUS/S5P/OFFL/L3_SO2", "SO2_column_number_density"),
            no2_mol_m2=mean_band("COPERNICUS/S5P/OFFL/L3_NO2", "NO2_column_number_density"),
            co_mol_m2=mean_band("COPERNICUS/S5P/OFFL/L3_CO", "CO_column_number_density"),
            aerosol_index=mean_band("COPERNICUS/S5P/OFFL/L3_AER_AI", "absorbing_aerosol_index"),
        )


_EVALSCRIPTS = {
    "SO2": """//VERSION=3
function setup() { return {input: ["SO2_column_number_density"], output: {bands: 1}}; }
function evaluatePixel(s) { return [s.SO2_column_number_density]; }""",
    "NO2": """//VERSION=3
function setup() { return {input: ["NO2_column_number_density"], output: {bands: 1}}; }
function evaluatePixel(s) { return [s.NO2_column_number_density]; }""",
    "CO": """//VERSION=3
function setup() { return {input: ["CO_column_number_density"], output: {bands: 1}}; }
function evaluatePixel(s) { return [s.CO_column_number_density]; }""",
    "AER_AI": """//VERSION=3
function setup() { return {input: ["absorbing_aerosol_index"], output: {bands: 1}}; }
function evaluatePixel(s) { return [s.absorbing_aerosol_index]; }""",
}
