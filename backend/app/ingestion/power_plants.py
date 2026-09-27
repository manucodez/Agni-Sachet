"""
WRI Global Power Plant Database — a free, direct-download CSV of named,
authoritative power plant locations (operator, fuel type, capacity_mw).

This exists as a *second* source of industrial infrastructure alongside
OSM specifically because OSM tagging completeness varies a lot by region —
a plant WRI has on record but OSM doesn't tag correctly should still show
up as a nearest-industrial match in Step 2, and should still be a graph
node candidate in Step 4. Treat WRI + OSM as complementary, not either/or:
cross-reference by proximity when building the graph rather than picking one.
"""
import io
import logging

import pandas as pd
import requests

from app.core.config import settings
from app.ingestion.base import IngestionAdapter

logger = logging.getLogger(__name__)


class PowerPlantsAdapter(IngestionAdapter):
    name = "power_plants"

    def fetch(self, **kwargs) -> pd.DataFrame:
        logger.info("Downloading WRI Global Power Plant Database")
        resp = requests.get(settings.wri_power_plants_url, timeout=60)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        return df[df["country"] == "IND"].copy()

    def to_records(self, raw: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in raw.iterrows():
            if pd.isna(row.get("latitude")) or pd.isna(row.get("longitude")):
                continue
            records.append(
                {
                    "wri_id": row.get("gppd_idnr"),
                    "name": row.get("name"),
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "fuel_type": row.get("primary_fuel"),
                    "capacity_mw": row.get("capacity_mw"),
                    "category": "power_plant_authoritative",
                }
            )
        logger.info("WRI power plants (India): %d records", len(records))
        return records
