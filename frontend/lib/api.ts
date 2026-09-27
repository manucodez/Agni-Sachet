import type { Alert, Cluster, ClusterConnection, ClusterHistoryPoint, GeoJSONFeatureCollection, Incident } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listClusters: (params?: { predicted_class?: string; min_risk?: number; risk_tier?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return getJSON<Cluster[]>(`/clusters${qs ? `?${qs}` : ""}`);
  },
  clustersGeoJSON: (params?: { predicted_class?: string; min_risk?: number }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return getJSON<GeoJSONFeatureCollection>(`/clusters/geojson${qs ? `?${qs}` : ""}`);
  },
  getCluster: (clusterId: number) => getJSON<Cluster>(`/clusters/${clusterId}`),
  getClusterHistory: (clusterId: number) => getJSON<ClusterHistoryPoint[]>(`/clusters/${clusterId}/history`),
  getClusterConnections: (clusterId: number) => getJSON<ClusterConnection[]>(`/clusters/${clusterId}/connections`),
  listAlerts: (severity?: string) => getJSON<Alert[]>(`/alerts${severity ? `?severity=${severity}` : ""}`),

  // Tiered incident-escalation workflow — see app/alerts/incident_dispatch.py.
  // Distinct from listAlerts above: an Incident is stateful (tier,
  // acknowledgement) where an Alert is a fire-and-forget CAP payload.
  listIncidents: (status?: string) => getJSON<Incident[]>(`/incidents${status ? `?status=${status}` : ""}`),
  getIncident: (incidentId: string) => getJSON<Incident>(`/incidents/${incidentId}`),
  acknowledgeIncident: (ackToken: string, acknowledgedBy?: string) =>
    postJSON<Incident>(`/incidents/${ackToken}/acknowledge`, { acknowledged_by: acknowledgedBy ?? null }),
  acknowledgeIncidentById: (incidentId: string, acknowledgedBy?: string) =>
    postJSON<Incident>(`/incidents/id/${incidentId}/acknowledge`, { acknowledged_by: acknowledgedBy ?? null }),
  simulateIncident: (clusterId: number, riskScore?: number, riskTier?: string) => {
    const qs = new URLSearchParams({
      ...(riskScore !== undefined ? { risk_score: String(riskScore) } : {}),
      ...(riskTier !== undefined ? { risk_tier: riskTier } : {}),
    }).toString();
    return postJSON<Incident>(`/incidents/${clusterId}/simulate${qs ? `?${qs}` : ""}`);
  },
};
