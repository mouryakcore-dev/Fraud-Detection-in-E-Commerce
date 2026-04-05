# """
# backend/fraud_clusters/cluster_detector.py

# Fraud Ring / Coordinated Fraud Cluster Detection

# Approach:
#   1. Run Louvain community detection on the transaction graph
#   2. Compute per-community fraud statistics using anomaly scores
#   3. Flag communities with high anomaly concentration as fraud rings
#   4. Extract and analyze suspicious subgraphs

# A "fraud ring" typically involves:
#   - Multiple accounts sharing devices or addresses
#   - Circular money flows
#   - Coordinated burst transactions at similar time steps
#   - A high ratio of anomalous nodes in the same community
# """

# import networkx as nx
# import numpy as np
# import pandas as pd
# import logging
# from typing import Dict, List, Optional, Tuple, Set
# from collections import defaultdict

# logger = logging.getLogger(__name__)

# # Try to import community detection library
# try:
#     import community as community_louvain
#     LOUVAIN_AVAILABLE = True
# except ImportError:
#     LOUVAIN_AVAILABLE = False
#     logger.warning("python-louvain not installed. Using fallback clustering.")


# class FraudClusterDetector:
#     """
#     Detects coordinated fraud clusters using community detection
#     on the transaction graph combined with anomaly scores.
#     """

#     def __init__(
#         self,
#         min_cluster_size: int = 3,
#         fraud_ratio_threshold: float = 0.4,
#         louvain_resolution: float = 1.0,
#     ):
#         self.min_cluster_size = min_cluster_size
#         self.fraud_ratio_threshold = fraud_ratio_threshold
#         self.louvain_resolution = louvain_resolution

#         # Results
#         self.communities: Dict[int, List[str]] = {}        # community_id → nodes
#         self.node_community: Dict[str, int] = {}           # node → community_id
#         self.fraud_clusters: List[Dict] = []               # flagged clusters
#         self.cluster_stats: Optional[pd.DataFrame] = None

#     # ──────────────────────────────────────────────────────────────────
#     # Community Detection
#     # ──────────────────────────────────────────────────────────────────

#     def detect_communities(
#         self,
#         G: nx.MultiDiGraph,
#         fraud_scores: Optional[Dict[str, float]] = None,
#     ) -> Dict[int, List[str]]:
#         """
#         Detect communities in the transaction graph.

#         Args:
#             G:             The transaction heterogeneous graph
#             fraud_scores:  {node_id: score} mapping from anomaly detector

#         Returns:
#             communities: dict mapping community_id → list of node IDs
#         """
#         logger.info("Running community detection...")

#         # Convert to undirected for community detection
#         undirected = self._to_undirected_weighted(G)

#         if LOUVAIN_AVAILABLE:
#             partition = community_louvain.best_partition(
#                 undirected,
#                 resolution=self.louvain_resolution,
#                 randomize=False,
#             )
#         else:
#             partition = self._fallback_clustering(undirected)

#         # Organize into community → nodes mapping
#         communities: Dict[int, List[str]] = defaultdict(list)
#         for node, comm_id in partition.items():
#             communities[comm_id].append(node)

#         self.communities = dict(communities)
#         self.node_community = partition

#         logger.info(
#             f"Found {len(self.communities)} communities | "
#             f"Nodes: {len(self.node_community)}"
#         )

#         if fraud_scores:
#             self._analyze_fraud_clusters(G, fraud_scores)

#         return self.communities

#     def _to_undirected_weighted(self, G: nx.MultiDiGraph) -> nx.Graph:
#         """Convert to simple undirected weighted graph for Louvain."""
#         undirected = nx.Graph()
#         for u, v, data in G.edges(data=True):
#             w = data.get("weight", 1.0)
#             if undirected.has_edge(u, v):
#                 undirected[u][v]["weight"] += w
#             else:
#                 undirected.add_edge(u, v, weight=w)
#         return undirected

#     def _fallback_clustering(self, G: nx.Graph) -> Dict[str, int]:
#         """
#         Fallback: greedy modularity clustering if Louvain unavailable.
#         """
#         from networkx.algorithms.community import greedy_modularity_communities
#         communities_gen = greedy_modularity_communities(G)
#         partition = {}
#         for i, comm in enumerate(communities_gen):
#             for node in comm:
#                 partition[node] = i
#         return partition

#     # ──────────────────────────────────────────────────────────────────
#     # Fraud Ring Analysis
#     # ──────────────────────────────────────────────────────────────────

#     def _analyze_fraud_clusters(
#         self,
#         G: nx.MultiDiGraph,
#         fraud_scores: Dict[str, float],
#     ):
#         """
#         Analyze each community for fraud concentration.
#         Flag communities meeting fraud_ratio_threshold as suspicious.
#         """
#         cluster_records = []

#         for comm_id, nodes in self.communities.items():
#             if len(nodes) < self.min_cluster_size:
#                 continue

#             # Compute per-cluster stats
#             scores = [fraud_scores.get(n, 0.0) for n in nodes]
#             avg_score = float(np.mean(scores))
#             max_score = float(np.max(scores))
#             high_risk_nodes = [
#                 n for n, s in zip(nodes, scores) if s >= 0.65
#             ]
#             fraud_ratio = len(high_risk_nodes) / len(nodes)

#             # Internal transaction volume
#             subgraph = G.subgraph(nodes)
#             internal_tx = subgraph.number_of_edges()
#             total_volume = sum(
#                 d.get("weight", 0)
#                 for _, _, d in subgraph.edges(data=True)
#             )

#             record = {
#                 "community_id": comm_id,
#                 "size": len(nodes),
#                 "avg_fraud_score": avg_score,
#                 "max_fraud_score": max_score,
#                 "high_risk_count": len(high_risk_nodes),
#                 "fraud_ratio": fraud_ratio,
#                 "internal_transactions": internal_tx,
#                 "total_volume": float(total_volume),
#                 "is_fraud_ring": fraud_ratio >= self.fraud_ratio_threshold,
#                 "nodes": nodes,
#                 "high_risk_nodes": high_risk_nodes,
#             }
#             cluster_records.append(record)

#         self.cluster_stats = pd.DataFrame(cluster_records)

#         # Separate fraud rings
#         if not self.cluster_stats.empty:
#             fraud_ring_df = self.cluster_stats[
#                 self.cluster_stats["is_fraud_ring"]
#             ].sort_values("fraud_ratio", ascending=False)
#             self.fraud_clusters = fraud_ring_df.to_dict("records")

#         logger.info(
#             f"Fraud cluster analysis complete: "
#             f"{len(self.fraud_clusters)} fraud rings detected"
#         )

#     # ──────────────────────────────────────────────────────────────────
#     # Ring pattern analysis
#     # ──────────────────────────────────────────────────────────────────

#     def analyze_ring_patterns(
#         self,
#         G: nx.MultiDiGraph,
#         cluster: Dict,
#     ) -> Dict:
#         """
#         Deep analysis of a suspected fraud ring community.

#         Detects:
#         - Circular money flows (cycles)
#         - Shared hub accounts (high degree nodes)
#         - Temporal burst patterns
#         - Money mule indicators
#         """
#         nodes = cluster["nodes"]
#         subgraph = G.subgraph(nodes).copy()

#         patterns = {
#             "community_id": cluster["community_id"],
#             "size": cluster["size"],
#             "fraud_ratio": cluster["fraud_ratio"],
#         }

#         # Circular flow detection
#         try:
#             cycles = list(nx.simple_cycles(subgraph))
#             patterns["cycle_count"] = len(cycles)
#             patterns["has_cycles"] = len(cycles) > 0
#             patterns["avg_cycle_length"] = (
#                 float(np.mean([len(c) for c in cycles])) if cycles else 0.0
#             )
#         except Exception:
#             patterns["cycle_count"] = 0
#             patterns["has_cycles"] = False
#             patterns["avg_cycle_length"] = 0.0

#         # Hub accounts (potential orchestrators)
#         degree_dict = dict(subgraph.degree())
#         if degree_dict:
#             hub_threshold = np.percentile(list(degree_dict.values()), 90)
#             hub_nodes = [n for n, d in degree_dict.items() if d >= hub_threshold]
#             patterns["hub_nodes"] = hub_nodes[:5]
#             patterns["max_internal_degree"] = int(max(degree_dict.values()))
#         else:
#             patterns["hub_nodes"] = []
#             patterns["max_internal_degree"] = 0

#         # Temporal analysis - burst detection
#         edge_steps = [
#             d.get("step", 0)
#             for _, _, d in subgraph.edges(data=True)
#             if "step" in d
#         ]
#         if edge_steps:
#             patterns["time_span"] = int(max(edge_steps) - min(edge_steps))
#             patterns["transactions_per_step"] = (
#                 subgraph.number_of_edges() / max(patterns["time_span"], 1)
#             )
#             patterns["is_burst_pattern"] = patterns["transactions_per_step"] > 5
#         else:
#             patterns["time_span"] = 0
#             patterns["transactions_per_step"] = 0.0
#             patterns["is_burst_pattern"] = False

#         return patterns

#     def get_fraud_rings(self) -> List[Dict]:
#         """Return all detected fraud ring clusters."""
#         return self.fraud_clusters

#     def get_cluster_summary(self) -> pd.DataFrame:
#         """Return full cluster statistics DataFrame."""
#         return self.cluster_stats

#     def get_node_cluster(self, node_id: str) -> Optional[Dict]:
#         """Get cluster info for a specific node."""
#         comm_id = self.node_community.get(node_id)
#         if comm_id is None:
#             return None
#         nodes = self.communities.get(comm_id, [])
#         if self.cluster_stats is not None:
#             row = self.cluster_stats[
#                 self.cluster_stats["community_id"] == comm_id
#             ]
#             if not row.empty:
#                 return row.iloc[0].to_dict()
#         return {"community_id": comm_id, "size": len(nodes), "nodes": nodes}

#     def export_fraud_rings_for_visualization(self) -> List[Dict]:
#         """
#         Export fraud rings in format suitable for frontend graph visualization.
#         Returns list of {nodes: [...], edges: [...]} dicts.
#         """
#         result = []
#         for ring in self.fraud_clusters:
#             nodes_data = [
#                 {"id": n, "fraud_ratio": ring["fraud_ratio"]}
#                 for n in ring["nodes"][:50]  # limit for viz
#             ]
#             result.append({
#                 "community_id": ring["community_id"],
#                 "fraud_ratio": ring["fraud_ratio"],
#                 "size": ring["size"],
#                 "nodes": nodes_data,
#                 "risk_label": (
#                     "CRITICAL" if ring["fraud_ratio"] >= 0.7
#                     else "HIGH" if ring["fraud_ratio"] >= 0.5
#                     else "MEDIUM"
#                 ),
#             })
#         return result
"""
backend/fraud_clusters/cluster_detector.py

Fraud Ring / Coordinated Fraud Cluster Detection

FIX LOG:
  [BUG-10] FIXED: risk_label thresholds aligned with ANOMALY_CONFIG.
           Was: CRITICAL ≥ 0.7, HIGH ≥ 0.5, MEDIUM otherwise.
           Now: CRITICAL = 1.0 (all nodes fraud), HIGH ≥ 0.7, MEDIUM ≥ 0.4.
           This matches the fraud_ratio_threshold=0.4 and is academically defensible.

  [BUG-11] FIXED: Louvain version guard. best_partition() kwarg changed between
           versions. Now attempts randomize=False first, falls back to
           random_state=42 for newer versions.
"""

import networkx as nx
import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict

logger = logging.getLogger(__name__)

try:
    import community as community_louvain
    LOUVAIN_AVAILABLE = True
except ImportError:
    LOUVAIN_AVAILABLE = False
    logger.warning("python-louvain not installed. Using fallback greedy clustering.")


def _louvain_partition(G: nx.Graph, resolution: float) -> Dict:
    """
    [BUG-11] Version-safe wrapper for community_louvain.best_partition().
    Older python-louvain uses randomize=False.
    Newer versions (0.16+) use random_state=.
    """
    try:
        return community_louvain.best_partition(
            G, resolution=resolution, randomize=False
        )
    except TypeError:
        try:
            return community_louvain.best_partition(
                G, resolution=resolution, random_state=42
            )
        except TypeError:
            # Neither kwarg supported — run without reproducibility arg
            logger.warning(
                "Could not set Louvain random seed — results may not be reproducible."
            )
            return community_louvain.best_partition(G, resolution=resolution)


class FraudClusterDetector:
    """
    Detects coordinated fraud clusters using community detection
    on the transaction graph combined with anomaly scores.
    """

    def __init__(
        self,
        min_cluster_size: int = 3,
        fraud_ratio_threshold: float = 0.4,
        louvain_resolution: float = 1.0,
    ):
        self.min_cluster_size = min_cluster_size
        self.fraud_ratio_threshold = fraud_ratio_threshold
        self.louvain_resolution = louvain_resolution

        self.communities: Dict[int, List[str]] = {}
        self.node_community: Dict[str, int] = {}
        self.fraud_clusters: List[Dict] = []
        self.cluster_stats: Optional[pd.DataFrame] = None

    def detect_communities(
        self,
        G: nx.MultiDiGraph,
        fraud_scores: Optional[Dict[str, float]] = None,
    ) -> Dict[int, List[str]]:
        """
        Detect communities in the transaction graph.

        Args:
            G:             The transaction heterogeneous graph
            fraud_scores:  {node_id: score} mapping from anomaly detector

        Returns:
            communities: dict mapping community_id → list of node IDs
        """
        logger.info("Running community detection...")
        undirected = self._to_undirected_weighted(G)

        if LOUVAIN_AVAILABLE:
            # [BUG-11] Version-safe call
            partition = _louvain_partition(undirected, self.louvain_resolution)
        else:
            partition = self._fallback_clustering(undirected)

        communities: Dict[int, List[str]] = defaultdict(list)
        for node, comm_id in partition.items():
            communities[comm_id].append(node)

        self.communities = dict(communities)
        self.node_community = partition

        logger.info(
            f"Found {len(self.communities)} communities | "
            f"Nodes: {len(self.node_community)}"
        )

        if fraud_scores:
            self._analyze_fraud_clusters(G, fraud_scores)

        return self.communities

    def _to_undirected_weighted(self, G: nx.MultiDiGraph) -> nx.Graph:
        """Convert to simple undirected weighted graph for Louvain."""
        undirected = nx.Graph()
        for u, v, data in G.edges(data=True):
            w = data.get("weight", 1.0)
            if undirected.has_edge(u, v):
                undirected[u][v]["weight"] += w
            else:
                undirected.add_edge(u, v, weight=w)
        return undirected

    def _fallback_clustering(self, G: nx.Graph) -> Dict[str, int]:
        """Greedy modularity clustering fallback if Louvain unavailable."""
        from networkx.algorithms.community import greedy_modularity_communities
        communities_gen = greedy_modularity_communities(G)
        partition = {}
        for i, comm in enumerate(communities_gen):
            for node in comm:
                partition[node] = i
        return partition

    def _analyze_fraud_clusters(
        self,
        G: nx.MultiDiGraph,
        fraud_scores: Dict[str, float],
    ):
        """
        Analyze each community for fraud concentration.
        Flag communities meeting fraud_ratio_threshold as suspicious.
        """
        cluster_records = []

        for comm_id, nodes in self.communities.items():
            if len(nodes) < self.min_cluster_size:
                continue

            scores = [fraud_scores.get(n, 0.0) for n in nodes]
            avg_score = float(np.mean(scores))
            max_score = float(np.max(scores))
            high_risk_nodes = [n for n, s in zip(nodes, scores) if s >= 0.65]
            fraud_ratio = len(high_risk_nodes) / len(nodes)

            subgraph = G.subgraph(nodes)
            internal_tx = subgraph.number_of_edges()
            total_volume = sum(
                d.get("weight", 0)
                for _, _, d in subgraph.edges(data=True)
            )

            record = {
                "community_id": comm_id,
                "size": len(nodes),
                "avg_fraud_score": avg_score,
                "max_fraud_score": max_score,
                "high_risk_count": len(high_risk_nodes),
                "fraud_ratio": fraud_ratio,
                "internal_transactions": internal_tx,
                "total_volume": float(total_volume),
                "is_fraud_ring": fraud_ratio >= self.fraud_ratio_threshold,
                "nodes": nodes,
                "high_risk_nodes": high_risk_nodes,
            }
            cluster_records.append(record)

        self.cluster_stats = pd.DataFrame(cluster_records)

        if not self.cluster_stats.empty:
            fraud_ring_df = self.cluster_stats[
                self.cluster_stats["is_fraud_ring"]
            ].sort_values("fraud_ratio", ascending=False)
            self.fraud_clusters = fraud_ring_df.to_dict("records")

        logger.info(
            f"Fraud cluster analysis complete: "
            f"{len(self.fraud_clusters)} fraud rings detected"
        )

    def analyze_ring_patterns(self, G: nx.MultiDiGraph, cluster: Dict) -> Dict:
        """Deep analysis of a suspected fraud ring community."""
        nodes = cluster["nodes"]
        subgraph = G.subgraph(nodes).copy()

        patterns = {
            "community_id": cluster["community_id"],
            "size": cluster["size"],
            "fraud_ratio": cluster["fraud_ratio"],
        }

        try:
            cycles = list(nx.simple_cycles(subgraph))
            patterns["cycle_count"] = len(cycles)
            patterns["has_cycles"] = len(cycles) > 0
            patterns["avg_cycle_length"] = (
                float(np.mean([len(c) for c in cycles])) if cycles else 0.0
            )
        except Exception:
            patterns["cycle_count"] = 0
            patterns["has_cycles"] = False
            patterns["avg_cycle_length"] = 0.0

        degree_dict = dict(subgraph.degree())
        if degree_dict:
            hub_threshold = np.percentile(list(degree_dict.values()), 90)
            hub_nodes = [n for n, d in degree_dict.items() if d >= hub_threshold]
            patterns["hub_nodes"] = hub_nodes[:5]
            patterns["max_internal_degree"] = int(max(degree_dict.values()))
        else:
            patterns["hub_nodes"] = []
            patterns["max_internal_degree"] = 0

        edge_steps = [
            d.get("step", 0)
            for _, _, d in subgraph.edges(data=True)
            if "step" in d
        ]
        if edge_steps:
            patterns["time_span"] = int(max(edge_steps) - min(edge_steps))
            patterns["transactions_per_step"] = (
                subgraph.number_of_edges() / max(patterns["time_span"], 1)
            )
            patterns["is_burst_pattern"] = patterns["transactions_per_step"] > 5
        else:
            patterns["time_span"] = 0
            patterns["transactions_per_step"] = 0.0
            patterns["is_burst_pattern"] = False

        return patterns

    def get_fraud_rings(self) -> List[Dict]:
        """Return all detected fraud ring clusters."""
        return self.fraud_clusters

    def get_cluster_summary(self) -> pd.DataFrame:
        """Return full cluster statistics DataFrame."""
        return self.cluster_stats

    def get_node_cluster(self, node_id: str) -> Optional[Dict]:
        """Get cluster info for a specific node."""
        comm_id = self.node_community.get(node_id)
        if comm_id is None:
            return None
        nodes = self.communities.get(comm_id, [])
        if self.cluster_stats is not None:
            row = self.cluster_stats[
                self.cluster_stats["community_id"] == comm_id
            ]
            if not row.empty:
                return row.iloc[0].to_dict()
        return {"community_id": comm_id, "size": len(nodes), "nodes": nodes}

    def export_fraud_rings_for_visualization(self) -> List[Dict]:
        """
        Export fraud rings for frontend visualization.

        [BUG-10] FIXED: risk_label thresholds now aligned with config:
          CRITICAL = fraud_ratio == 1.0 (entire cluster is fraud)
          HIGH     = fraud_ratio >= 0.7
          MEDIUM   = fraud_ratio >= 0.4 (= fraud_ratio_threshold)
        """
        result = []
        for ring in self.fraud_clusters:
            fr = ring["fraud_ratio"]
            if fr >= 1.0:
                risk_label = "CRITICAL"
            elif fr >= 0.7:
                risk_label = "HIGH"
            else:
                risk_label = "MEDIUM"

            nodes_data = [
                {"id": n, "fraud_ratio": ring["fraud_ratio"]}
                for n in ring["nodes"][:50]
            ]
            result.append({
                "community_id": ring["community_id"],
                "fraud_ratio": round(fr, 4),
                "size": ring["size"],
                "nodes": nodes_data,
                "risk_label": risk_label,
                "avg_fraud_score": round(ring.get("avg_fraud_score", 0.0), 4),
                "max_fraud_score": round(ring.get("max_fraud_score", 0.0), 4),
                "internal_transactions": ring.get("internal_transactions", 0),
            })
        return result