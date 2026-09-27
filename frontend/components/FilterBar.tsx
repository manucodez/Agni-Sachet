"use client";

import type { PredictedClass, RiskTier } from "@/types";

export interface Filters {
  predicted_class?: PredictedClass;
  risk_tier?: RiskTier;
}

const CLASS_OPTIONS: { value: PredictedClass; label: string }[] = [
  { value: "industrial_fire", label: "Industrial fire" },
  { value: "gas_flare", label: "Gas flare" },
  { value: "mining", label: "Mining" },
  { value: "agricultural_burn", label: "Agricultural burn" },
  { value: "wildfire", label: "Wildfire" },
  { value: "other", label: "Other" },
  { value: "unclassified", label: "Unclassified" },
];

const TIER_OPTIONS: { value: RiskTier; label: string }[] = [
  { value: "L3", label: "L3 — Critical" },
  { value: "L2", label: "L2 — Elevated" },
  { value: "L1", label: "L1 — Watch" },
  { value: "L0", label: "L0 — Low" },
];

const selectStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  background: "var(--bg-panel-raised)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-hairline)",
  borderRadius: 6,
  fontSize: 13,
};

export default function FilterBar({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  return (
    <div style={{ padding: "0 20px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
      <label style={{ fontSize: 12, color: "var(--text-muted)" }}>
        Class
        <select
          style={{ ...selectStyle, marginTop: 4 }}
          value={filters.predicted_class ?? ""}
          onChange={(e) => onChange({ ...filters, predicted_class: (e.target.value || undefined) as PredictedClass | undefined })}
        >
          <option value="">All classes</option>
          {CLASS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <label style={{ fontSize: 12, color: "var(--text-muted)" }}>
        Risk tier
        <select
          style={{ ...selectStyle, marginTop: 4 }}
          value={filters.risk_tier ?? ""}
          onChange={(e) => onChange({ ...filters, risk_tier: (e.target.value || undefined) as RiskTier | undefined })}
        >
          <option value="">All tiers</option>
          {TIER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
