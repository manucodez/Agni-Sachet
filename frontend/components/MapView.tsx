"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useState } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import { api } from "@/lib/api";
import type { Cluster, ClusterConnection, PredictedClass } from "@/types";

// Leaflet draws onto SVG/canvas outside the normal CSS cascade, so these
// mirror the tokens in globals.css as literal values rather than trying to
// resolve var(--x) at draw time — keep the two in sync by hand if the
// palette changes.
const CLASS_COLOR: Record<PredictedClass, string> = {
  industrial_fire: "#c9433e",
  gas_flare: "#d9a441",
  mining: "#7d7266",
  agricultural_burn: "#7fa15a",
  wildfire: "#b3542f",
  other: "#5c6672",
  unclassified: "#8b6fb0",
};

const CLASS_LABEL: Record<PredictedClass, string> = {
  industrial_fire: "Industrial fire",
  gas_flare: "Gas flare",
  mining: "Mining",
  agricultural_burn: "Agricultural burn",
  wildfire: "Wildfire",
  other: "Other",
  unclassified: "Unclassified",
};

const EDGE_COLOR = { physical: "#4a5a6a", wind: "#6aa3b3" };
const SELECTED_MARKER_STROKE = "#e7e4dd";

// India-wide default view, matching the ingestion bbox in .env.example
const INDIA_CENTER: [number, number] = [22.5, 82.5];
const INDIA_ZOOM = 5;

function FlyToSelected({ clusters, selectedClusterId }: { clusters: Cluster[]; selectedClusterId: number | null }) {
  const map = useMap();
  useEffect(() => {
    if (selectedClusterId === null) return;
    const c = clusters.find((c) => c.cluster_id === selectedClusterId);
    if (c) map.flyTo([c.centroid_lat, c.centroid_lon], Math.max(map.getZoom(), 9), { duration: 0.6 });
  }, [selectedClusterId, clusters, map]);
  return null;
}

export default function MapView({
  clusters,
  selectedClusterId,
  onSelectCluster,
}: {
  clusters: Cluster[];
  selectedClusterId: number | null;
  onSelectCluster: (id: number) => void;
}) {
  const [connections, setConnections] = useState<Record<number, ClusterConnection[]>>({});

  useEffect(() => {
    if (selectedClusterId === null) return;
    api
      .getClusterConnections(selectedClusterId)
      .then((conns) => setConnections((prev) => ({ ...prev, [selectedClusterId]: conns })))
      .catch(() => {
        /* connections are supplementary — a failed fetch shouldn't break the map */
      });
  }, [selectedClusterId]);

  const clusterById = new Map(clusters.map((c) => [c.cluster_id, c]));
  const selectedConnections = selectedClusterId !== null ? connections[selectedClusterId] ?? [] : [];

  return (
    <MapContainer key="main-map" center={INDIA_CENTER} zoom={INDIA_ZOOM} style={{ height: "100vh", width: "100%" }}>
      <TileLayer
        // CARTO's dark basemap — matches the instrument-panel theme instead
        // of default OSM light tiles fighting the rest of the UI.
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
      />
      <FlyToSelected clusters={clusters} selectedClusterId={selectedClusterId} />

      {selectedConnections.map((conn, i) => {
        const source = clusterById.get(selectedClusterId as number);
        const target = clusterById.get(conn.target_cluster_id);
        if (!source || !target) return null;
        return (
          <Polyline
            key={`${conn.edge_type}-${i}`}
            positions={[
              [source.centroid_lat, source.centroid_lon],
              [target.centroid_lat, target.centroid_lon],
            ]}
            pathOptions={{
              color: EDGE_COLOR[conn.edge_type],
              weight: conn.edge_type === "physical" ? 2 : 1.5,
              dashArray: conn.edge_type === "wind" ? "6 6" : undefined,
              opacity: 0.85,
            }}
          />
        );
      })}

      {clusters.map((cluster) => {
        const color = cluster.predicted_class ? CLASS_COLOR[cluster.predicted_class] : "#888888";
        const isSelected = cluster.cluster_id === selectedClusterId;
        return (
          <CircleMarker
            key={cluster.cluster_id}
            center={[cluster.centroid_lat, cluster.centroid_lon]}
            radius={isSelected ? 10 : 6 + Math.min(4, (cluster.risk_score ?? 0) / 25)}
            pathOptions={{
              color: isSelected ? SELECTED_MARKER_STROKE : color,
              fillColor: color,
              fillOpacity: 0.85,
              weight: isSelected ? 2 : 1,
            }}
            eventHandlers={{ click: () => onSelectCluster(cluster.cluster_id) }}
          >
            <Popup>
              <strong>{cluster.predicted_class ? CLASS_LABEL[cluster.predicted_class] : "Unknown"}</strong>
              <br />
              Risk: {cluster.risk_tier ?? "—"} ({cluster.risk_score?.toFixed(0) ?? "—"})
              <br />
              {cluster.total_detections} detections
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
