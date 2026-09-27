# Data sources

| Source | Used for | Access | Cost / limits |
|---|---|---|---|
| [NASA FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Thermal hotspot detections (VIIRS, MODIS) | Free `MAP_KEY` signup | 5,000 transactions/10min per key; NRT data, ~3hr latency |
| [OpenStreetMap Overpass API](https://overpass-api.de/) | Industrial land polygons, pipelines, transmission lines, rail, and (added in the best-practices merge — see docs/MERGE_NOTES.md) fire stations + hospitals for the nearest-responder feature | No key | Rate-limited under load — `.env.example` sets a fallback mirror |
| [ESA WorldCover](https://esa-worldcover.org/) | 10m land-cover classification | Public S3, no auth | Tiled; only the tiles covering your bbox are pulled |
| [WorldPop](https://www.worldpop.org/) | Population density (risk-score population term) | Public, no auth | ~100m resolution unconstrained mosaics |
| [WRI Global Power Plant Database](https://github.com/wri/global-power-plant-database) | Authoritative, named power plant locations with fuel type, kept as its own nearest-distance join distinct from generic OSM industrial land — see `app/models/hotspot.py` | Public CSV, no auth | Static snapshot; re-download periodically for updates |
| [DataMeet composite India boundary](https://github.com/datameet/maps) | Sovereign-boundary filter (`app/ingestion/india_boundary.py`) — excludes ocean/neighboring-country detections the FIRMS bbox lets through | Public GeoJSON, CC BY 4.0, no auth | Downloaded once, cached to `data/raw/india_boundary/`; ~a few MB |
| [VIIRS Nightfire (VNF)](https://payneinstitute.mines.edu/eog/nightfire/) | Gas-flare-vs-fire temperature discrimination (optional, for training labels) | **License-gated** — apply at the link above | Not a hard dependency — the pipeline runs without it; see `.env.example` |
| [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) | Sentinel-1 (SAR), Sentinel-2 (optical/GFM chips), Sentinel-5P/TROPOMI (chemistry) | Free account, OAuth2 client credentials | Generous free tier; async processing for some products |
| [Google Earth Engine](https://earthengine.google.com/) | Alternative backend for S1/S2/S5P (simpler auth) | Free for research/nonprofit use, service account | Synchronous `reduceRegion` calls used here |
| [Open-Meteo Historical API](https://open-meteo.com/) | Wind speed/direction for wind-transport graph edges | No key | Generous free tier |
| [ECMWF ERA5 (via CDS)](https://cds.climate.copernicus.eu/) | Reanalysis-grade wind (optional alternative to Open-Meteo) | Free CDS account | Requests are queued server-side, not synchronous |
| [Prithvi-EO-2.0 / Clay](https://huggingface.co/ibm-nasa-geospatial) | Frozen embeddings for open-set novelty detection | Open weights on Hugging Face | ~1.2GB download, cached locally after first run |
| [NDMA SACHET](https://sachet.ndma.gov.in/) | Reference schema for outbound alert payloads | N/A — this project targets the shape, not a live integration | — |

## Why VNF is optional, not required

VIIRS Nightfire is the most direct historical proxy for "was this
detection a gas flare" (temperature + persistence classification against
a global flare survey), which is genuinely useful for building training
labels. But its license approval can take longer than a hackathon week
allows, so nothing in the live pipeline blocks on it: `FirmsAdapter` and
the discovery/anomaly/classification steps run entirely on the open FIRMS
feed. If VNF access comes through, its historical flare survey is a strong
source of `gas_flare` training labels for `app/ml/train.py` — wire it in
as an additional labeling source, not a runtime dependency.

## Sovereign boundary filter

`FIRMS_BBOX` is a rectangle (the FIRMS Area API only accepts one), and a
rectangle drawn generously enough to cover the whole country necessarily
also covers ocean and slivers of Pakistan/Bangladesh/Nepal/China/Myanmar/
Sri Lanka. `app/ingestion/india_boundary.py` filters against the real
national boundary instead, using the DataMeet composite polygon linked
above. It fails open, not closed: if the polygon can't be downloaded (no
network, GitHub rate limit), ingestion proceeds with bbox-only filtering
and logs a loud warning rather than blocking the whole pipeline over one
optional layer — check the logs before trusting a "0 dropped" count in
that situation. Set `ENFORCE_INDIA_BOUNDARY=false` if you've deliberately
repointed this project at a different country/region.

## The agricultural-burn harvest calendar is a heuristic, not a citation

`app/ml/weak_labeling.py`'s `AGRICULTURAL_BURN_HARVEST_MONTHS` (Feb-May +
Oct-Nov) is a coarse, commonly-referenced approximation of Rabi and Kharif
post-harvest residue-burning windows for northern India, not a
peer-reviewed constant. It's a reasonable prior for bootstrapping training
labels at scale, not something to cite as fact in front of judges without
your own source — swap in a state-specific agricultural calendar if you
have one, and see `data/reference/verified_events.csv` for the harder
requirement (an independently checkable citation, not a heuristic) that
governs the verified-events evaluation harness.



Everything defaults to an India bounding box (`FIRMS_BBOX` in
`.env.example`: `68.0,6.5,97.5,37.5`). Every adapter that takes a bbox
argument reads this one setting — narrow it while developing (a state or
two) to keep Overpass/WorldCover pulls fast, then widen it back out for a
full run.
