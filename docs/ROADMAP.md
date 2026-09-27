# Roadmap — from scratch to advanced

This maps the architecture in [ARCHITECTURE.md](./ARCHITECTURE.md) onto a
buildable sequence. Days 0-6 are the core MVP — fully functional, directly
answers both PS deliverables, demoable on its own. The Advanced section is
Phase 3 (chemistry / SAR / wind edges / GFM novelty) — genuinely novel,
genuinely optional, and explicitly not required for the core system to
work. The Stretch section is honest about what's designed but not
implemented.

Role labels below are generic (six roles is a common hackathon team size)
— map them onto your actual team however makes sense; nothing here assumes
specific names or a fixed assignment.

## Day 0 — Setup

- Everyone: clone the repo, follow [SETUP.md](./SETUP.md) Sections 0-4
  (Docker up, `/health` returns ok).
- Data/Graph engineer: get the FIRMS `MAP_KEY` (instant), confirm Overpass
  queries return data for a small test bbox, download one WorldCover tile
  and one WorldPop raster manually to confirm URLs/paths are right for
  your actual bbox.
- Backend engineer: `make revision m="initial schema"` + `make migrate`,
  confirm all 5 tables exist (`\dt` in `make db-shell`).
- ML scientist: start sourcing labels in parallel from day 0 — this is the
  longest lead-time item in the whole build (see "Label sourcing" below).
- Frontend engineer: `npm run dev` locally works, dark theme renders,
  Leaflet base map loads.
- QA/Validation lead: read [ARCHITECTURE.md](./ARCHITECTURE.md)'s
  validation-methodology section now, not on day 5 — it changes how labels
  should be collected (spread across many sites, not just a few well-known
  ones) from the start.

## Day 1 — Ingestion live

- Data engineer: `FirmsAdapter`, `OsmAdapter`, `WorldCoverAdapter`,
  `WorldPopAdapter`, `PowerPlantsAdapter` all return real data for your
  bbox; `make ingest` populates the `hotspots` table end to end.
- Backend engineer: confirm `/hotspots` and `/hotspots/geojson` return
  real rows.
- Frontend engineer: wire the map to `/hotspots/geojson` temporarily
  (before clusters exist) just to see real points rendering.

## Day 2 — Discovery + anomaly detection

- ML scientist: `run_discovery` produces sensible clusters on your real
  ingested history (tune `min_cluster_size`/`cluster_selection_epsilon_km`
  against what you're actually seeing — defaults are a starting point).
- ML scientist: `detect_changepoints` + the decay-curve trend classifier
  run cleanly per cluster/sensor; sanity-check a few flagged spikes by eye
  against the raw FRP series.

## Day 3 — Classification

- ML scientist + QA lead: finalize the labeled dataset (see "Label
  sourcing"), run `scripts/validate_spatial_leakage.py` against it BEFORE
  training — fix thin-coverage classes now, not after judging.
- ML scientist: `app/ml/train.py` — report the spatial-block F1, not the
  random-split one. Iterate on features/hyperparameters against that
  number.
- Backend engineer: `app/jobs/run_pipeline.py`'s classification step runs
  against the trained model; `discovered_clusters.predicted_class`
  populates.

## Day 4 — Graph + risk scoring

- Data/Graph engineer: `build_physical_graph` connects real clusters via
  real OSM/WRI infrastructure for at least one genuine corridor — this is
  your strongest demo moment for "why does a graph matter," so make sure
  at least one real example exists, not just a synthetic one.
- Backend engineer: `compute_risk_score` wired into the pipeline;
  `risk_tier` populates and looks sane against a few manually-reasoned
  examples.

## Day 5 — API + frontend polish

- Backend engineer: `/clusters/geojson`, `/clusters/{id}`,
  `/clusters/{id}/history`, `/clusters/{id}/connections`, `/alerts` all
  exercised against real data.
- Frontend engineer: switch the map to `/clusters/geojson`, wire the
  detail panel, filter bar, alert feed to the real endpoints; confirm
  physical-edge polylines render for the Day 4 corridor example.

## Day 6 — Alerts, validation pass, honesty pass

- Backend engineer: confirm L2/L3 clusters produce a SACHET-shaped payload
  (`app/alerts/sachet.py`) and show up in the `/alerts` feed.
- QA/Validation lead: full pass against
  [ARCHITECTURE.md](./ARCHITECTURE.md)'s validation checklist; write down
  the actual spatial-block F1 and the gap vs. random-split — this
  transparency is itself a strong point in front of judges.
- Everyone: pick ONE real, documented Indian incident with public news
  coverage and build a specific, rehearsed demo path around it (see
  [ARCHITECTURE.md](./ARCHITECTURE.md), "Being honest about what's a
  7-day build") rather than claiming national live coverage.

## Day 7 — Demo rehearsal

- Record a fallback video of the full demo path in case live network/API
  access is flaky on presentation day.
- Prepare answers for the obvious judge questions: why NTRO cares (IMINT /
  critical-infrastructure mandate, not just generic disaster response),
  why detection is intent-agnostic by design, what's core vs. advanced and
  why (this roadmap's own split is the honest answer), and what the
  spatial-block F1 actually means vs. a naive number.

---

## Advanced (Phase 3) — build in parallel once core dataflow is stable

None of this blocks Days 0-6. Whoever frees up first (or a 7th
contributor, if you have one) can start here once `run_pipeline.py`'s core
loop is working end to end.

- **Wind-transport graph edges** (`app/graph/wind_edges.py`) — the
  cheapest of the four Phase 3 additions: no training, no heavy
  dependencies, just geometry + a free wind API. Genuinely buildable in a
  day. Do this one first if you only have time for one Phase 3 item.
- **Chemical fingerprint channel** (`app/ingestion/tropomi.py`) — needs a
  free Copernicus Data Space or Earth Engine account (Section 2 of
  SETUP.md); the CDSE Statistical API / GEE `reduceRegion` calls are
  synchronous, so this is a same-day integration once the account exists.
  Calibrating the crude SO2-threshold "anomalousness" proxy in
  `run_pipeline.py::_run_advanced_channels` into something better-founded
  is a good use of remaining time if you have it.
- **SAR structural confirmation** (`app/ingestion/sentinel1.py`) — the GEE
  amplitude-proxy path is same-day buildable; the HyP3 full-InSAR-coherence
  path is async (submit a job, poll, download) and realistically a
  post-hackathon upgrade — the module's docstring says so explicitly.
- **GFM visual novelty** (`app/ml/novelty.py`) — needs `torch` +
  `transformers` (`requirements-advanced.txt`) and a Sentinel-2 chip
  downloader wired in (left as a documented gap in `run_pipeline.py` since
  the chip size/bands depend on which GFM variant you pick). Building
  `build_class_centroids` from your labeled dataset is cheap once chip
  download exists; do this one last if time is short, since it depends on
  having the labeled dataset from Day 3 anyway.

## Stretch — designed, not implemented, and here's why

- **Cascade-prediction GNN** (`app/graph/cascade_gnn.py`) — deliberately
  left as a documented, honest stub. Power-grid cascading-failure GNN
  research trains on simulated outage data because the physics are known;
  there's no equivalent simulator for a satellite thermal-event graph.
  Doing this properly means generating your own synthetic percolation
  runs over the real graph first — see the module docstring for the
  recommended sequence. Shipping an unvalidated GNN in place of the
  working centrality heuristic would be worse than not having one; say so
  to judges rather than rushing it.
- **Conformal-prediction confidence wrapper** — a genuinely nice add-on
  (calibrated confidence intervals on classifier output instead of a raw
  softmax probability) but adds a full extra validation step; reasonable
  to scope out of a first build.
- **OSM infrastructure lines in PostGIS instead of in-memory** —
  `build_physical_graph` currently takes `infra_lines` as an in-memory
  list; moving OSM line geometries into their own PostGIS table with a
  proper `ST_DWithin` query would be both faster and let the frontend
  render infrastructure lines directly instead of only inferring them from
  cluster-to-cluster edges.

(Stable cluster identity across discovery re-runs used to be listed here
as designed-not-implemented. It isn't anymore — `app/jobs/run_discovery.py`
already matches newly-clustered groups against existing `DiscoveredCluster`
rows by centroid proximity before assigning IDs, specifically so
`cluster_id` stays stable across re-runs. This was caught as a stale doc
during the best-practices merge — see docs/MERGE_NOTES.md — the code was
already right, the roadmap just hadn't been updated to say so.)

## Label sourcing (the actual bottleneck)

Realistically the single longest-lead-time task in this whole build —
start it Day 0, not Day 3.

**Fastest path to a spatially-diverse training set:** `make weak-labels`
(`scripts/generate_weak_labels.py`) applies a documented, versioned rule
(`app/ml/weak_labeling.py`) to whatever's already in the `hotspots` table
— distance to industrial land / power plants, land-cover class, month,
recurrence — and writes a ready-to-train `labels.csv` in seconds. This
gets `scripts/validate_spatial_leakage.py` enough spatially-diverse rows
to actually mean something, which "manually spot-label a few dozen sites"
alone struggles to do in a 7-day build.

**It is not a substitute for the per-class judgment below** — it's a
starting point, and a model trained only on it will partly just be
learning to recite the rule back. Before trusting any accuracy number:

1. Run `make circularity-audit` (`scripts/circularity_audit.py`). It
   retrains with exactly the features the rule used to assign labels
   removed, and reports how much of the "headline" score survives without
   them. A large drop means most of your accuracy is the model re-deriving
   distance/land-cover/month facts it was already handed — expected, and
   worth reporting honestly rather than the headline number alone.
2. Run `make evaluate-verified` (`scripts/evaluate_verified_labels.py`)
   against `data/reference/verified_events.csv` — a small, independently
   cited set of real incidents (Wikipedia/NASA/company sources, not this
   rule's output). It currently covers `industrial_fire`, `mining` and
   `wildfire` with real dates/coordinates; `gas_flare` and
   `agricultural_burn` are still open — adding a cited event for each is
   real, valuable work, not busywork (see that file's own notes on why a
   guessed date/location isn't good enough). Note the historical-backfill
   caveat in that script's docstring: it only matches against detections
   already in your DB, and FIRMS' near-real-time feed doesn't reach back
   to 2009/2019/2021 — you'll need FIRMS' separate archive-download API
   for that, which isn't wired up yet.

**Per-class notes (unchanged by the above — still the right judgment
calls):**

- `gas_flare` — the weak-labeling rule uses proximity + recurrence as a
  proxy; VNF's historical flare survey, if your license comes through in
  time, is real ground truth and should win over the rule wherever the two
  disagree.
- `wildfire` — state forest department / FSI public incident reports, or
  a public wildfire-labeled benchmark dataset if you find one covering
  India.
- `industrial_fire` — genuinely the hardest class to source, because
  (thankfully) real industrial accidents are rare. A small number of
  well-documented historical incidents (news-verified date + location) is
  more honest than a large weakly-labeled set — and is exactly why the
  Phase 3 GFM novelty channel exists as a complementary, label-light
  safety net for this specific class.
- `mining`, `agricultural_burn`, `other` — land-cover class (WorldCover)
  + OSM tags + manual spot-checks are usually enough to bootstrap
  reasonable label sets for these three; the weak-labeling rule's mining
  heuristic (bare/sparse-vegetation land cover) is coarse and will also
  catch quarries and brick kilns — treat those labels as lower-confidence
  than the others.

Whatever you end up with, run `scripts/validate_spatial_leakage.py`
against it before trusting any accuracy number from `app/ml/train.py`.
