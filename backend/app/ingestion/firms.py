"""
NASA FIRMS Area API adapter.

Docs: https://firms.modaps.eosdis.nasa.gov/api/area/
Free MAP_KEY: https://firms.modaps.eosdis.nasa.gov/api/map_key/

One request per sensor (the Area API takes a single source per call), so
`fetch()` loops over settings.firms_sensor_list and concatenates results.
"""
import io
import logging
from datetime import UTC, datetime

import pandas as pd
import requests

from app.core.config import settings
from app.ingestion.base import IngestionAdapter

logger = logging.getLogger(__name__)

FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{sensor}/{bbox}/{day_range}"


class FirmsAdapter(IngestionAdapter):
    name = "firms"

    def fetch(self, **kwargs) -> pd.DataFrame:
        if not settings.firms_map_key:
            raise RuntimeError(
                "FIRMS_MAP_KEY is not set. Get a free key at "
                "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and put it in .env"
            )

        bbox = kwargs.get("bbox", settings.firms_bbox)
        day_range = kwargs.get("day_range", settings.firms_day_range)

        frames = []
        for sensor in settings.firms_sensor_list:
            url = FIRMS_AREA_URL.format(
                map_key=settings.firms_map_key, sensor=sensor, bbox=bbox, day_range=day_range
            )
            logger.info("Fetching FIRMS %s: %s", sensor, url)
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            if df.empty:
                continue
            df["sensor_source"] = sensor
            frames.append(df)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def to_records(self, raw: pd.DataFrame) -> list[dict]:
        if raw.empty:
            return []

        records = []
        for _, row in raw.iterrows():
            # VIIRS uses bright_ti4/bright_ti5; MODIS uses `brightness`.
            brightness = row.get("bright_ti4", row.get("brightness"))
            acq_dt = datetime.strptime(
                f"{row['acq_date']} {int(row['acq_time']):04d}", "%Y-%m-%d %H%M"
            ).replace(tzinfo=UTC)

            records.append(
                {
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "acq_datetime": acq_dt,
                    "sensor": _normalize_sensor_name(row.get("satellite"), row["sensor_source"]),
                    "frp": float(row.get("frp", 0) or 0),
                    "brightness_temp": float(brightness) if pd.notna(brightness) else None,
                    "confidence": str(row.get("confidence", "")),
                    "daynight": str(row.get("daynight", "")),
                }
            )
        return records


def _normalize_sensor_name(satellite: str, sensor_source: str) -> str:
    """Collapse FIRMS' (satellite, instrument) pair into the label the rest
    of the app uses. VIIRS_SNPP is deliberately treated as legacy-only —
    see docs/DATA_SOURCES.md for why."""
    if "MODIS" in sensor_source:
        return "MODIS"
    if "NOAA20" in sensor_source:
        return "VIIRS_NOAA20"
    if "NOAA21" in sensor_source:
        return "VIIRS_NOAA21"
    return "VIIRS_SNPP"
