"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Cluster, ClusterHistoryPoint, PredictedClass } from "@/types";

const CLASS_LABEL: Record<PredictedClass, string> = {
  industrial_fire: "Industrial fire",
  gas_flare: "Gas flare",
  mining: "Mining",
  agricultural_burn: "Agricultural burn",
  wildfire: "Wildfire",
  other: "Other",
  unclassified: "Unclassified — needs manual review",
};

function EvidenceRow({ label, value }: { label: string; value: number | null }) {
  if (value === null) return null;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0" }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ fontFamily: "var(--font-data)" }}>{value.toFixed(2)}</span>
    </div>
  );
}

export default function ClusterDetailPanel({ clusterId, onClose }: { clusterId: number; onClose: () => void }) {
  const [cluster, setCluster] = useState<Cluster | null>(null);
  const [history, setHistory] = useState<ClusterHistoryPoint[]>([]);

  // No manual reset-to-null here on clusterId change — the parent renders
  // this component with `key={clusterId}` (see app/page.tsx), so switching
  // clusters remounts it fresh instead of reusing stale state. That avoids
  // a synchronous setState-in-effect render cascade for what would
  // otherwise just be clearing state before the real fetch resolves.
  useEffect(() => {
    api.getCluster(clusterId).then(setCluster).catch(() => {});
    api
      .getClusterHistory(clusterId)
      .then((h) => setHistory(h.slice(-10)))
      .catch(() => {});
  }, [clusterId]);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        height: "100vh",
        width: 340,
        background: "var(--bg-panel)",
        borderLeft: "1px solid var(--border-hairline)",
        padding: 20,
        overflowY: "auto",
        zIndex: 1000,
      }}
    >
      <button
        onClick={onClose}
        style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: 13, padding: 0, marginBottom: 16 }}
      >
        Close
      </button>

      {!cluster ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading cluster {clusterId}…</p>
      ) : (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 4px" }}>
            {cluster.predicted_class ? CLASS_LABEL[cluster.predicted_class] : "Unclassified"}
          </h2>
          <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 0 16px", fontFamily: "var(--font-data)" }}>
            {cluster.centroid_lat.toFixed(4)}, {cluster.centroid_lon.toFixed(4)}
          </p>

          <div
            style={{
              display: "inline-block",
              padding: "4px 10px",
              borderRadius: 4,
              fontSize: 12,
              background: "var(--bg-panel-raised)",
              border: "1px solid var(--border-hairline)",
              marginBottom: 16,
            }}
          >
            {cluster.risk_tier ?? "—"} · risk {cluster.risk_score?.toFixed(0) ?? "—"}/100
          </div>

          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
            {cluster.total_detections} detections · classifier confidence{" "}
            {cluster.classification_confidence !== null ? `${(cluster.classification_confidence * 100).toFixed(0)}%` : "—"}
          </div>

          {(cluster.chem_fingerprint_score !== null || cluster.sar_structural_change_score !== null || cluster.gfm_novelty_score !== null) && (
            <div style={{ marginBottom: 16 }}>
              <h3 style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 0 6px", fontWeight: 600 }}>
                Advanced evidence
              </h3>
              <EvidenceRow label="Chemical fingerprint" value={cluster.chem_fingerprint_score} />
              <EvidenceRow label="SAR structural change" value={cluster.sar_structural_change_score} />
              <EvidenceRow label="Visual novelty (GFM)" value={cluster.gfm_novelty_score} />
            </div>
          )}

          {history.length > 0 && (
            <div>
              <h3 style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 0 6px", fontWeight: 600 }}>
                Recent detections
              </h3>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {history.map((h, i) => (
                  <li
                    key={i}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 11,
                      fontFamily: "var(--font-data)",
                      padding: "3px 0",
                      color: "var(--text-muted)",
                    }}
                  >
                    <span>{new Date(h.acq_datetime).toLocaleDateString()}</span>
                    <span>{h.sensor}</span>
                    <span>{h.frp !== null ? `${h.frp.toFixed(1)} MW` : "—"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
