"""
STRETCH GOAL — NOT part of the shipped MVP. Read docs/ROADMAP.md before
starting this.

The centrality-based risk contribution in app/graph/build_graph.py is a
hand-tuned heuristic: "more connected = more important". A trained GNN
could instead learn "if node X fails, what's P(node Y fails within
24-48h)?" directly from the graph topology — this is the same idea used in
power-grid cascading-failure research, transplanted to a satellite-
observed thermal-event graph instead of a physics-modeled electrical one.

Why this is a stretch goal and not core:
  1. Power-grid cascade GNNs train on simulated outage data because the
     underlying physics (power flow equations) are known and can generate
     unlimited labeled examples. A satellite thermal-event graph has no
     equivalent physics simulator — you'd need either (a) enough REAL
     historical cascading incidents to learn from, which are rare by
     definition, or (b) a synthetic propagation simulator (simple
     epidemic/percolation model over the real graph) whose assumptions
     you'd have to defend to judges as a stand-in for ground truth.
  2. Without (a) or (b) done carefully, a "cascade GNN" is just an
     unvalidated model wearing a more impressive architecture than the
     centrality heuristic it's replacing — worse, not better.

If you do pursue it (recommended sequence, not a copy-paste implementation):
  1. Generate synthetic cascades: pick a percolation or SIR-style model,
     run it thousands of times over the REAL physical+wind graph from
     app/graph/build_graph.py + app/graph/wind_edges.py, varying the
     seed node and propagation probability.
  2. Train a small message-passing GNN (2-3 GraphSAGE or GCN layers is
     plenty at this graph size) to predict, per node, P(activated within
     48h | seed node activated), using the synthetic runs as supervision.
  3. Validate against however many REAL correlated-incident pairs you can
     find in FIRMS history (Step 6's cross-graph correlation logic can
     mine these) — treat this as a sanity check, not a proper test set;
     say so explicitly in the judging deck.
  4. Keep the centrality score as the default `centrality_score` on
     DiscoveredCluster and add the GNN output as a SEPARATE field
     (e.g. `cascade_probability`) rather than replacing it — that way a
     GNN that doesn't finish in time blocks nothing.

Nothing below is a working implementation — it's the scaffold + honest
docstring for whoever picks this up.
"""
from __future__ import annotations

import logging

import networkx as nx

logger = logging.getLogger(__name__)


def simulate_synthetic_cascades(graph: nx.Graph, n_runs: int = 2000, propagation_prob: float = 0.15) -> list[dict]:
    """TODO: implement a percolation/SIR-style simulation over `graph`.
    Each run should record which nodes activated within N hops of a random
    seed node, at what propagation probability. Return one dict per run:
    {"seed": node_id, "activated": set(node_ids), "propagation_prob": p}.
    """
    raise NotImplementedError("Stretch goal — see module docstring for the recommended sequence")


def train_cascade_gnn(graph: nx.Graph, synthetic_runs: list[dict]):
    """TODO: build a small PyTorch Geometric (or DGL) message-passing model
    and train it on the synthetic runs. Not started — deliberately left
    for whoever has bandwidth after the core MVP (Phases 0-2) ships."""
    raise NotImplementedError("Stretch goal — see module docstring for the recommended sequence")
