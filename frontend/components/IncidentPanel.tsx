"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Incident, IncidentStatus } from "@/types";

// Separate from AlertFeed on purpose — an Alert is a fire-and-forget CAP
// payload, an Incident is the stateful, acknowledgeable tiered-escalation
// workflow (see app/alerts/incident_dispatch.py). Showing both side by
// side is deliberate: this panel answers "who's been notified and did
// anyone confirm it," which the alert feed alone can't.
const STATUS_LABEL: Record<IncidentStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  auto_resolved: "Auto-resolved",
};

const STATUS_COLOR: Record<IncidentStatus, string> = {
  open: "var(--tier-l3)",
  acknowledged: "var(--tier-l0)",
  auto_resolved: "var(--text-muted)",
};

export default function IncidentPanel({ onSelectCluster }: { onSelectCluster: (id: number) => void }) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => api.listIncidents().then(setIncidents).catch((e) => setError(String(e)));

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000); // matches AlertFeed's polling interval
    return () => clearInterval(interval);
  }, []);

  async function handleAcknowledge(incident: Incident) {
    setBusyId(incident.id);
    try {
      await api.acknowledgeIncidentById(incident.id, "dashboard");
    } finally {
      setBusyId(null);
      load();
    }
  }

  return (
    <div style={{ padding: "16px 20px", borderTop: "1px solid var(--border-hairline)" }}>
      <h2 style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", margin: "0 0 12px" }}>
        Incidents (tiered escalation)
      </h2>

      {error && <p style={{ fontSize: 12, color: "var(--tier-l3)" }}>Couldn&apos;t load incidents.</p>}
      {!error && incidents.length === 0 && (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
          No incidents yet — one opens automatically the first time a cluster reaches L2/L3.
        </p>
      )}

      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {incidents.map((incident) => (
          <li
            key={incident.id}
            style={{
              background: "var(--bg-panel-raised)",
              border: "1px solid var(--border-hairline)",
              borderLeft: `3px solid ${STATUS_COLOR[incident.status]}`,
              borderRadius: 6,
              padding: "10px 12px",
            }}
          >
            <button
              onClick={() => onSelectCluster(incident.cluster_id)}
              style={{ all: "unset", cursor: "pointer", display: "block", width: "100%", color: "var(--text-primary)" }}
            >
              <div style={{ fontSize: 13 }}>
                {incident.predicted_class} — {incident.risk_tier} — Tier {incident.current_tier}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, fontFamily: "var(--font-data)" }}>
                {STATUS_LABEL[incident.status]}
                {incident.nearest_responder_name &&
                  ` · nearest responder: ${incident.nearest_responder_name} (${(
                    (incident.nearest_responder_distance_m ?? 0) / 1000
                  ).toFixed(1)} km)`}
              </div>
            </button>
            {incident.status === "open" && (
              <button
                onClick={() => handleAcknowledge(incident)}
                disabled={busyId === incident.id}
                style={{
                  marginTop: 8, fontSize: 11, padding: "4px 8px", borderRadius: 4,
                  border: "1px solid var(--border-hairline)", background: "transparent",
                  color: "var(--text-primary)", cursor: "pointer",
                }}
              >
                {busyId === incident.id ? "…" : "Acknowledge"}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
