// Mirrors backend/app/schemas/*.py — keep these in sync by hand for now;
// see docs/ROADMAP.md re: generating this from the OpenAPI schema instead.

export type PredictedClass =
  | "industrial_fire"
  | "gas_flare"
  | "mining"
  | "agricultural_burn"
  | "wildfire"
  | "other"
  | "unclassified";

export type RiskTier = "L0" | "L1" | "L2" | "L3";

export interface Cluster {
  cluster_id: number;
  centroid_lat: number;
  centroid_lon: number;
  first_seen: string;
  last_seen: string;
  total_detections: number;
  predicted_class: PredictedClass | null;
  classification_confidence: number | null;
  classification_override_note: string | null;
  chem_fingerprint_score: number | null;
  sar_structural_change_score: number | null;
  gfm_novelty_score: number | null;
  centrality_score: number | null;
  risk_score: number | null;
  risk_tier: RiskTier | null;
}

export interface ClusterConnection {
  target_cluster_id: number;
  edge_type: "physical" | "wind";
  connection_detail: string | null;
  weight: number | null;
}

export interface ClusterHistoryPoint {
  acq_datetime: string;
  sensor: string;
  frp: number | null;
  brightness_temp: number | null;
}

export interface Alert {
  id: string;
  created_at: string;
  event_type: string;
  severity: RiskTier;
  location_lat: number;
  location_lon: number;
  description: string;
  cluster_ids_involved: number[];
  delivered: boolean;
}

export interface GeoJSONFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: Record<string, unknown>;
  }>;
}

// Mirrors backend/app/schemas/incident.py — see app/models/incident.py for
// why this is a separate, stateful workflow from Alert above (Alert is
// fire-and-forget; an Incident tracks tier/acknowledgement over time).
export type IncidentStatus = "open" | "acknowledged" | "auto_resolved";

export interface Incident {
  id: string;
  cluster_id: number;
  created_at: string;
  last_escalated_at: string;
  predicted_class: PredictedClass;
  risk_score: number;
  risk_tier: RiskTier;
  centroid_lat: number;
  centroid_lon: number;
  nearest_responder_distance_m: number | null;
  nearest_responder_type: "fire_station" | "hospital" | null;
  nearest_responder_name: string | null;
  current_tier: number;
  status: IncidentStatus;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}
