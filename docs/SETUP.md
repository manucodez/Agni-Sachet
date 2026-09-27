# Setup — from an empty machine to a running dashboard

This is the exhaustive version. For the short path, see the Quickstart in
the root [README.md](../README.md).

## 0. Prerequisites

Install these first:

- **Docker Desktop** (or Docker Engine + Compose v2 on Linux) — everything
  runs in containers, so you do NOT need Python or Node installed on the
  host unless you want to run things outside Docker (Section 8 covers that
  path too).
- **Git**
- A GitHub account, if you're pushing this up (see Section 9).

Verify:

```bash
docker --version         # 24.x or newer recommended
docker compose version   # v2.x — note: "docker compose", not "docker-compose"
git --version
```

## 1. Clone / initialize the repo

If you received this as a zip, unzip it and `cd` in, then initialize git
yourself (Section 9 has the exact commands). If you're continuing from an
existing repo, just `git clone` it and `cd` in as normal.

```bash
cd agni-sachet
```

## 2. Get your API keys

You need exactly **one** key to get the core system running. Everything
else is optional and the system degrades gracefully without it.

### Required: NASA FIRMS MAP_KEY

1. Go to <https://firms.modaps.eosdis.nasa.gov/api/map_key/>
2. Fill in your email — the key is emailed to you within a few minutes,
   no approval wait.
3. Copy the key.

### Optional but recommended: nothing else needed for OSM/WorldCover/WorldPop/WRI

These four sources need no signup at all — they're public with no auth.

### Optional (Phase 3 / advanced channels only)

Skip these entirely for the core MVP. Only needed if you're building the
chemistry/SAR/novelty channels:

- **Copernicus Data Space Ecosystem** (TROPOMI + Sentinel-1/2): register
  free at <https://dataspace.copernicus.eu/>, then create an OAuth2 client
  under your account settings to get a client ID/secret.
- **Google Earth Engine** (alternative backend for the same data):
  <https://earthengine.google.com/> → sign up → create a service account
  under a Google Cloud project → download its JSON key.
- **Hugging Face token**: only needed if `ibm-nasa-geospatial/Prithvi-EO-2.0-300M`
  is gated for your account when you try to download it — most GFM repos
  are open. Get one at <https://huggingface.co/settings/tokens> if needed.
- **VIIRS Nightfire**: apply at
  <https://payneinstitute.mines.edu/eog/nightfire/> — this can take a
  while to be approved; the system runs fine without it (see
  [DATA_SOURCES.md](./DATA_SOURCES.md)).

## 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```
FIRMS_MAP_KEY=<the key from step 2>
```

Everything else has a working default for local development. Leave the
Phase 3 keys blank if you're not using them — the code checks for them and
skips those channels cleanly (logs a warning, doesn't crash).

## 4. Start the stack

```bash
make up
```

This runs `docker compose up --build`, which:

1. Starts a PostGIS container (`postgis/postgis:16-3.4`) and waits for it
   to report healthy.
2. Builds the backend image (installs GDAL/GEOS/PROJ system libraries plus
   everything in `backend/requirements.txt`) and starts FastAPI with
   `--reload` on port `8000`.
3. Builds the frontend image, runs `npm install`, and starts Next.js dev
   server on port `3000`.

First build takes a few minutes (GDAL compilation + npm install). Leave
this running in its own terminal; open a second terminal for the next
steps.

**Verify it's up:**

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Open <http://localhost:3000> — you should see a dark map with no markers
yet (that's expected, you haven't loaded data).

## 5. Run database migrations

```bash
make migrate
```

This runs `alembic upgrade head` inside the backend container, creating
every table (`hotspots`, `discovered_clusters`, `cluster_edges`,
`anomaly_flags`, `alerts`) plus the PostGIS extension and spatial indexes.
The initial migration is already committed in the repo (it has a couple of
hand-fixed PostGIS/GeoAlchemy2 quirks documented in its own docstring —
see [ARCHITECTURE.md](./ARCHITECTURE.md) if you're curious), so this is a
single command on a fresh checkout.

**If you change a model later** and need a new migration:

```bash
make revision m="describe your change"
make migrate
```

Alembic's autogenerate has two known rough edges worth knowing about
before you trust a freshly generated migration — both are already handled
for the initial one, but will resurface on new geometry columns or new
PostGIS-adjacent tables:
1. It will try to `DROP TABLE spatial_ref_sys` (PostGIS's own internal
   table) unless `migrations/env.py`'s `include_object` filter catches it
   — already in place, just don't remove it.
2. It emits an explicit `create_index(...)` for any new Geometry column's
   GiST index, which GeoAlchemy2 *also* creates automatically via its own
   DDL event — running both fails with "relation already exists". Strip
   the redundant explicit `create_index`/`drop_index` calls for any new
   geometry column the same way the initial migration's file shows.

## 6. See something on the map immediately: seed demo data

```bash
make seed
```

This inserts three illustrative clusters (a flare, an industrial-fire
scenario, a mining site) so the dashboard has something to show right
away. Refresh <http://localhost:3000> — you should now see three
color-coded markers on the map. Click one to open the detail panel.

**This is placeholder data, not a live detection** — swap it out before
a judged demo (see [ARCHITECTURE.md](./ARCHITECTURE.md)'s note on using
one real, documented incident rather than a synthetic example).

## 7. Run the real pipeline against live data

```bash
make ingest     # pulls FIRMS + OSM + WorldCover + WorldPop + WRI, fuses, stores
make pipeline   # discovery hasn't run yet — see below, run this AFTER discovery
```

Actually, run them in this order the first time:

```bash
make ingest                                            # Steps 1-2
docker compose exec backend python -m app.jobs.run_discovery   # Step 3
```

Before `make pipeline` will do anything useful, you need a trained
classifier — see Section 7a. Without one, the pipeline still runs
(anomaly detection, graph, risk scoring all work), it just leaves
`predicted_class` as `unclassified` for everything.

### 7a. Train the classifier

You need a labeled CSV first — `backend/app/ml/train.py`'s docstring and
`app/ml/features.py`'s `FEATURE_COLUMNS` define the exact shape it expects
(one row per labeled historical detection, with `label` being one of the
6 known classes plus `lat`/`lon`/`acq_datetime`). Building this labeled
set is genuinely the most labor-intensive part of the whole project —
see [ARCHITECTURE.md](./ARCHITECTURE.md) and [DATA_SOURCES.md](./DATA_SOURCES.md)
for where labels can come from (VNF's historical flare survey for
`gas_flare`, FSI/state forest department data for `wildfire`, WRI/OSM
proximity + manual spot-checks for `industrial_fire`/`mining`).

The fastest way to get a first labeled CSV — after `make ingest` has
populated the `hotspots` table — is the deterministic weak-labeling rule:

```bash
make weak-labels   # writes data/processed/labeled_clusters.csv
```

This is a starting point, not ground truth — see
[ROADMAP.md, "Label sourcing"](./ROADMAP.md#label-sourcing-the-actual-bottleneck)
for what it does and doesn't solve, and run `make circularity-audit` and
`make evaluate-verified` before trusting any accuracy number it produces.

```bash
docker compose exec backend python -m app.ml.train --labels data/processed/labeled_clusters.csv
```

Read the console output carefully — it prints BOTH the spatial-block
holdout F1 (the honest number) and the random-split F1 (for contrast).
Report the spatial-block one. See
[ARCHITECTURE.md](./ARCHITECTURE.md#validation-methodology-read-before-reporting-any-accuracy-number).

Then:

```bash
make pipeline
```

### 7b. Configure incident escalation (optional, off by default)

`ALERT_DISPATCH_ENABLED=false` in `.env.example` means incidents are
still created, tiered and logged exactly as normal, but no email actually
sends — safe defaults for a demo or CI run. To wire up real tier
notifications: set `SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_FROM_ADDRESS`
(a Gmail [app password](https://myaccount.google.com/apppasswords) is the
fastest path), fill in at least `INCIDENT_TIER0_EMAILS`, set
`PUBLIC_BASE_URL` to wherever the backend is actually reachable from
(so the click-to-acknowledge link in the email works), and only then flip
`ALERT_DISPATCH_ENABLED=true`. See `app/alerts/email_channel.py`'s module
docstring for the safety reasoning behind that ordering.

## 8. Running outside Docker (optional)

If you'd rather run the backend directly on your host (e.g. for faster
iteration with a debugger attached):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# You'll also need GDAL/GEOS/PROJ system libraries installed natively —
# on macOS: brew install gdal geos proj
# on Ubuntu/Debian: apt install gdal-bin libgdal-dev libgeos-dev libproj-dev
export $(cat ../.env | grep -v '^#' | xargs)   # or use a tool like direnv
uvicorn app.main:app --reload
```

For the frontend:

```bash
cd frontend
npm install
npm run dev
```

You'll still need a PostGIS instance reachable — either keep using the
Dockerized one (`docker compose up postgis`) or point `POSTGRES_HOST` in
`.env` at your own.

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `FIRMS_MAP_KEY is not set` error | `.env` not filled in, or not picked up | Confirm `.env` exists (not just `.env.example`) and `docker compose` was restarted after editing it |
| Overpass query times out / 429s | Public Overpass instance overloaded | `.env`'s `OVERPASS_API_URL_FALLBACK` is tried automatically; narrow `FIRMS_BBOX` while developing to speed up queries |
| `postgis` container unhealthy / backend can't connect | First boot still initializing | `docker compose logs postgis` — wait for "database system is ready to accept connections"; `make up` already waits on the healthcheck, so this usually resolves itself in under a minute |
| Map loads but shows no markers | No data ingested/seeded yet | Run `make seed` for a quick check, or `make ingest` + discovery for real data |
| `No trained model` warning in pipeline logs | Haven't run `app/ml/train.py` yet | Expected until you have a labeled dataset — the rest of the pipeline still runs, everything just reports `unclassified` |
| WorldCover/WorldPop downloads fail | Bbox spans tiles/countries not covered, or a transient S3 issue | Check the specific tile name in the error against <https://esa-worldcover.org/en/data-access>; these downloads are retried on the next `make ingest` run, not required for the pipeline to proceed |
| `npm install` slow or fails in the frontend container | Cold npm cache on first build | Re-run `make up --build`; subsequent builds are cached |
