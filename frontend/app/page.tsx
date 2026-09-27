"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import AlertFeed from "@/components/AlertFeed";
import ClusterDetailPanel from "@/components/ClusterDetailPanel";
import FilterBar, { type Filters } from "@/components/FilterBar";
import IncidentPanel from "@/components/IncidentPanel";
import { api } from "@/lib/api";
import type { Cluster } from "@/types";

// Leaflet touches `window` at import time, so the map has to be client-only —
// a plain "use client" directive isn't enough, it still needs ssr:false.
const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export default function DashboardPage() {
  const [filters, setFilters] = useState<Filters>({});
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listClusters(filters)
      .then(setClusters)
      .catch((err) => setLoadError(String(err)));
  }, [filters]);

  return (
    <main style={{ display: "grid", gridTemplateColumns: "320px 1fr", height: "100vh" }}>
      <aside
        style={{
          borderRight: "1px solid var(--border-hairline)",
          background: "var(--bg-panel)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "20px 20px 12px" }}>
          <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Agni Sachet</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "4px 0 0" }}>
            Industrial thermal source monitor
          </p>
        </div>
        <FilterBar filters={filters} onChange={setFilters} />
        <div style={{ flex: 1, overflowY: "auto", borderTop: "1px solid var(--border-hairline)" }}>
          <AlertFeed onSelectCluster={setSelectedClusterId} />
          <IncidentPanel onSelectCluster={setSelectedClusterId} />
        </div>
      </aside>

      <div style={{ position: "relative" }}>
        {loadError && (
          <div style={{ position: "absolute", top: 12, left: 12, zIndex: 1000, color: "var(--tier-l3)", background: "var(--bg-panel)", padding: "8px 12px", borderRadius: 6, fontSize: 13 }}>
            Couldn&apos;t reach the API at the configured URL — is the backend running? ({loadError})
          </div>
        )}
        <MapView clusters={clusters} selectedClusterId={selectedClusterId} onSelectCluster={setSelectedClusterId} />
        {selectedClusterId !== null && (
          <ClusterDetailPanel key={selectedClusterId} clusterId={selectedClusterId} onClose={() => setSelectedClusterId(null)} />
        )}
      </div>
    </main>
  );
}
