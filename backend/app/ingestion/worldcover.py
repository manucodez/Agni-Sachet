"""
ESA WorldCover (10m land-cover, public S3 bucket — no auth). Downloads the
tiles covering the configured bbox and exposes a sampler used in Step 2
(feature fusion) to look up the land-cover class under each hotspot.

WorldCover ships as 3x3-degree tiles named like ESA_WorldCover_10m_2021_v200_N30E060_Map.tif.
For a hackathon-scale India build, downloading the handful of tiles that
actually cover your bbox is far cheaper than mosaicking the whole country.
"""
import logging
import math
from pathlib import Path

import requests

from app.core.config import settings
from app.ingestion.base import IngestionAdapter

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/raw/worldcover")

# Class codes used downstream (app/ml/features.py) — see
# https://esa-worldcover.org/en/data-access for the full legend.
LAND_COVER_CLASSES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_ice",
    80: "permanent_water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"ESA_WorldCover_10m_2021_v200_{ns}{abs(lat):02d}{ew}{abs(lon):03d}_Map.tif"


class WorldCoverAdapter(IngestionAdapter):
    name = "worldcover"

    def fetch(self, **kwargs) -> list[Path]:
        w, s, e, n = settings.firms_bbox_tuple
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # WorldCover tiles are indexed on a 3-degree grid.
        lat_starts = range(int(math.floor(s / 3) * 3), int(math.ceil(n / 3) * 3), 3)
        lon_starts = range(int(math.floor(w / 3) * 3), int(math.ceil(e / 3) * 3), 3)

        downloaded = []
        for lat in lat_starts:
            for lon in lon_starts:
                tile = _tile_name(lat, lon)
                dest = DATA_DIR / tile
                if dest.exists():
                    downloaded.append(dest)
                    continue
                url = f"{settings.worldcover_s3_base}/v200/2021/map/{tile}"
                logger.info("Downloading WorldCover tile %s", tile)
                resp = requests.get(url, timeout=120, stream=True)
                if resp.status_code == 404:
                    logger.warning("No WorldCover tile at %s (likely ocean/out of coverage)", url)
                    continue
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                downloaded.append(dest)
        return downloaded

    def to_records(self, raw: list[Path]) -> list[dict]:
        # WorldCover is a raster sampled per-point in app/ml/features.py,
        # not a table of "records" to insert — this adapter's job ends at
        # having the right tiles on disk.
        return [{"tile_path": str(p)} for p in raw]


def sample_land_cover(lat: float, lon: float) -> int | None:
    """Point-sample the land-cover class at (lat, lon) from whichever
    downloaded tile covers it. Used by app/ml/features.py during fusion."""
    import rasterio

    lat_tile = int(math.floor(lat / 3) * 3)
    lon_tile = int(math.floor(lon / 3) * 3)
    tile_path = DATA_DIR / _tile_name(lat_tile, lon_tile)
    if not tile_path.exists():
        return None

    with rasterio.open(tile_path) as src:
        row, col = src.index(lon, lat)
        window = ((row, row + 1), (col, col + 1))
        value = src.read(1, window=window)
        return int(value[0, 0]) if value.size else None
