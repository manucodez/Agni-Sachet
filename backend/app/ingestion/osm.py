"""
Overpass API adapter — pulls industrial land polygons, the linear
infrastructure (pipelines, transmission lines, rail) used to build the
physical-edge graph in app/graph/build_graph.py, and — as of the
best-practices merge described in docs/MERGE_NOTES.md — the nearest
emergency-responder layer (fire stations + hospitals) used to make an
alert actionable ("nearest fire station: 4.2 km") rather than just a
coordinate on a map.

No API key needed. Overpass instances rate-limit aggressively under load,
so this adapter retries against a fallback mirror before giving up.
"""
import logging

import requests

from app.core.config import settings
from app.ingestion.base import IngestionAdapter

logger = logging.getLogger(__name__)

# India bounding box by default; swap for a smaller bbox while developing —
# a full-country Overpass query can take a couple of minutes.
#
# fire_station / hospital are queried as both `way` and `node` because OSM
# mappers tag small facilities as a single point and larger campuses as a
# footprint polygon — restricting to one form silently loses the other.
OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:180];
(
  way["landuse"="industrial"]({bbox});
  way["power"="plant"]({bbox});
  way["man_made"="pipeline"]({bbox});
  way["power"="line"]({bbox});
  way["power"="minor_line"]({bbox});
  way["railway"="rail"]({bbox});
  node["industrial"]({bbox});
  way["amenity"="fire_station"]({bbox});
  node["amenity"="fire_station"]({bbox});
  way["amenity"="hospital"]({bbox});
  node["amenity"="hospital"]({bbox});
);
out body geom;
"""


def _extract_coords(el: dict) -> list[list[float]] | None:
    """Returns [[lon, lat], ...] for one Overpass element, or None if it
    carries no usable geometry.

    Overpass's `out geom` modifier attaches a `geometry` array to WAYS and
    RELATIONS (so a polygon's outline can be drawn), but a NODE is already
    a single point and is returned with top-level `lat`/`lon` fields
    instead — it never gets a `geometry` array, with or without `out geom`.

    The previous version of this function read `el.get("geometry")`
    unconditionally and skipped the element when that was empty. That's
    correct for ways, but silently dropped every `node[...]` match in the
    query above — which is a lot of OSM fire stations and hospitals, since
    small facilities are typically mapped as a single point rather than a
    building outline. This was invisible for the original industrial/
    pipeline query because `landuse=industrial` and pipeline/transmission/
    rail tags are overwhelmingly mapped as ways in India; `node["industrial"]`
    results were being silently dropped too, just less consequentially.
    Handling both element types explicitly fixes both.
    """
    if el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
        return [[lon, lat]] if lat is not None and lon is not None else None

    geometry = el.get("geometry")
    if not geometry:
        return None
    return [[pt["lon"], pt["lat"]] for pt in geometry]


class OsmAdapter(IngestionAdapter):
    name = "osm"

    def fetch(self, **kwargs) -> dict:
        # Overpass wants (south,west,north,east) — different order than FIRMS.
        w, s, e, n = settings.firms_bbox_tuple
        bbox = f"{s},{w},{n},{e}"
        query = OVERPASS_QUERY_TEMPLATE.format(bbox=bbox)

        for url in (settings.overpass_api_url, settings.overpass_api_url_fallback):
            try:
                logger.info("Querying Overpass at %s", url)
                resp = requests.post(url, data={"data": query}, timeout=200)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                logger.warning("Overpass endpoint %s failed: %s", url, exc)
        raise RuntimeError("Both Overpass endpoints failed — see logs above")

    def to_records(self, raw: dict) -> list[dict]:
        """Splits elements into polygons (industrial land / plants), lines
        (pipeline / transmission / rail), and responders (fire stations /
        hospitals) since they feed different downstream steps (nearest-
        distance join, graph edges, and the incident-response nearest-
        responder lookup in app/jobs/run_ingestion.py, respectively).

        All three categories are returned in one flat list — same
        contract as before — distinguished by the `category` field;
        callers filter with a list comprehension rather than this
        function returning three separate lists.
        """
        polygons, lines, responders = [], [], []

        for el in raw.get("elements", []):
            tags = el.get("tags", {})
            coords = _extract_coords(el)
            if not coords:
                continue

            record = {
                "osm_id": el["id"],
                "osm_type": el["type"],
                "tags": tags,
                "coordinates": coords,
            }

            if tags.get("landuse") == "industrial" or tags.get("power") == "plant" or "industrial" in tags:
                record["category"] = "industrial_polygon"
                polygons.append(record)
            elif tags.get("man_made") == "pipeline":
                record["category"] = "pipeline"
                lines.append(record)
            elif tags.get("power") in ("line", "minor_line"):
                record["category"] = "transmission"
                lines.append(record)
            elif tags.get("railway") == "rail":
                record["category"] = "rail"
                lines.append(record)
            elif tags.get("amenity") == "fire_station":
                record["category"] = "responder_fire_station"
                record["name"] = tags.get("name")
                responders.append(record)
            elif tags.get("amenity") == "hospital":
                record["category"] = "responder_hospital"
                record["name"] = tags.get("name")
                responders.append(record)

        logger.info(
            "OSM: %d industrial polygons, %d infrastructure lines, %d responders (%d fire stations, %d hospitals)",
            len(polygons), len(lines), len(responders),
            sum(1 for r in responders if r["category"] == "responder_fire_station"),
            sum(1 for r in responders if r["category"] == "responder_hospital"),
        )
        return polygons + lines + responders
