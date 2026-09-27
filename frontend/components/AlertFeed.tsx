"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Alert, RiskTier } from "@/types";

const TIER_COLOR: Record<RiskTier, string> = {
  L3: "var(--tier-l3)",
  L2: "var(--tier-l2)",
  L1: "var(--tier-l1)",
  L0: "var(--tier-l0)",
};

export default function AlertFeed({ onSelectCluster }: { onSelectCluster: (id: number) => void }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.listAlerts().then(setAlerts).catch((e) => setError(String(e)));
    load();
    const interval = setInterval(load, 30_000); // simple polling — fine at hackathon scale, swap for SSE/websocket later
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ padding: "16px 20px" }}>
      <h2 style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", margin: "0 0 12px" }}>
        Recent alerts
      </h2>

      {error && <p style={{ fontSize: 12, color: "var(--tier-l3)" }}>Couldn&apos;t load alerts.</p>}
      {!error && alerts.length === 0 && (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>No L2/L3 alerts yet — the feed fills in as the pipeline runs.</p>
      )}

      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {alerts.map((alert) => (
          <li key={alert.id}>
            <button
              onClick={() => onSelectCluster(alert.cluster_ids_involved[0])}
              style={{
                width: "100%",
                textAlign: "left",
                background: "var(--bg-panel-raised)",
                border: "1px solid var(--border-hairline)",
                borderLeft: `3px solid ${TIER_COLOR[alert.severity]}`,
                borderRadius: 6,
                padding: "10px 12px",
                cursor: "pointer",
                color: "var(--text-primary)",
              }}
            >
              <div style={{ fontSize: 13 }}>{alert.description}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, fontFamily: "var(--font-data)" }}>
                {new Date(alert.created_at).toLocaleString()}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
