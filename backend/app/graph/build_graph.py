"""
Step 4 — physical correlation graph. Connects discovered clusters that
share OSM/WRI infrastructure (pipeline, transmission line, rail corridor)
within a small buffer distance, using NetworkX.

Centrality (betweenness + degree, combined) becomes `centrality_score` on
DiscoveredCluster and feeds the risk score (app/risk/scoring.py) — a
cluster sitting on a highly-connected corridor matters more than an
identical-looking isolated one, because an anomaly there has more places
to cascade to. See app/graph/wind_edges.py for the second, independent
edge type this graph gets extended with in Phase 3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import networkx as nx
import pandas as pd
from shapely.geometry import LineString, Point

logger = logging.getLogger(__name__)

INFRA_BUFFER_KM = 2.0  # a cluster within this distance of a pipeline/line is "on" it


@dataclass
class PhysicalEdge:
    source_cluster_id: int
    target_cluster_id: int
    connection_detail: str  # "pipeline" | "transmission" | "rail"


def build_physical_graph(
    clusters: pd.DataFrame, infra_lines: list[dict]
) -> tuple[nx.Graph, list[PhysicalEdge]]:
    """
    Args:
        clusters: from discover_clusters/summarize_clusters — needs
            cluster_id, centroid_lat, centroid_lon.
        infra_lines: OSM adapter output filtered to category in
            {pipeline, transmission, rail} — each a dict with `coordinates`
            as a list of [lon, lat] points.
    """
    graph = nx.Graph()
    for _, row in clusters.iterrows():
        graph.add_node(int(row["cluster_id"]), lat=row["centroid_lat"], lon=row["centroid_lon"])

    # Which clusters sit near which infra line?
    line_to_clusters: dict[int, list[int]] = {}
    for i, line in enumerate(infra_lines):
        try:
            shapely_line = LineString(line["coordinates"])
        except (ValueError, KeyError):
            continue
        nearby = []
        for _, row in clusters.iterrows():
            point = Point(row["centroid_lon"], row["centroid_lat"])
            # cheap degrees->km approximation is fine at this buffer scale;
            # for tighter tolerances use a proper projected CRS instead.
            if shapely_line.distance(point) * 111.0 <= INFRA_BUFFER_KM:
                nearby.append((int(row["cluster_id"]), line.get("category", "infrastructure")))
        if len(nearby) >= 2:
            line_to_clusters[i] = nearby

    edges: list[PhysicalEdge] = []
    for _line_idx, nearby in line_to_clusters.items():
        cluster_ids = [c for c, _ in nearby]
        category = nearby[0][1]
        # connect consecutive clusters along the same corridor, not every
        # pair — avoids an O(n^2) fully-connected clique per line for long
        # transmission corridors with many stations on them
        #
        # strict=False is deliberate here, not an oversight: this zips a
        # list against itself offset by one (cluster_ids[:-1] vs [1:]) to
        # get consecutive pairs, so the two sides are ALWAYS exactly one
        # element apart by construction — strict=True would make this
        # raise on every single call.
        for a, b in zip(cluster_ids[:-1], cluster_ids[1:], strict=False):
            if a == b:
                continue
            graph.add_edge(a, b, edge_type="physical", connection_detail=category)
            edges.append(PhysicalEdge(source_cluster_id=a, target_cluster_id=b, connection_detail=category))

    logger.info("Physical graph: %d nodes, %d edges", graph.number_of_nodes(), len(edges))
    return graph, edges


def compute_centrality(graph: nx.Graph) -> dict[int, float]:
    """Combined betweenness + degree centrality, normalized to [0,1] and
    averaged. Betweenness alone over-rewards long, sparse transmission
    corridors; degree alone over-rewards dense local hubs. Averaging both
    is a deliberately simple heuristic — see docs/ROADMAP.md for the GNN
    upgrade path that would learn this weighting instead of hand-setting it.
    """
    if graph.number_of_nodes() == 0:
        return {}
    betweenness = nx.betweenness_centrality(graph)
    degree = nx.degree_centrality(graph)
    return {node: round((betweenness.get(node, 0) + degree.get(node, 0)) / 2, 4) for node in graph.nodes}
