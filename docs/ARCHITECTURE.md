# Architecture

Agni Sachet turns raw satellite thermal detections into classified,
risk-scored, monitored "persistent thermal sources" — directly answering
the problem statement's two deliverables:

- **(i) Classification and segregation** of industrial fires from forest
  fires and other natural fires → Steps 1-3, 7 below.
- **(ii) GIS-based storage and map-overlay visualization** → Steps 9-11
  below (PostGIS + FastAPI + Next.js/Leaflet).

Everything from Step 2.5 onward that's marked **PHASE 3 / ADVANCED** is an
optional enrichment layer — the system is fully functional and demoable
without it. See [ROADMAP.md](./ROADMAP.md) for what's core vs. stretch and
why.

## Why this design, not just "NASA FIRMS + a classifier"

NASA FIRMS gives you a point, a temperature, and a confidence level — it
was never built to tell a refinery flare from a wildfire from a mining
burn, because that's not what it's for. Three things make this system more
than a thin wrapper around FIRMS + XGBoost:

1. **Context beats instantaneous radiometry.** A July 2026 leakage study on
   FIRMS-based wildfire classifiers found that a smoldering wildfire edge
   and an agricultural burn can present near-identical FRP and brightness
   temperature — flares are engineered to burn at wildfire-like
   intensities. What actually discriminates an event is temporal
   persistence, spatial density, and growth pattern, not the raw thermal
   reading. That's why Steps 3-6 (discovery, decay-curve trend, changepoint
   detection, graph correlation) exist before classification ever runs —
   the classifier consumes *context* features, not raw FRP.

2. **A found site isn't classified in isolation.** Two clusters connected
   by a shared pipeline, or one that's downwind of the other, change how
   an anomaly at either one should be read. See "The correlation graph"
   below.

3. **Evidence should be corroborated across independent physical
   channels, not just modeled harder on the same one.** Phase 3 adds
   atmospheric chemistry, SAR structural confirmation, and open-set visual
   novelty — three modalities that answer genuinely different questions
   than "how hot is this pixel."

## The pipeline, step by step

| # | Step | Module | Output |
|---|------|--------|--------|
| 1 | Pull FIRMS, OSM (+ responders), WorldCover, WorldPop, WRI power plants | `app/ingestion/*.py` | raw records |
| 1.5 | Sovereign-boundary filter — drop detections outside India (fails open, see docs/DATA_SOURCES.md) | `app/ingestion/india_boundary.py` | filtered raw records |
| 2 | Fuse: nearest-industrial / nearest-power-plant / nearest-responder distance, land-cover class, population density | `app/jobs/run_ingestion.py` | `hotspots` rows |
| 2.5 | **[ADVANCED]** Chemical fingerprint + SAR + GFM novelty, only for flagged clusters | `app/ingestion/tropomi.py`, `sentinel1.py`, `app/ml/novelty.py` | enrichment scores |
| 3 | HDBSCAN discovery of persistent sites (haversine metric) | `app/ml/discovery.py` | `discovered_clusters` rows |
| 4 | Build correlation graph: physical edges (pipeline/transmission/rail) + **[ADVANCED]** wind-transport edges | `app/graph/build_graph.py`, `wind_edges.py` | `cluster_edges` rows |
| 5 | Per-cluster, per-sensor changepoint detection (spike/silence) + decay-curve FRP trend | `app/ml/anomaly.py` | `anomaly_flags` rows |
| 6 | Cross-graph correlation: did a connected cluster (physical or wind) also spike in a matching window? | `app/jobs/run_pipeline.py` | feature input |
| 7 | XGBoost classification into 6 classes + confidence-gated "unclassified" 7th bucket, explained via SHAP | `app/ml/classifier.py` | `predicted_class`, `classification_confidence` |
| 7.5 | Serving guards: deterministic overrides for non-combustion facilities and low-confidence forest/cropland ambiguity | `app/ml/serving_guards.py` | possibly-revised `predicted_class` + `classification_override_note` |
| 8 | Weighted risk score (0-100) → L0-L3 tier | `app/risk/scoring.py` | `risk_score`, `risk_tier` |
| 9 | Store everything in PostGIS with spatial indexes | `app/models/*.py` | queryable GIS tables |
| 10 | FastAPI: filterable JSON + GeoJSON endpoints | `app/api/routes/*.py` | `/clusters`, `/hotspots`, `/alerts`, `/incidents` |
| 11 | Next.js + Leaflet: class-colored markers, dual-style edges (solid=physical, dashed=wind), risk-tier badges, cluster detail panel, incident panel | `frontend/` | map overlay UI |
| 12 | Two independent alerting layers for L2/L3 events — see "Alerting: two layers" below | `app/alerts/sachet.py`, `app/alerts/incident_dispatch.py` | outbound alert payload + tiered incident |

## Alerting: two layers, answering two different questions

`app/alerts/sachet.py` and `app/alerts/incident_dispatch.py` both fire on
the same risk_tier gate (L2/L3), and both write a row every time, but they
are not the same mechanism and neither replaces the other:

- **Alert** (`app/models/alert.py`) is fire-and-forget: a single CAP-shaped
  webhook payload, written once, no notion of "did anyone see this." It
  answers "what did the system broadcast."
- **Incident** (`app/models/incident.py`) is stateful: it tracks which
  tier has been notified, escalates to the next tier if nobody
  acknowledges within `ESCALATION_INTERVAL_SECONDS`, and stops the moment
  someone does. It answers "did a human confirm this, and who."

Both share one master safety switch, `ALERT_DISPATCH_ENABLED` (default
`false`) — a demo, a replay of historical data, or a CI run must never be
able to page anyone by accident, regardless of which layer would have
fired. See `app/alerts/email_channel.py`'s module docstring for the full
reasoning, and docs/MERGE_NOTES.md for where this pattern came from.

## Serving guards: rules for what a trained model can't reliably learn

`app/ml/serving_guards.py` runs after the classifier, before risk scoring,
and can override `predicted_class` for two narrow, specific cases:

1. A detection right at a solar or wind facility (WRI `fuel_type`) can't
   physically be a combustion fire — panel glare and gearbox heat are real
   thermal anomalies with no fire involved. No amount of training data
   fixes this; it's a hard rule, not a probability.
2. A low-confidence `agricultural_burn`/`other` call sitting on dense
   forest cover gets a defense-in-depth nudge toward `wildfire`. This is
   deliberately a safety net, not the primary mechanism — `land_cover_class`
   is already a classifier input feature (see "Validation methodology"
   below), so a *confident* prediction means the model already looked at
   land cover and made its own call; this guard only overrides when the
   model itself wasn't sure.

Every override is recorded in `classification_override_note` (on the
cluster row, in the alert payload, and in the API response) rather than
silently changing the label — see that module's docstring for the full
reasoning.

## The correlation graph is heterogeneous, not single-purpose

Most graph-based infrastructure risk work (cascading-failure GNN research
in particular) is built for power grids with known physics and simulated
outage data. There's no equivalent physics simulator for a satellite-
observed thermal-event network, so this system uses two *deterministic,
independently-computed* edge types instead of trying to force-fit one:

- **Physical edges** — clusters within `INFRA_BUFFER_KM` of a shared OSM
  pipeline, transmission line, or rail corridor. Static; doesn't change
  hour to hour.
- **Wind-transport edges** *(Phase 3)* — for a cluster that just crossed
  the anomaly threshold, is another cluster within a plausible plume-
  travel distance and roughly downwind at that hour? Time-scoped
  (`valid_from`/`valid_to`), recomputed per anomaly event.

A toxic release doesn't need a shared pipeline to threaten the facility
next door — it needs the wind blowing the wrong way. Centrality
(betweenness + degree, averaged) is computed over the physical graph today
and feeds the risk score; see [ROADMAP.md](./ROADMAP.md) for the (explicitly
stretch-goal) GNN upgrade path that would learn a cascade probability
instead of using a hand-set centrality heuristic.

## Evidence fusion, not evidence replacement

Phase 3's three additional channels are *never* used to override the
6-class softmax output directly — see `FireClassifier.apply_evidence_fusion`
in `app/ml/classifier.py`. Specifically:

- **Chemical fingerprint** (TROPOMI SO2/NO2/CO/aerosol index) and
  **SAR structural change** (Sentinel-1) are stored as separate scores on
  the cluster and folded into the *risk score*, not the classification —
  "sulfur-heavy plume" or "physical structure changed" is evidence about
  severity and confirmation, not a vote for a different taxonomy label.
- **GFM visual novelty** (frozen Prithvi-EO-2.0/Clay embedding distance
  from known-class centroids) is the one channel that *can* override a
  confident-but-wrong softmax prediction, downgrading it to
  `unclassified` — because a high novelty score means "this doesn't look
  like anything in the training distribution," which is exactly the case
  where trusting the classifier's confidence would be a mistake. This
  targets the rare-accident-class problem directly: no labeled accident
  examples are needed for this channel to work, since only the known-class
  centroids need labels.

## Validation methodology (read before reporting any accuracy number)

González-Martínez & Soltan's 2026 leakage study on FIRMS-based classifiers
found a naive random-split F1 of 0.985 that fell to 0.767 under an
event-aware split and 0.627 under a full spatial holdout, because the
model partly memorized *where* known events occurred rather than learning
transferable signal. Two rules, both implemented in `app/ml/train.py` and
`app/ml/features.py`:

1. **Never use raw latitude/longitude as a classifier feature.** Use
   `distance_to_industrial_m` and `land_cover_class` instead — they carry
   "is this an industrial area" without encoding *which* one.
2. **Validate with a spatial-block holdout, not a random split.**
   `app/ml/train.py` computes both and logs the gap explicitly — report
   the spatial-block number in the judging deck, not the random-split one,
   and run `scripts/validate_spatial_leakage.py` first to confirm your
   labeled dataset actually has enough geographic diversity per class for
   the holdout to mean anything.
3. **Build cluster-density features causally.** `trailing_detection_count_6h`
   /`_24h` (`app/ml/features.py::build_causal_cluster_density`) only ever
   look at rows at-or-before the timestamp being scored — this is what
   makes the feature valid for live scoring, not just backtesting.
4. **If any of your labels came from `app/ml/weak_labeling.py`, run the
   circularity audit too.** A spatial-block holdout alone still grades the
   model against that same rule's own output — `scripts/circularity_audit.py`
   retrains with the rule-defining features removed and reports how much
   of the score depends on them, and `scripts/evaluate_verified_labels.py`
   checks predictions against `data/reference/verified_events.csv`, a
   small independently-cited set that wasn't derived from the rule at all.
   Report both alongside the headline spatial-block number, not instead
   of it — see docs/ROADMAP.md, "Label sourcing."

## Risk scoring is a documented heuristic, not a calibrated model

`app/risk/scoring.py`'s weights (`WEIGHTS`, `CLASS_SEVERITY`) are a
reasoned starting point, not a validated output. Say so explicitly if
asked — the L0-L3 bucketing is genuinely useful for at-a-glance
prioritization; the specific numeric weights are an assumption to defend,
not a result to cite.
