# """
# backend/graph_builder/graph_constructor.py

# Constructs a heterogeneous, dynamic transaction graph from PaySim data.

# Graph Schema:
#   NODE TYPES:
#     - "account"     : financial accounts (nameOrig / nameDest)
#     - "transaction" : individual transactions (unique tx ID)
#     - "merchant"    : merchant accounts (nameDest starting with 'M')

#   EDGE TYPES:
#     - account → transaction   : "initiates"   (sender places transaction)
#     - transaction → account   : "received_by" (transaction reaches receiver)
#     - account → account       : "transfers_to" (aggregated flow edge)

#   NODE ATTRIBUTES:
#     - account nodes : balance, fraud_flag, degree, risk_score
#     - tx nodes      : amount, type, step, isFraud

# The graph is built incrementally (temporal sliding window support).
# """

# import networkx as nx
# import pandas as pd
# import numpy as np
# import pickle
# import logging
# from typing import Dict, List, Optional, Tuple
# from pathlib import Path

# logger = logging.getLogger(__name__)


# class TransactionGraphBuilder:
#     """
#     Builds and maintains a heterogeneous directed multigraph from
#     PaySim transaction records.
#     """

#     def __init__(self):
#         # MultiDiGraph allows multiple edges between same node pair
#         self.G = nx.MultiDiGraph()
#         self._tx_counter = 0
#         self._node_metadata: Dict[str, dict] = {}

#     # ──────────────────────────────────────────────────────────────────
#     # Core build method
#     # ──────────────────────────────────────────────────────────────────

#     def build_from_dataframe(
#         self,
#         df: pd.DataFrame,
#         step_start: Optional[int] = None,
#         step_end: Optional[int] = None,
#         max_transactions: Optional[int] = None,
#     ) -> nx.MultiDiGraph:
#         """
#         Build the full graph from a DataFrame of transactions.

#         Args:
#             df:               Cleaned PaySim DataFrame (post feature engineering)
#             step_start:       Filter transactions from this step (temporal window)
#             step_end:         Filter transactions to this step
#             max_transactions: Cap transactions for memory management

#         Returns:
#             nx.MultiDiGraph with typed nodes and edges
#         """
#         # Temporal filtering
#         if step_start is not None:
#             df = df[df["step"] >= step_start]
#         if step_end is not None:
#             df = df[df["step"] <= step_end]
#         if max_transactions is not None:
#             df = df.head(max_transactions)

#         logger.info(f"Building graph from {len(df):,} transactions...")

#         for _, row in df.iterrows():
#             self._add_transaction(row)

#         self._compute_graph_statistics()

#         logger.info(
#             f"Graph built: {self.G.number_of_nodes():,} nodes | "
#             f"{self.G.number_of_edges():,} edges"
#         )
#         return self.G

#     # ──────────────────────────────────────────────────────────────────
#     # Transaction → Graph mapping
#     # ──────────────────────────────────────────────────────────────────

#     def _add_transaction(self, row: pd.Series):
#         """
#         Map a single PaySim transaction row into graph nodes + edges.

#         Pattern:
#           [account_orig] --initiates--> [transaction_node] --received_by--> [account_dest]

#         This tripartite pattern preserves transaction-level metadata while
#         also capturing the account-to-account flow.
#         """
#         tx_id = f"tx_{self._tx_counter}"
#         self._tx_counter += 1

#         orig_id = f"acc_{row['nameOrig']}"
#         dest_id = f"acc_{row['nameDest']}"

#         # Detect merchant nodes
#         dest_type = "merchant" if row.get("dest_is_merchant", False) else "account"

#         # ── Add / update account nodes ──
#         self._upsert_account_node(orig_id, row, is_origin=True)
#         self._upsert_account_node(dest_id, row, is_origin=False,
#                                    node_type=dest_type)

#         # ── Add transaction node ──
#         self.G.add_node(
#             tx_id,
#             node_type="transaction",
#             amount=float(row["amount"]),
#             amount_log=float(row.get("amount_log", np.log1p(row["amount"]))),
#             tx_type=str(row["type"]),
#             type_encoded=int(row.get("type_encoded", -1)),
#             step=int(row["step"]),
#             hour=int(row.get("hour_of_day", row["step"] % 24)),
#             day=int(row.get("day_of_sim", row["step"] // 24)),
#             is_fraud=int(row["isFraud"]),
#             is_flagged=int(row["isFlaggedFraud"]),
#             is_round=int(row.get("is_round_amount", 0)),
#             orig_zeroed=int(row.get("orig_zeroed_out", 0)),
#         )

#         # ── Add directed edges ──
#         self.G.add_edge(
#             orig_id, tx_id,
#             edge_type="initiates",
#             weight=float(row["amount"]),
#             step=int(row["step"]),
#         )
#         self.G.add_edge(
#             tx_id, dest_id,
#             edge_type="received_by",
#             weight=float(row["amount"]),
#             step=int(row["step"]),
#         )

#         # ── Also add direct account→account edge (aggregated view) ──
#         if self.G.has_edge(orig_id, dest_id):
#             # Accumulate weight on existing edge
#             for key, edge_data in self.G[orig_id][dest_id].items():
#                 if edge_data.get("edge_type") == "transfers_to":
#                     edge_data["weight"] += float(row["amount"])
#                     edge_data["tx_count"] += 1
#                     break
#         else:
#             self.G.add_edge(
#                 orig_id, dest_id,
#                 edge_type="transfers_to",
#                 weight=float(row["amount"]),
#                 tx_count=1,
#                 step=int(row["step"]),
#             )

#     def _upsert_account_node(
#         self,
#         node_id: str,
#         row: pd.Series,
#         is_origin: bool,
#         node_type: str = "account"
#     ):
#         """Add account node or update its fraud flag."""
#         if node_id not in self.G:
#             self.G.add_node(
#                 node_id,
#                 node_type=node_type,
#                 is_fraud=int(row["isFraud"]),
#                 tx_count=1,
#                 total_sent=float(row["amount"]) if is_origin else 0.0,
#                 total_received=0.0 if is_origin else float(row["amount"]),
#                 balance=float(
#                     row["newbalanceOrig"] if is_origin else row["newbalanceDest"]
#                 ),
#             )
#         else:
#             # Update existing node
#             node = self.G.nodes[node_id]
#             node["tx_count"] += 1
#             if row["isFraud"] == 1:
#                 node["is_fraud"] = 1   # sticky fraud flag
#             if is_origin:
#                 node["total_sent"] += float(row["amount"])
#                 node["balance"] = float(row["newbalanceOrig"])
#             else:
#                 node["total_received"] += float(row["amount"])
#                 node["balance"] = float(row["newbalanceDest"])

#     # ──────────────────────────────────────────────────────────────────
#     # Graph analytics
#     # ──────────────────────────────────────────────────────────────────

#     def _compute_graph_statistics(self):
#         """
#         Compute and attach degree-based statistics to each node.
#         These features augment embeddings.
#         """
#         in_deg = dict(self.G.in_degree())
#         out_deg = dict(self.G.out_degree())

#         for node in self.G.nodes():
#             self.G.nodes[node]["in_degree"] = in_deg.get(node, 0)
#             self.G.nodes[node]["out_degree"] = out_deg.get(node, 0)
#             self.G.nodes[node]["total_degree"] = (
#                 in_deg.get(node, 0) + out_deg.get(node, 0)
#             )

#     def get_subgraph_by_node_type(self, node_type: str) -> nx.MultiDiGraph:
#         """Extract subgraph containing only nodes of a given type."""
#         nodes = [n for n, d in self.G.nodes(data=True)
#                  if d.get("node_type") == node_type]
#         return self.G.subgraph(nodes).copy()

#     def get_fraud_subgraph(self) -> nx.MultiDiGraph:
#         """Extract subgraph of known fraud nodes for analysis."""
#         fraud_nodes = [n for n, d in self.G.nodes(data=True)
#                        if d.get("is_fraud", 0) == 1]
#         return self.G.subgraph(fraud_nodes).copy()

#     def get_summary(self) -> dict:
#         """Return graph summary statistics."""
#         node_types = {}
#         fraud_nodes = 0
#         for n, d in self.G.nodes(data=True):
#             t = d.get("node_type", "unknown")
#             node_types[t] = node_types.get(t, 0) + 1
#             if d.get("is_fraud", 0):
#                 fraud_nodes += 1

#         edge_types = {}
#         for u, v, d in self.G.edges(data=True):
#             t = d.get("edge_type", "unknown")
#             edge_types[t] = edge_types.get(t, 0) + 1

#         return {
#             "total_nodes": self.G.number_of_nodes(),
#             "total_edges": self.G.number_of_edges(),
#             "node_types": node_types,
#             "edge_types": edge_types,
#             "fraud_nodes": fraud_nodes,
#             "is_connected": nx.is_weakly_connected(self.G),
#             "avg_degree": sum(dict(self.G.degree()).values()) / max(self.G.number_of_nodes(), 1),
#         }

#     # ──────────────────────────────────────────────────────────────────
#     # Persistence
#     # ──────────────────────────────────────────────────────────────────

#     def save(self, path: str):
#         """Serialize graph to pickle."""
#         with open(path, "wb") as f:
#             pickle.dump(self.G, f, protocol=pickle.HIGHEST_PROTOCOL)
#         logger.info(f"Graph saved to {path}")

#     def load(self, path: str) -> nx.MultiDiGraph:
#         """Load serialized graph."""
#         with open(path, "rb") as f:
#             self.G = pickle.load(f)
#         logger.info(f"Graph loaded from {path} | "
#                     f"{self.G.number_of_nodes():,} nodes")
#         return self.G


# class DynamicGraphUpdater:
#     """
#     Supports streaming updates to an existing graph.
#     New transactions are ingested one-by-one or in micro-batches,
#     simulating a real-time transaction environment.
#     """

#     def __init__(self, builder: TransactionGraphBuilder):
#         self.builder = builder
#         self.update_count = 0
#         self.update_log: List[dict] = []

#     def ingest_transaction(self, tx: dict) -> Tuple[List[str], List[str]]:
#         """
#         Add a single streaming transaction to the live graph.

#         Args:
#             tx: dict with keys matching PaySim row fields

#         Returns:
#             (new_nodes, new_edges) - lists of newly added identifiers
#         """
#         row = pd.Series(tx)
#         before_nodes = set(self.builder.G.nodes())
#         before_edges = self.builder.G.number_of_edges()

#         self.builder._add_transaction(row)

#         after_nodes = set(self.builder.G.nodes())
#         new_nodes = list(after_nodes - before_nodes)
#         new_edges = self.builder.G.number_of_edges() - before_edges

#         self.update_count += 1
#         self.update_log.append({
#             "update_id": self.update_count,
#             "tx_id": f"tx_{self.builder._tx_counter - 1}",
#             "new_nodes": len(new_nodes),
#             "new_edges": new_edges,
#         })

#         return new_nodes, [f"+{new_edges} edges"]

#     def ingest_batch(self, transactions: List[dict]) -> dict:
#         """Ingest a batch of streaming transactions."""
#         total_new_nodes = []
#         total_new_edges = 0
#         for tx in transactions:
#             nn, ne = self.ingest_transaction(tx)
#             total_new_nodes.extend(nn)
#             total_new_edges += 1

#         return {
#             "batch_size": len(transactions),
#             "new_nodes": len(total_new_nodes),
#             "new_edges": total_new_edges,
#             "total_nodes": self.builder.G.number_of_nodes(),
#             "total_edges": self.builder.G.number_of_edges(),
#         }
"""
backend/graph_builder/graph_constructor.py

Constructs a heterogeneous, dynamic transaction graph from PaySim data.

FIX LOG:
  [BUG-5]  FIXED fraud label propagation. Previously, destination account
           nodes were tagged is_fraud=1 if the transaction's isFraud=1.
           In PaySim, isFraud labels the ORIGINATOR, not the destination.
           Destination accounts now receive is_fraud_dest=1 (mule flag)
           to distinguish from is_fraud (initiator of fraud).
           This prevents true_label contamination in evaluate_against_labels.

  [BUG-6]  FIXED: node_type not updated on re-encounter.
           If a node appears first as an account then as a merchant,
           we now upgrade the type to merchant (more specific wins).

  [BUG-7]  FIXED: account→account edge accumulation bug.
           G.has_edge(orig_id, dest_id) returns True for ANY edge between
           the pair (including tx-intermediate edges). We now use a dedicated
           lookup via edge key tracking to safely find/create transfers_to edges.
"""

import networkx as nx
import pandas as pd
import numpy as np
import pickle
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class TransactionGraphBuilder:
    """
    Builds and maintains a heterogeneous directed multigraph from
    PaySim transaction records.
    """

    def __init__(self):
        self.G = nx.MultiDiGraph()
        self._tx_counter = 0
        # [BUG-7] Track which edge key is the transfers_to edge per pair
        self._transfers_to_keys: Dict[Tuple[str, str], int] = {}

    def build_from_dataframe(
        self,
        df: pd.DataFrame,
        step_start: Optional[int] = None,
        step_end: Optional[int] = None,
        max_transactions: Optional[int] = None,
    ) -> nx.MultiDiGraph:
        """Build the full graph from a DataFrame of transactions."""
        if step_start is not None:
            df = df[df["step"] >= step_start]
        if step_end is not None:
            df = df[df["step"] <= step_end]
        if max_transactions is not None:
            df = df.head(max_transactions)

        logger.info(f"Building graph from {len(df):,} transactions...")

        for _, row in df.iterrows():
            self._add_transaction(row)

        self._compute_graph_statistics()

        logger.info(
            f"Graph built: {self.G.number_of_nodes():,} nodes | "
            f"{self.G.number_of_edges():,} edges"
        )
        return self.G

    def _add_transaction(self, row: pd.Series):
        """
        Map a single PaySim row into graph nodes + edges.

        Pattern:
          [acc_orig] --initiates--> [tx_N] --received_by--> [acc_dest]
        Plus aggregated:
          [acc_orig] --transfers_to--> [acc_dest]

        NOTE on fraud labeling (PaySim semantics):
          isFraud=1 means acc_orig INITIATED fraud.
          acc_dest is a mule/merchant — tagged is_fraud_dest, not is_fraud.
        """
        tx_id = f"tx_{self._tx_counter}"
        self._tx_counter += 1

        orig_id = f"acc_{row['nameOrig']}"
        dest_id = f"acc_{row['nameDest']}"
        dest_type = "merchant" if row.get("dest_is_merchant", False) else "account"

        # [BUG-5] FIX: only tag ORIGINATOR with is_fraud
        self._upsert_account_node(orig_id, row, is_origin=True, node_type="account")
        self._upsert_account_node(dest_id, row, is_origin=False, node_type=dest_type)

        # Transaction node
        self.G.add_node(
            tx_id,
            node_type="transaction",
            amount=float(row["amount"]),
            amount_log=float(row.get("amount_log", np.log1p(row["amount"]))),
            tx_type=str(row["type"]),
            type_encoded=int(row.get("type_encoded", -1)),
            step=int(row["step"]),
            hour=int(row.get("hour_of_day", row["step"] % 24)),
            day=int(row.get("day_of_sim", row["step"] // 24)),
            is_fraud=int(row["isFraud"]),          # ground truth on TX node
            is_flagged=int(row["isFlaggedFraud"]),
            is_round=int(row.get("is_round_amount", 0)),
            orig_zeroed=int(row.get("orig_zeroed_out", 0)),
        )

        self.G.add_edge(orig_id, tx_id, edge_type="initiates",
                        weight=float(row["amount"]), step=int(row["step"]))
        self.G.add_edge(tx_id, dest_id, edge_type="received_by",
                        weight=float(row["amount"]), step=int(row["step"]))

        # [BUG-7] FIX: use dedicated key tracking for transfers_to edges
        pair = (orig_id, dest_id)
        if pair in self._transfers_to_keys:
            # Update existing transfers_to edge directly by key
            key = self._transfers_to_keys[pair]
            self.G[orig_id][dest_id][key]["weight"] += float(row["amount"])
            self.G[orig_id][dest_id][key]["tx_count"] += 1
        else:
            # Add new transfers_to edge and record its key
            key = self.G.add_edge(
                orig_id, dest_id,
                edge_type="transfers_to",
                weight=float(row["amount"]),
                tx_count=1,
                step=int(row["step"]),
            )
            self._transfers_to_keys[pair] = key

    def _upsert_account_node(
        self,
        node_id: str,
        row: pd.Series,
        is_origin: bool,
        node_type: str = "account",
    ):
        """
        Add account node or update its attributes.

        [BUG-5] FIX: is_fraud only set on ORIGIN account (fraud initiator).
                     Destination accounts receive is_fraud_dest flag instead.
        [BUG-6] FIX: merchant type wins if encountered after account type.
        """
        is_fraud_tx = int(row["isFraud"])

        if node_id not in self.G:
            self.G.add_node(
                node_id,
                node_type=node_type,
                # [BUG-5] Only mark originator as fraudulent
                is_fraud=is_fraud_tx if is_origin else 0,
                is_fraud_dest=0 if is_origin else is_fraud_tx,
                tx_count=1,
                total_sent=float(row["amount"]) if is_origin else 0.0,
                total_received=0.0 if is_origin else float(row["amount"]),
                balance=float(
                    row["newbalanceOrig"] if is_origin else row["newbalanceDest"]
                ),
            )
        else:
            node = self.G.nodes[node_id]
            node["tx_count"] += 1

            # [BUG-6] Upgrade type if merchant (more specific than account)
            if node_type == "merchant" and node.get("node_type") == "account":
                node["node_type"] = "merchant"

            # [BUG-5] Sticky fraud flag — only for origin account
            if is_origin and is_fraud_tx == 1:
                node["is_fraud"] = 1
            elif not is_origin and is_fraud_tx == 1:
                node["is_fraud_dest"] = 1

            if is_origin:
                node["total_sent"] += float(row["amount"])
                node["balance"] = float(row["newbalanceOrig"])
            else:
                node["total_received"] += float(row["amount"])
                node["balance"] = float(row["newbalanceDest"])

    def _compute_graph_statistics(self):
        """Compute and attach degree-based statistics to each node."""
        in_deg = dict(self.G.in_degree())
        out_deg = dict(self.G.out_degree())

        for node in self.G.nodes():
            self.G.nodes[node]["in_degree"] = in_deg.get(node, 0)
            self.G.nodes[node]["out_degree"] = out_deg.get(node, 0)
            self.G.nodes[node]["total_degree"] = (
                in_deg.get(node, 0) + out_deg.get(node, 0)
            )

    def get_subgraph_by_node_type(self, node_type: str) -> nx.MultiDiGraph:
        """Extract subgraph containing only nodes of a given type."""
        nodes = [n for n, d in self.G.nodes(data=True)
                 if d.get("node_type") == node_type]
        return self.G.subgraph(nodes).copy()

    def get_fraud_subgraph(self) -> nx.MultiDiGraph:
        """
        Extract subgraph of known fraud ORIGINATOR nodes.
        Uses is_fraud flag (set only on origin accounts) for clean ground truth.
        """
        fraud_nodes = [n for n, d in self.G.nodes(data=True)
                       if d.get("is_fraud", 0) == 1]
        return self.G.subgraph(fraud_nodes).copy()

    def get_summary(self) -> dict:
        """Return graph summary statistics."""
        node_types = {}
        fraud_nodes = 0
        for n, d in self.G.nodes(data=True):
            t = d.get("node_type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1
            if d.get("is_fraud", 0):
                fraud_nodes += 1

        edge_types = {}
        for u, v, d in self.G.edges(data=True):
            t = d.get("edge_type", "unknown")
            edge_types[t] = edge_types.get(t, 0) + 1

        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_types": node_types,
            "edge_types": edge_types,
            "fraud_nodes": fraud_nodes,
            "is_connected": nx.is_weakly_connected(self.G),
            "avg_degree": (
                sum(dict(self.G.degree()).values()) /
                max(self.G.number_of_nodes(), 1)
            ),
        }

    def save(self, path: str):
        """Serialize graph to pickle."""
        with open(path, "wb") as f:
            pickle.dump(self.G, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"Graph saved to {path}")

    def load(self, path: str) -> nx.MultiDiGraph:
        """Load serialized graph."""
        with open(path, "rb") as f:
            self.G = pickle.load(f)
        logger.info(f"Graph loaded from {path} | "
                    f"{self.G.number_of_nodes():,} nodes")
        return self.G


class DynamicGraphUpdater:
    """
    Supports streaming updates to an existing graph.
    """

    def __init__(self, builder: TransactionGraphBuilder):
        self.builder = builder
        self.update_count = 0

    def ingest_transaction(self, tx: dict) -> Tuple[List[str], List[str]]:
        """Add a single streaming transaction to the live graph."""
        row = pd.Series(tx)
        before_nodes = set(self.builder.G.nodes())
        before_edges = self.builder.G.number_of_edges()
        self.builder._add_transaction(row)
        after_nodes = set(self.builder.G.nodes())
        new_nodes = list(after_nodes - before_nodes)
        new_edges = self.builder.G.number_of_edges() - before_edges
        self.update_count += 1
        return new_nodes, [f"+{new_edges} edges"]

    def ingest_batch(self, transactions: List[dict]) -> dict:
        """Ingest a batch of streaming transactions."""
        total_new_nodes = []
        total_new_edges = 0
        for tx in transactions:
            nn, ne = self.ingest_transaction(tx)
            total_new_nodes.extend(nn)
            total_new_edges += 1
        return {
            "batch_size": len(transactions),
            "new_nodes": len(total_new_nodes),
            "new_edges": total_new_edges,
            "total_nodes": self.builder.G.number_of_nodes(),
            "total_edges": self.builder.G.number_of_edges(),
        }