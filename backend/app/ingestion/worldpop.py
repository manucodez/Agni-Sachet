"""
WorldPop population-density raster (public, no auth). Used to weight the
risk score (app/risk/scoring.py) by how many people live near a discovered
cluster — no census data-sharing agreement required since this is an
aggregate, non-personal raster.

https://www.worldpop.org/methods/populations/
"""
import logging
from pathlib import Path

import requests

from app.core.config import settings
from app.ingestion.base import IngestionAdapter

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/raw/worldpop")

# WorldPop's "unconstrained global mosaics" are per-country, ~100m resolution.
# For India specifically the ISO3 code is IND.
WORLDPOP_IND_URL_TEMPLATE = (
    "{base}/GIS/Population/Global_2000_2020_1km/2020/IND/ind_ppp_2020_1km_Aggregated.tif"
)


class WorldPopAdapter(IngestionAdapter):
    name = "worldpop"

    def fetch(self, **kwargs) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = DATA_DIR / "ind_ppp_2020_1km_Aggregated.tif"
        if dest.exists():
            return dest

        url = WORLDPOP_IND_URL_TEMPLATE.format(base=settings.worldpop_base_url)
        logger.info("Downloading WorldPop raster: %s", url)
        resp = requests.get(url, timeout=300, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return dest

    def to_records(self, raw: Path) -> list[dict]:
        return [{"raster_path": str(raw)}]


def sample_population_density(lat: float, lon: float) -> float | None:
    """Point-sample population density near (lat, lon). Used during
    feature fusion (Step 2) and again in risk scoring (Step 8)."""
    import rasterio

    tile_path = DATA_DIR / "ind_ppp_2020_1km_Aggregated.tif"
    if not tile_path.exists():
        return None

    with rasterio.open(tile_path) as src:
        row, col = src.index(lon, lat)
        window = ((row, row + 1), (col, col + 1))
        value = src.read(1, window=window)
        return float(value[0, 0]) if value.size and value[0, 0] >= 0 else None
