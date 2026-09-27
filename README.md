# Agni Sachet

AI-based classification and monitoring of industrial fires and persistent
thermal sources — built for SIH 2026, Problem Statement 26162 (NTRO).

NASA FIRMS tells you a pixel got hot. It doesn't tell you whether that was
a refinery flare, a mining burn, an agricultural fire, a wildfire, or an
actual accident. This system fuses FIRMS thermal detections with OSM
infrastructure data, land-cover, population, and (optionally) atmospheric
chemistry and SAR structural data to answer that question — then stores
and visualizes the result as a GIS map overlay.

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the full design
and the reasoning behind it, [docs/ROADMAP.md](./docs/ROADMAP.md) for the
phased build plan, [docs/DATA_SOURCES.md](./docs/DATA_SOURCES.md) for
every data source used and how to get access, and
[docs/MERGE_NOTES.md](./docs/MERGE_NOTES.md) for a from-scratch analysis
of two other SIH26162 reference implementations and exactly what was
ported into this codebase from each, and why.

## What's actually here

**Core (fully working without any advanced setup):**
- FIRMS + OSM + ESA WorldCover + WorldPop + WRI Power Plant Database
  ingestion, fused into one table
- Sovereign-boundary filtering (a real India polygon, not just the FIRMS
  bounding box) and a nearest-emergency-responder (fire station/hospital)
  layer
- HDBSCAN discovery of persistent thermal sources
- Per-cluster changepoint (spike/silence) anomaly detection with a
  decay-curve FRP trend feature
- A physical-infrastructure correlation graph (pipeline/transmission/rail)
- XGBoost + SHAP classification into 6 classes plus a confidence-gated
  "unclassified" bucket, followed by a small set of deterministic serving
  guards for the cases a trained model can't be relied on to get right on
  its own (non-combustion facilities, low-confidence forest/cropland
  ambiguity) — see `app/ml/serving_guards.py`
- A documented, versioned weak-labeling rule, a circularity audit, and a
  small independently-cited verified-events register, for actually
  knowing whether the classifier's reported accuracy means anything — see
  `app/ml/weak_labeling.py`, `scripts/circularity_audit.py`
- A documented, transparent 0-100 risk score with L0-L3 tiers
- PostGIS storage, FastAPI + GeoJSON endpoints, a Next.js + Leaflet map
- SACHET-shaped outbound alerts, plus a stateful, acknowledgeable 3-tier
  incident escalation workflow (email, click-to-acknowledge) for anything
  that crosses L2/L3 — see `app/alerts/incident_dispatch.py`. Dispatch is
  OFF by default (`ALERT_DISPATCH_ENABLED=false`) until you deliberately
  configure real recipients.

**Advanced / Phase 3 (optional, each independently toggleable):**
- Atmospheric chemistry fingerprint (TROPOMI SO2/NO2/CO/aerosol) for
  flagged clusters
- SAR structural-change confirmation (Sentinel-1) for high-severity
  candidates
- Wind-transport graph edges — a second, independent hazard-propagation
  pathway alongside physical infrastructure
- Open-set visual novelty detection via a frozen geospatial foundation
  model (Prithvi-EO-2.0 / Clay), targeting the rare-accident-class problem
  without needing more labeled accident data

**Stretch (designed, not implemented — and the docs say exactly why):**
a cascade-prediction GNN, a conformal-prediction confidence wrapper. See
[docs/ROADMAP.md](./docs/ROADMAP.md#stretch--designed-not-implemented-and-heres-why).

## Quickstart

```bash
cp .env.example .env
# edit .env: set FIRMS_MAP_KEY (free, instant — see docs/SETUP.md Section 2)

make up            # starts PostGIS + backend + frontend
make migrate        # creates the schema
make seed           # loads 3 demo clusters so the map isn't empty
```

Open <http://localhost:3000>. API docs (FastAPI's auto-generated Swagger
UI) are at <http://localhost:8000/docs>.

For real data instead of the demo seed:

```bash
make ingest                                                   # pull + fuse real detections
docker compose exec backend python -m app.jobs.run_discovery   # find persistent sites
make pipeline                                                  # anomaly + classify + score + alert
```

Full walkthrough, every command explained, troubleshooting table:
**[docs/SETUP.md](./docs/SETUP.md)**.

## Project structure

```
agni-sachet/
├── backend/
│   ├── app/
│   │   ├── core/          # config, DB engine/session
│   │   ├── models/        # SQLAlchemy + GeoAlchemy2 ORM models
│   │   ├── schemas/       # Pydantic API response shapes
│   │   ├── api/routes/    # FastAPI routers (hotspots, clusters, alerts, incidents, health)
│   │   ├── ingestion/     # one adapter per data source (base.py defines the interface), + india_boundary.py
│   │   ├── ml/            # feature engineering, discovery, anomaly, classifier, training, novelty, serving_guards, weak_labeling
│   │   ├── graph/         # physical + wind-transport correlation graph, cascade GNN stub
│   │   ├── risk/          # 0-100 score + L0-L3 tiering
│   │   ├── alerts/        # SACHET-shaped payload builder + tiered incident escalation (incident_dispatch.py, email_channel.py)
│   │   └── jobs/          # orchestration entrypoints (run_ingestion, run_discovery, run_pipeline)
│   ├── migrations/        # Alembic
│   ├── tests/
│   ├── data/reference/    # verified_events.csv — small, cited, hand-curated (not gitignored, unlike data/raw|processed)
│   ├── scripts/           # seed_demo_data.py, validate_spatial_leakage.py, generate_weak_labels.py, circularity_audit.py, evaluate_verified_labels.py
│   ├── requirements.txt
│   ├── requirements-advanced.txt   # torch/transformers/earthengine — Phase 3 only
│   └── Dockerfile
├── frontend/
│   ├── app/                # Next.js App Router pages
│   ├── components/         # MapView, FilterBar, ClusterDetailPanel, AlertFeed
│   ├── lib/api.ts           # typed API client
│   └── types/index.ts       # mirrors backend Pydantic schemas
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_SOURCES.md
│   ├── SETUP.md
│   └── ROADMAP.md
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Everyday commands

Run `make help`-style by just reading the [Makefile](./Makefile) — every
target has a one-line comment. The ones you'll use most:

```bash
make up             # start everything
make down            # stop everything
make logs             # tail all container logs
make backend-shell     # shell into the backend container
make db-shell            # psql into PostGIS
make test                 # run the backend test suite
make lint / make fmt       # ruff check / ruff format
```

## Pushing this to your own GitHub

```bash
git init -b main
git add .
git commit -m "Initial Agni Sachet scaffold"

# Create the repo on GitHub first (web UI, or: gh repo create agni-sachet --private --source=. --remote=origin)
git remote add origin https://github.com/<your-username>/agni-sachet.git
git push -u origin main
```

If you're on a team, protect `main` and work in feature branches
(`git checkout -b feat/discovery-tuning`), opening PRs back into `main` —
`.github/workflows/ci.yml` runs lint + tests on every push and PR.

## License

MIT — see [LICENSE](./LICENSE).
