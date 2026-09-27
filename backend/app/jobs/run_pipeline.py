"""
The steady-state pipeline: anomaly detection -> classification -> graph
update -> risk scoring -> alerts. Run after run_discovery has populated
clusters, on whatever cadence matches your FIRMS pull frequency (every
few hours is reasonable for NRT data).

Run with:  python -m app.jobs.run_pipeline
or:        make pipeline

This is intentionally the one place that wires core (Phases 0-2) and
advanced (Phase 3) channels together — see the ADVANCED CHANNELS block
below, which only fires for clusters that already crossed the anomaly
threshold, keeping the expensive calls rare by construction.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import select

from app.alerts.incident_dispatch import auto_resolve_if_subsided, trigger_or_escalate_incident
from app.alerts.sachet import build_sachet_payload, dispatch_alert
from app.core.config import settings
from app.core.db import SessionLocal
from app.graph.build_graph import build_physical_graph, compute_centrality
from app.graph.wind_edges import find_wind_edges
from app.ml.anomaly import detect_changepoints
from app.ml.classifier import FireClassifier, dump_shap_reasons
from app.ml.features import build_causal_cluster_density, build_feature_row
from app.ml.serving_guards import apply_serving_guards
from app.models.alert import Alert
from app.models.anomaly import AnomalyFlag
from app.models.cluster import DiscoveredCluster
from app.models.edge import ClusterEdge
from app.models.hotspot import Hotspot
from app.risk.scoring import RiskInput, compute_risk_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPIKE_SEVERITY_THRESHOLD_FOR_ADVANCED_CHANNELS = 1.5  # only pull chemistry/SAR/GFM above this


def run_pipeline() -> None:
    logger.info("=== Pipeline pass starting ===")
    classifier = FireClassifier()
    try:
        classifier.load()
    except FileNotFoundError as exc:
        logger.error("%s — skipping classification/risk this pass", exc)
        classifier = None

    with SessionLocal() as session:
        clusters = pd.DataFrame(
            [
                {"cluster_id": c.cluster_id, "centroid_lat": c.centroid_lat, "centroid_lon": c.centroid_lon}
                for c in session.execute(select(DiscoveredCluster)).scalars().all()
            ]
        )
        if clusters.empty:
            logger.warning("No discovered clusters — run discovery first")
            return

        all_hotspots = pd.DataFrame(
            [
                {
                    "id": h.id, "cluster_id": h.cluster_id, "sensor": h.sensor,
                    "acq_datetime": h.acq_datetime, "frp": h.frp, "brightness_temp": h.brightness_temp,
                    "land_cover_class": h.land_cover_class,
                    "nearest_industrial_distance_m": h.nearest_industrial_distance_m,
                    "nearest_power_plant_distance_m": h.nearest_power_plant_distance_m,
                    "nearest_power_plant_fuel_type": h.nearest_power_plant_fuel_type,
                    "nearest_responder_distance_m": h.nearest_responder_distance_m,
                    "nearest_responder_type": h.nearest_responder_type,
                    "nearest_responder_name": h.nearest_responder_name,
                    "population_density_nearby": h.population_density_nearby,
                }
                for h in session.execute(select(Hotspot)).scalars().all()
            ]
        )

        # === Step 4: physical graph + centrality ===
        # NOTE: infra_lines would come from a stored OSM lines table in a
        # full build; wiring that persistence is a small addition once
        # you've decided where OSM lines live (see docs/ROADMAP.md).
        physical_graph, _physical_edges = build_physical_graph(clusters, infra_lines=[])
        centrality = compute_centrality(physical_graph)

        for cluster_id, group in all_hotspots.groupby("cluster_id"):
            if cluster_id is None:
                continue
            cluster_row = clusters[clusters["cluster_id"] == cluster_id].iloc[0]

            # === Step 5: anomaly detection, per sensor ===
            all_events = []
            for sensor, sensor_group in group.groupby("sensor"):
                sensor_group = sensor_group.sort_values("acq_datetime")
                events = detect_changepoints(sensor_group, cluster_id=int(cluster_id), sensor=sensor)
                all_events.extend(events)
                for ev in events:
                    session.add(
                        AnomalyFlag(
                            cluster_id=ev.cluster_id, sensor=ev.sensor, flag_type=ev.flag_type,
                            timestamp=ev.timestamp, severity_score=ev.severity_score,
                            baseline_value=ev.baseline_value, observed_value=ev.observed_value,
                            frp_trend=ev.frp_trend,
                        )
                    )

            max_severity = max((e.severity_score for e in all_events), default=0.0)
            latest_row = group.sort_values("acq_datetime").iloc[-1]

            # === ADVANCED CHANNELS (Phase 3) — only for real spikes ===
            chem_score, sar_score, novelty_score_val = None, None, None
            if max_severity >= SPIKE_SEVERITY_THRESHOLD_FOR_ADVANCED_CHANNELS:
                chem_score, sar_score, novelty_score_val = _run_advanced_channels(
                    cluster_row, event_date=latest_row["acq_datetime"].date()
                )

            # === Step 7: classification ===
            predicted_class, confidence, top_reasons = "unclassified", 0.0, []
            if classifier is not None:
                count_6h, count_24h = build_causal_cluster_density(
                    all_hotspots, cluster_id, latest_row["acq_datetime"]
                )
                site_baseline = group[group["acq_datetime"] < latest_row["acq_datetime"]]["frp"]
                feature_row = build_feature_row(
                    land_cover_class=latest_row["land_cover_class"],
                    distance_to_industrial_m=latest_row["nearest_industrial_distance_m"],
                    distance_to_power_plant_m=latest_row["nearest_power_plant_distance_m"],
                    acq_datetime=latest_row["acq_datetime"],
                    frp=latest_row["frp"],
                    site_frp_mean=site_baseline.mean() if not site_baseline.empty else None,
                    site_frp_std=site_baseline.std() if not site_baseline.empty else None,
                    brightness_temp=latest_row["brightness_temp"],
                    trailing_detection_count_6h=count_6h,
                    trailing_detection_count_24h=count_24h,
                    is_correlated_with_connected_site=False,  # set below, after Step 6
                    graph_centrality_score=centrality.get(int(cluster_id), 0.0),
                )
                result = classifier.predict(feature_row.as_dict())
                result = classifier.apply_evidence_fusion(
                    result, chem_fingerprint_score=chem_score, sar_structural_change_score=sar_score,
                    gfm_novelty_score=novelty_score_val,
                )
                predicted_class, confidence, top_reasons = result.predicted_class, result.confidence, result.top_reasons

            # === Step 7b: serving guards ===
            # Deterministic post-hoc rules for the cases a trained softmax
            # can't be relied on to get right by itself (non-combustion
            # facilities, low-confidence forest/cropland ambiguity) -- see
            # app/ml/serving_guards.py for why this exists as a separate
            # step rather than more training data. Runs even when the
            # classifier itself didn't (predicted_class == "unclassified"),
            # since land_cover_class / power-plant proximity are still
            # known and a solar-farm glare spike shouldn't sit in the
            # unclassified bucket either.
            guard_result = apply_serving_guards(
                predicted_class, confidence,
                land_cover_class=latest_row["land_cover_class"],
                nearest_industrial_distance_m=latest_row["nearest_industrial_distance_m"],
                nearest_power_plant_distance_m=latest_row["nearest_power_plant_distance_m"],
                nearest_power_plant_fuel_type=latest_row["nearest_power_plant_fuel_type"],
            )
            predicted_class, confidence = guard_result.served_class, guard_result.served_confidence
            override_note = guard_result.override_note
            if override_note:
                logger.info("Cluster %s: %s", cluster_id, override_note)

            # === Step 8: risk scoring ===
            risk_score, risk_tier = compute_risk_score(
                RiskInput(
                    anomaly_severity=max_severity,
                    population_density_nearby=latest_row["population_density_nearby"],
                    graph_centrality_score=centrality.get(int(cluster_id), 0.0),
                    predicted_class=predicted_class,
                    classification_confidence=confidence,
                    chem_fingerprint_score=chem_score,
                    sar_structural_change_score=sar_score,
                )
            )

            # --- persist cluster update ---
            cluster = session.get(DiscoveredCluster, int(cluster_id))
            cluster.predicted_class = predicted_class
            cluster.classification_confidence = confidence
            cluster.top_reasons_json = dump_shap_reasons(top_reasons)
            cluster.classification_override_note = override_note
            cluster.chem_fingerprint_score = chem_score
            cluster.sar_structural_change_score = sar_score
            cluster.gfm_novelty_score = novelty_score_val
            cluster.centrality_score = centrality.get(int(cluster_id), 0.0)
            cluster.risk_score = risk_score
            cluster.risk_tier = risk_tier

            # === Step 4b: wind edges (Phase 3), only from clusters that spiked ===
            if max_severity >= SPIKE_SEVERITY_THRESHOLD_FOR_ADVANCED_CHANNELS:
                wind_edges = find_wind_edges(
                    {"cluster_id": int(cluster_id), "centroid_lat": cluster_row["centroid_lat"], "centroid_lon": cluster_row["centroid_lon"]},
                    clusters, latest_row["acq_datetime"],
                )
                for we in wind_edges:
                    session.add(
                        ClusterEdge(
                            source_cluster_id=we.source_cluster_id, target_cluster_id=we.target_cluster_id,
                            edge_type="wind", connection_detail=f"{we.wind_bearing_deg}deg",
                            valid_from=we.valid_from, valid_to=we.valid_to, weight=we.weight,
                        )
                    )

            # === Step 12: alert if it crosses threshold ===
            # Two independent things happen here, not one: a single-shot CAP
            # webhook payload (Alert — unchanged, for any system already
            # consuming that feed) and a stateful, acknowledgeable tiered
            # escalation (Incident — new in the best-practices merge, see
            # app/alerts/incident_dispatch.py). Both are gated on the same
            # risk_tier check; they're written independently because they
            # answer different questions later ("what did we broadcast" vs
            # "did a human confirm this").
            if risk_tier in ("L2", "L3"):
                extra_evidence = {"frp_trend": all_events[-1].frp_trend if all_events else "unknown"}
                if override_note:
                    extra_evidence["classification_override_note"] = override_note
                payload = build_sachet_payload(
                    cluster_id=int(cluster_id), predicted_class=predicted_class,
                    lat=cluster_row["centroid_lat"], lon=cluster_row["centroid_lon"],
                    risk_score=risk_score, risk_tier=risk_tier,
                    extra_evidence=extra_evidence,
                )
                delivered = dispatch_alert(payload)
                session.add(
                    Alert(
                        id=payload["identifier"], created_at=datetime.now(timezone.utc),
                        event_type=predicted_class, severity=risk_tier,
                        location_lat=cluster_row["centroid_lat"], location_lon=cluster_row["centroid_lon"],
                        description=payload["info"]["event"], cluster_ids_involved=[int(cluster_id)],
                        sachet_payload=payload, delivered=delivered,
                    )
                )
                trigger_or_escalate_incident(
                    session, cluster_id=int(cluster_id), predicted_class=predicted_class,
                    risk_score=risk_score, risk_tier=risk_tier,
                    centroid_lat=cluster_row["centroid_lat"], centroid_lon=cluster_row["centroid_lon"],
                    nearest_responder_distance_m=latest_row["nearest_responder_distance_m"],
                    nearest_responder_type=latest_row["nearest_responder_type"],
                    nearest_responder_name=latest_row["nearest_responder_name"],
                )
            else:
                auto_resolve_if_subsided(session, cluster_id=int(cluster_id), risk_tier=risk_tier)

        session.commit()
    logger.info("=== Pipeline pass complete ===")


def _run_advanced_channels(cluster_row: pd.Series, event_date: date) -> tuple[float | None, float | None, float | None]:
    """Chemistry + SAR + GFM novelty — each wrapped so one failing doesn't
    block the others or the core pipeline. Returns (chem_score, sar_score,
    novelty_score), any of which may be None if that channel isn't
    configured (see .env.example) or failed."""
    chem_score = sar_score = novelty = None

    try:
        from app.ingestion.tropomi import TropomiAdapter

        fp = TropomiAdapter().fetch_fingerprint(cluster_row["centroid_lat"], cluster_row["centroid_lon"], event_date)
        # crude 0-1 "anomalousness" proxy from raw column densities — replace
        # with a properly calibrated model once you have labeled examples;
        # see docs/ARCHITECTURE.md "Chemical fingerprint calibration".
        if fp.so2_mol_m2 is not None:
            chem_score = min(1.0, fp.so2_mol_m2 / 0.02)
    except Exception:
        logger.debug("TROPOMI channel unavailable this pass", exc_info=True)

    try:
        from app.ingestion.sentinel1 import Sentinel1Adapter

        sar = Sentinel1Adapter().fetch_structural_change(cluster_row["centroid_lat"], cluster_row["centroid_lon"], event_date)
        sar_score = sar.coherence_drop_ratio
    except Exception:
        logger.debug("Sentinel-1 channel unavailable this pass", exc_info=True)

    try:
        from app.ml import novelty as novelty_module
        # A real implementation pulls a Sentinel-2 chip here first; left as
        # a documented gap (see app/ml/novelty.py) since chip download
        # depends on which backend (CDSE/GEE) you've configured.
        pass
    except Exception:
        logger.debug("GFM novelty channel unavailable this pass", exc_info=True)

    return chem_score, sar_score, novelty


if __name__ == "__main__":
    run_pipeline()
