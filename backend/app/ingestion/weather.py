"""
ADVANCED / PHASE 3 — wind data for the second graph-edge type.

Open-Meteo's historical/forecast API needs no key and is the default; set
USE_ERA5=true if you have Copernicus Climate Data Store access and want
reanalysis-grade wind fields instead. Either way this returns the same
shape, so app/graph/wind_edges.py doesn't care which backend produced it.
"""
import logging
from dataclasses import dataclass
from datetime import datetime

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


@dataclass
class WindReading:
    wind_speed_ms: float
    wind_direction_deg: float  # meteorological convention: direction wind is blowing FROM


class WeatherAdapter:
    name = "weather"

    def fetch_wind(self, lat: float, lon: float, when: datetime) -> WindReading | None:
        if settings.use_era5:
            return self._fetch_era5(lat, lon, when)
        return self._fetch_open_meteo(lat, lon, when)

    def _fetch_open_meteo(self, lat: float, lon: float, when: datetime) -> WindReading | None:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": when.date().isoformat(),
            "end_date": when.date().isoformat(),
            "hourly": "wind_speed_10m,wind_direction_10m",
            "timezone": "UTC",
        }
        resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("hourly", {})
        times = data.get("time", [])
        if not times:
            return None

        # pick the hourly reading closest to `when`
        target_hour = when.strftime("%Y-%m-%dT%H:00")
        try:
            idx = times.index(target_hour)
        except ValueError:
            idx = min(range(len(times)), key=lambda i: abs(i - when.hour))

        speed = data["wind_speed_10m"][idx]
        direction = data["wind_direction_10m"][idx]
        if speed is None or direction is None:
            return None
        return WindReading(wind_speed_ms=speed / 3.6, wind_direction_deg=direction)  # km/h -> m/s

    def _fetch_era5(self, lat: float, lon: float, when: datetime) -> WindReading | None:
        """Requires the `cdsapi` package and a CDS API key (~/.cdsapirc or
        CDS_API_KEY). ERA5 downloads are NetCDF grib and asynchronous
        (queued server-side), so this is a documented integration point
        rather than a synchronous call — see requirements-advanced.txt and
        https://cds.climate.copernicus.eu/how-to-api for the request format.
        """
        logger.info("ERA5 backend selected — submit a CDS retrieval request for u10/v10 at %s,%s %s", lat, lon, when)
        raise NotImplementedError("Wire up cdsapi.Client().retrieve(...) here; see docstring")
