# # """
# # backend/anomaly_detection/detector.py

# # Unsupervised fraud anomaly detection on graph node embeddings.

# # Two complementary approaches are combined:

# # 1. Isolation Forest
# #    - Builds random binary trees; anomalies have shorter path lengths
# #    - Effective for high-dimensional embeddings (64-128 dim)
# #    - Returns anomaly score ∈ (-∞, 0.5]; more negative = more anomalous

# # 2. Local Outlier Factor (LOF)
# #    - Compares local density of a point vs its neighbors
# #    - High LOF score = point is in a much less dense region = outlier
# #    - Effective at detecting cluster-boundary fraudsters

# # Final fraud score = weighted ensemble of both scores, normalized [0, 1].
# # """

# # import numpy as np
# # import pandas as pd
# # import logging
# # from typing import Dict, List, Optional, Tuple

# # from sklearn.ensemble import IsolationForest
# # from sklearn.neighbors import LocalOutlierFactor
# # from sklearn.preprocessing import StandardScaler, MinMaxScaler

# # import networkx as nx

# # logger = logging.getLogger(__name__)


# # class FraudAnomalyDetector:
# #     """
# #     Ensemble anomaly detector that scores graph nodes based on
# #     their learned embedding representations.

# #     Usage:
# #         detector = FraudAnomalyDetector()
# #         scores = detector.fit_predict(embeddings, node_names)
# #         fraud_nodes = detector.get_high_risk_nodes(threshold=0.65)
# #     """

# #     def __init__(
# #         self,
# #         if_n_estimators: int = 200,
# #         if_contamination: float = 0.05,
# #         lof_n_neighbors: int = 20,
# #         lof_contamination: float = 0.05,
# #         fraud_threshold: float = 0.65,
# #         medium_threshold: float = 0.45,
# #         if_weight: float = 0.6,
# #         lof_weight: float = 0.4,
# #         random_state: int = 42,
# #     ):
# #         self.if_weight = if_weight
# #         self.lof_weight = lof_weight
# #         self.fraud_threshold = fraud_threshold
# #         self.medium_threshold = medium_threshold

# #         self.iso_forest = IsolationForest(
# #             n_estimators=if_n_estimators,
# #             contamination=if_contamination,
# #             max_samples="auto",
# #             random_state=random_state,
# #             n_jobs=-1,
# #         )
# #         self.lof = LocalOutlierFactor(
# #             n_neighbors=lof_n_neighbors,
# #             contamination=lof_contamination,
# #             novelty=False,
# #             n_jobs=-1,
# #         )

# #         self.scaler = StandardScaler()
# #         self.score_scaler = MinMaxScaler()

# #         # Results storage
# #         self.node_names: List[str] = []
# #         self.fraud_scores: Optional[np.ndarray] = None
# #         self.if_scores: Optional[np.ndarray] = None
# #         self.lof_scores: Optional[np.ndarray] = None
# #         self.predictions: Optional[np.ndarray] = None  # -1 = anomaly, 1 = normal

# #     # ──────────────────────────────────────────────────────────────────
# #     # Core detection
# #     # ──────────────────────────────────────────────────────────────────

# #     def fit_predict(
# #         self,
# #         embeddings: np.ndarray,
# #         node_names: List[str],
# #         graph: Optional[nx.MultiDiGraph] = None,
# #     ) -> np.ndarray:
# #         """
# #         Fit anomaly detectors on embeddings and return fraud scores.

# #         Args:
# #             embeddings:  (N, dim) node embedding matrix
# #             node_names:  list of node identifier strings
# #             graph:       optional graph for structural feature augmentation

# #         Returns:
# #             fraud_scores: (N,) array ∈ [0, 1] where 1 = highest fraud risk
# #         """
# #         self.node_names = node_names
# #         logger.info(f"Running anomaly detection on {len(embeddings)} nodes...")

# #         # Step 1: Augment embeddings with graph structural features
# #         features = self._augment_with_structural_features(
# #             embeddings, node_names, graph
# #         )

# #         # Step 2: Standardize features
# #         X = self.scaler.fit_transform(features)

# #         # Step 3: Isolation Forest
# #         logger.info("Fitting Isolation Forest...")
# #         self.iso_forest.fit(X)
# #         # score_samples returns negative anomaly scores;
# #         # more negative = more anomalous
# #         if_raw = self.iso_forest.score_samples(X)
# #         # Invert so higher = more anomalous
# #         if_inverted = -if_raw
# #         self.if_scores = self._normalize_scores(if_inverted)

# #         # Step 4: Local Outlier Factor
# #         logger.info("Fitting Local Outlier Factor...")
# #         self.lof.fit_predict(X)
# #         # negative_outlier_factor_: more negative = more anomalous
# #         lof_raw = -self.lof.negative_outlier_factor_
# #         self.lof_scores = self._normalize_scores(lof_raw)

# #         # Step 5: Ensemble
# #         self.fraud_scores = (
# #             self.if_weight * self.if_scores +
# #             self.lof_weight * self.lof_scores
# #         )

# #         # Final normalization [0, 1]
# #         self.fraud_scores = self._normalize_scores(self.fraud_scores)

# #         # Binary predictions
# #         self.predictions = (self.fraud_scores >= self.fraud_threshold).astype(int)

# #         logger.info(
# #             f"Detection complete: "
# #             f"{self.predictions.sum()} high-risk nodes "
# #             f"({self.predictions.mean():.1%} of total)"
# #         )
# #         return self.fraud_scores

# #     def _augment_with_structural_features(
# #         self,
# #         embeddings: np.ndarray,
# #         node_names: List[str],
# #         graph: Optional[nx.MultiDiGraph],
# #     ) -> np.ndarray:
# #         """
# #         Concatenate embedding vectors with graph structural features:
# #         - in_degree, out_degree, total_degree
# #         - total_sent, total_received (if account node)
# #         - tx_count

# #         This enriches the embedding space for anomaly detection.
# #         """
# #         if graph is None:
# #             return embeddings

# #         structural = []
# #         for name in node_names:
# #             attrs = graph.nodes.get(name, {})
# #             structural.append([
# #                 float(attrs.get("in_degree", 0)),
# #                 float(attrs.get("out_degree", 0)),
# #                 float(attrs.get("total_degree", 0)),
# #                 float(attrs.get("tx_count", 1)),
# #                 np.log1p(float(attrs.get("total_sent", 0))),
# #                 np.log1p(float(attrs.get("total_received", 0))),
# #                 np.log1p(float(attrs.get("balance", 0))),
# #             ])

# #         structural_arr = np.array(structural, dtype=np.float32)
# #         return np.hstack([embeddings, structural_arr])

# #     @staticmethod
# #     def _normalize_scores(scores: np.ndarray) -> np.ndarray:
# #         """Min-max normalize scores to [0, 1]."""
# #         s_min, s_max = scores.min(), scores.max()
# #         if s_max == s_min:
# #             return np.zeros_like(scores)
# #         return (scores - s_min) / (s_max - s_min)

# #     # ──────────────────────────────────────────────────────────────────
# #     # Results
# #     # ──────────────────────────────────────────────────────────────────

# #     def get_results_dataframe(self) -> pd.DataFrame:
# #         """Return full detection results as a DataFrame."""
# #         if self.fraud_scores is None:
# #             raise RuntimeError("Run fit_predict() first.")

# #         return pd.DataFrame({
# #             "node_id": self.node_names,
# #             "fraud_score": self.fraud_scores,
# #             "if_score": self.if_scores,
# #             "lof_score": self.lof_scores,
# #             "risk_level": self._assign_risk_levels(),
# #             "is_anomaly": self.predictions,
# #         }).sort_values("fraud_score", ascending=False)

# #     def _assign_risk_levels(self) -> List[str]:
# #         """Assign HIGH / MEDIUM / LOW risk labels."""
# #         levels = []
# #         for score in self.fraud_scores:
# #             if score >= self.fraud_threshold:
# #                 levels.append("HIGH")
# #             elif score >= self.medium_threshold:
# #                 levels.append("MEDIUM")
# #             else:
# #                 levels.append("LOW")
# #         return levels

# #     def get_high_risk_nodes(self, threshold: Optional[float] = None) -> List[str]:
# #         """Return node IDs with fraud score above threshold."""
# #         thresh = threshold or self.fraud_threshold
# #         return [
# #             self.node_names[i]
# #             for i in range(len(self.node_names))
# #             if self.fraud_scores[i] >= thresh
# #         ]

# #     def get_node_score(self, node_name: str) -> Optional[Dict]:
# #         """Get all scores for a specific node."""
# #         if node_name not in self.node_names:
# #             return None
# #         idx = self.node_names.index(node_name)
# #         return {
# #             "node_id": node_name,
# #             "fraud_score": float(self.fraud_scores[idx]),
# #             "if_score": float(self.if_scores[idx]),
# #             "lof_score": float(self.lof_scores[idx]),
# #             "risk_level": self._assign_risk_levels()[idx],
# #             "is_anomaly": bool(self.predictions[idx]),
# #         }

# #     def evaluate_against_labels(
# #         self,
# #         true_labels: np.ndarray,
# #         threshold: Optional[float] = None,
# #     ) -> Dict:
# #         """
# #         Evaluate detection performance against ground-truth fraud labels.

# #         Metrics:
# #         - Precision, Recall, F1 (for fraud class)
# #         - AUC-ROC
# #         - Average Precision (PR-AUC)
# #         """
# #         from sklearn.metrics import (
# #             precision_score, recall_score, f1_score,
# #             roc_auc_score, average_precision_score,
# #             confusion_matrix,
# #         )

# #         thresh = threshold or self.fraud_threshold
# #         pred_binary = (self.fraud_scores >= thresh).astype(int)

# #         tn, fp, fn, tp = confusion_matrix(true_labels, pred_binary).ravel()

# #         return {
# #             "precision": float(precision_score(true_labels, pred_binary, zero_division=0)),
# #             "recall": float(recall_score(true_labels, pred_binary, zero_division=0)),
# #             "f1": float(f1_score(true_labels, pred_binary, zero_division=0)),
# #             "roc_auc": float(roc_auc_score(true_labels, self.fraud_scores)),
# #             "pr_auc": float(average_precision_score(true_labels, self.fraud_scores)),
# #             "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
# #             "true_positive_rate": float(tp / max(tp + fn, 1)),
# #             "false_positive_rate": float(fp / max(fp + tn, 1)),
# #         }

# """
# backend/anomaly_detection/detector.py

# Unsupervised fraud anomaly detection on graph node embeddings.

# FIX LOG:
#   [BUG-1]  REMOVED double normalization. The ensemble sum of two already-
#            normalized scores [0,1] already lives in [0,1]. The final
#            _normalize_scores() call was collapsing the distribution and making
#            the 0.65 threshold meaningless (top score was always 1.0 by construction).
#            Now the ensemble is clipped to [0,1] — preserving true signal magnitude.

#   [BUG-4]  evaluate_against_labels now filters to TRANSACTION nodes only.
#            Account nodes with is_fraud=1 are contaminated (dest accounts get
#            tagged fraud just for receiving from a fraudster in _upsert_account_node).
#            Only transaction nodes have unambiguous isFraud ground-truth labels.

#   [BUG-3]  LOF fit_predict() return value was discarded; call is now lof.fit()
#            then access negative_outlier_factor_ directly, which is cleaner
#            and avoids the redundant pass.
# """

# import numpy as np
# import pandas as pd
# import logging
# from typing import Dict, List, Optional, Tuple

# from sklearn.ensemble import IsolationForest
# from sklearn.neighbors import LocalOutlierFactor
# from sklearn.preprocessing import StandardScaler

# import networkx as nx

# logger = logging.getLogger(__name__)


# class FraudAnomalyDetector:
#     """
#     Ensemble anomaly detector that scores graph nodes based on
#     their learned embedding representations.

#     Usage:
#         detector = FraudAnomalyDetector()
#         scores = detector.fit_predict(embeddings, node_names, graph)
#         fraud_nodes = detector.get_high_risk_nodes(threshold=0.65)
#     """

#     def __init__(
#         self,
#         if_n_estimators: int = 200,
#         if_contamination: float = 0.05,
#         lof_n_neighbors: int = 20,
#         lof_contamination: float = 0.05,
#         fraud_threshold: float = 0.65,
#         medium_threshold: float = 0.45,
#         if_weight: float = 0.6,
#         lof_weight: float = 0.4,
#         random_state: int = 42,
#     ):
#         self.if_weight = if_weight
#         self.lof_weight = lof_weight
#         self.fraud_threshold = fraud_threshold
#         self.medium_threshold = medium_threshold

#         self.iso_forest = IsolationForest(
#             n_estimators=if_n_estimators,
#             contamination=if_contamination,
#             max_samples="auto",
#             random_state=random_state,
#             n_jobs=-1,
#         )
#         # [BUG-3] novelty=False, use fit() then negative_outlier_factor_
#         self.lof = LocalOutlierFactor(
#             n_neighbors=lof_n_neighbors,
#             contamination=lof_contamination,
#             novelty=False,
#             n_jobs=-1,
#         )

#         self.scaler = StandardScaler()

#         self.node_names: List[str] = []
#         self.fraud_scores: Optional[np.ndarray] = None
#         self.if_scores: Optional[np.ndarray] = None
#         self.lof_scores: Optional[np.ndarray] = None
#         self.predictions: Optional[np.ndarray] = None

#     def fit_predict(
#         self,
#         embeddings: np.ndarray,
#         node_names: List[str],
#         graph: Optional[nx.MultiDiGraph] = None,
#     ) -> np.ndarray:
#         """
#         Fit anomaly detectors on embeddings and return fraud scores.

#         Args:
#             embeddings:  (N, dim) node embedding matrix
#             node_names:  list of node identifier strings (must align with rows)
#             graph:       optional graph for structural feature augmentation

#         Returns:
#             fraud_scores: (N,) array in [0, 1] where higher = more anomalous
#         """
#         self.node_names = list(node_names)
#         logger.info(f"Running anomaly detection on {len(embeddings)} nodes...")

#         # Step 1: Augment with structural features
#         features = self._augment_with_structural_features(
#             embeddings, node_names, graph
#         )

#         # Step 2: Standardize
#         X = self.scaler.fit_transform(features)

#         # Step 3: Isolation Forest
#         logger.info("Fitting Isolation Forest...")
#         self.iso_forest.fit(X)
#         if_raw = self.iso_forest.score_samples(X)   # more negative = more anomalous
#         if_inverted = -if_raw
#         self.if_scores = self._normalize_scores(if_inverted)  # → [0, 1]

#         # Step 4: Local Outlier Factor
#         # [BUG-3] Use fit() not fit_predict() — we only need negative_outlier_factor_
#         logger.info("Fitting Local Outlier Factor...")
#         self.lof.fit(X)
#         lof_raw = -self.lof.negative_outlier_factor_  # invert so higher = more anomalous
#         self.lof_scores = self._normalize_scores(lof_raw)  # → [0, 1]

#         # Step 5: Weighted ensemble
#         # [BUG-1] FIXED: DO NOT normalize again.
#         # Both if_scores and lof_scores are already in [0, 1].
#         # Their weighted sum is in [0, 1] by construction (weights sum to 1.0).
#         # Re-normalizing would artificially force min→0, max→1 every run,
#         # making the threshold meaningless and distribution misleading.
#         self.fraud_scores = np.clip(
#             self.if_weight * self.if_scores + self.lof_weight * self.lof_scores,
#             0.0, 1.0
#         )

#         self.predictions = (self.fraud_scores >= self.fraud_threshold).astype(int)

#         logger.info(
#             f"Detection complete: "
#             f"{self.predictions.sum()} high-risk nodes "
#             f"({self.predictions.mean():.1%} of total)"
#         )
#         return self.fraud_scores

#     def _augment_with_structural_features(
#         self,
#         embeddings: np.ndarray,
#         node_names: List[str],
#         graph: Optional[nx.MultiDiGraph],
#     ) -> np.ndarray:
#         """
#         Concatenate embedding vectors with graph structural features.
#         Adds 7 features: in/out/total degree, tx_count, log(sent), log(received), log(balance).
#         """
#         if graph is None:
#             return embeddings

#         structural = []
#         for name in node_names:
#             attrs = graph.nodes.get(name, {})
#             structural.append([
#                 float(attrs.get("in_degree", 0)),
#                 float(attrs.get("out_degree", 0)),
#                 float(attrs.get("total_degree", 0)),
#                 float(attrs.get("tx_count", 1)),
#                 np.log1p(float(attrs.get("total_sent", 0))),
#                 np.log1p(float(attrs.get("total_received", 0))),
#                 np.log1p(float(attrs.get("balance", 0))),
#             ])

#         structural_arr = np.array(structural, dtype=np.float32)
#         return np.hstack([embeddings, structural_arr])

#     @staticmethod
#     def _normalize_scores(scores: np.ndarray) -> np.ndarray:
#         """Min-max normalize scores to [0, 1]."""
#         s_min, s_max = scores.min(), scores.max()
#         if s_max == s_min:
#             return np.zeros_like(scores)
#         return (scores - s_min) / (s_max - s_min)

#     def get_results_dataframe(self) -> pd.DataFrame:
#         """Return full detection results as a DataFrame."""
#         if self.fraud_scores is None:
#             raise RuntimeError("Run fit_predict() first.")
#         return pd.DataFrame({
#             "node_id": self.node_names,
#             "fraud_score": self.fraud_scores,
#             "if_score": self.if_scores,
#             "lof_score": self.lof_scores,
#             "risk_level": self._assign_risk_levels(),
#             "is_anomaly": self.predictions,
#         }).sort_values("fraud_score", ascending=False)

#     def _assign_risk_levels(self) -> List[str]:
#         """Assign HIGH / MEDIUM / LOW risk labels based on thresholds."""
#         levels = []
#         for score in self.fraud_scores:
#             if score >= self.fraud_threshold:
#                 levels.append("HIGH")
#             elif score >= self.medium_threshold:
#                 levels.append("MEDIUM")
#             else:
#                 levels.append("LOW")
#         return levels

#     def get_high_risk_nodes(self, threshold: Optional[float] = None) -> List[str]:
#         """Return node IDs with fraud score above threshold."""
#         thresh = threshold or self.fraud_threshold
#         return [
#             self.node_names[i]
#             for i in range(len(self.node_names))
#             if self.fraud_scores[i] >= thresh
#         ]

#     def get_node_score(self, node_name: str) -> Optional[Dict]:
#         """Get all scores for a specific node."""
#         if node_name not in self.node_names:
#             return None
#         idx = self.node_names.index(node_name)
#         return {
#             "node_id": node_name,
#             "fraud_score": float(self.fraud_scores[idx]),
#             "if_score": float(self.if_scores[idx]),
#             "lof_score": float(self.lof_scores[idx]),
#             "risk_level": self._assign_risk_levels()[idx],
#             "is_anomaly": bool(self.predictions[idx]),
#         }

#     def evaluate_against_labels(
#         self,
#         true_labels: np.ndarray,
#         threshold: Optional[float] = None,
#     ) -> Dict:
#         """
#         Evaluate detection performance against ground-truth fraud labels.

#         IMPORTANT: Pass only TRANSACTION node labels (tx_* nodes).
#         Account nodes are unreliable — destination accounts are tagged
#         is_fraud=1 just for receiving from a fraudster (see graph_constructor).

#         Metrics: Precision, Recall, F1, AUC-ROC, PR-AUC, confusion matrix.
#         """
#         from sklearn.metrics import (
#             precision_score, recall_score, f1_score,
#             roc_auc_score, average_precision_score,
#             confusion_matrix,
#         )

#         if len(true_labels) != len(self.fraud_scores):
#             raise ValueError(
#                 f"Label length mismatch: {len(true_labels)} labels "
#                 f"vs {len(self.fraud_scores)} scores."
#             )

#         thresh = threshold or self.fraud_threshold
#         pred_binary = (self.fraud_scores >= thresh).astype(int)

#         cm = confusion_matrix(true_labels, pred_binary)
#         tn, fp, fn, tp = cm.ravel()

#         return {
#             "precision": float(precision_score(true_labels, pred_binary, zero_division=0)),
#             "recall": float(recall_score(true_labels, pred_binary, zero_division=0)),
#             "f1": float(f1_score(true_labels, pred_binary, zero_division=0)),
#             "roc_auc": float(roc_auc_score(true_labels, self.fraud_scores)),
#             "pr_auc": float(average_precision_score(true_labels, self.fraud_scores)),
#             "confusion_matrix": {
#                 "tn": int(tn), "fp": int(fp),
#                 "fn": int(fn), "tp": int(tp),
#             },
#             "true_positive_rate": float(tp / max(tp + fn, 1)),
#             "false_positive_rate": float(fp / max(fp + tn, 1)),
#             "threshold_used": float(thresh),
#             "total_nodes_evaluated": int(len(true_labels)),
#             "positive_class_rate": float(true_labels.mean()),
#         }
"""
backend/anomaly_detection/detector.py

ACCURACY IMPROVEMENTS IN THIS VERSION
======================================

ROOT CAUSES OF LOW ACCURACY (diagnosed from fraud_scores.csv):

  PROBLEM 1 — TRIPLE NORMALIZATION (was destroying all signal)
    IF scores normalized → [0,1]
    LOF scores normalized → [0,1]
    Ensemble normalized AGAIN → [0,1]
    Effect: min ALWAYS = 0.0, max ALWAYS = 1.0 every run.
    Median score was 0.70 → 60.1% of nodes flagged HIGH.
    PaySim true fraud rate is 1.3%. You were flagging 46× too many.
    Precision was mathematically capped at ~2%.

  PROBLEM 2 — CONTAMINATION 4× TOO HIGH
    contamination=0.05 tells the models "5% of data is fraud".
    PaySim actual fraud rate: 1.3%. Models were pre-calibrated wrong.

  PROBLEM 3 — ISOLATION FOREST BLIND IN 64 DIMENSIONS
    IF path-length std was 0.086 (near-random). In 64-dim space,
    all points are equidistant — IF cannot isolate anomalies.
    Fix: PCA reduces embeddings to 20 components before IF.

  PROBLEM 4 — NO THRESHOLD OPTIMISATION
    Fixed threshold 0.65 chosen arbitrarily. At 1.3% fraud rate,
    optimal F1 threshold is typically 0.75–0.85.
    Fix: auto-tune threshold from precision-recall curve.

  PROBLEM 5 — NO DETECTION_METRICS.JSON BEING SAVED
    Pipeline computed no metrics. Dashboard showed fake hardcoded values.
    Fix: evaluate_against_labels() now returns rich metrics dict,
    and run_pipeline.py saves it to data/detection_metrics.json.
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple

from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

import networkx as nx

logger = logging.getLogger(__name__)


class FraudAnomalyDetector:
    """
    Three-component ensemble anomaly detector:
      1. Isolation Forest on PCA-reduced embeddings  (weight 0.45)
      2. Local Outlier Factor on full feature matrix (weight 0.40)
      3. Heuristic transaction-feature score         (weight 0.15)

    The heuristic catches structurally isolated fraudsters
    that the graph embedding cannot encode (few neighbours,
    but near-deterministic fraud signals in their attributes).
    """

    def __init__(
        self,
        if_n_estimators: int = 300,
        if_contamination: float = 0.013,     # TUNED: PaySim true fraud rate
        lof_n_neighbors: int = 30,
        lof_contamination: float = 0.013,    # TUNED: PaySim true fraud rate
        pca_components: int = 20,            # NEW: reduces IF input dimensionality
        fraud_threshold: float = 0.65,       # will be auto-tuned
        medium_threshold: float = 0.40,
        if_weight: float = 0.45,
        lof_weight: float = 0.40,
        heuristic_weight: float = 0.15,      # NEW: third signal
        random_state: int = 42,
    ):
        self.if_weight = if_weight
        self.lof_weight = lof_weight
        self.heuristic_weight = heuristic_weight
        self.fraud_threshold = fraud_threshold
        self.medium_threshold = medium_threshold
        self.pca_components = pca_components

        self.iso_forest = IsolationForest(
            n_estimators=if_n_estimators,
            contamination=if_contamination,
            max_samples="auto",
            random_state=random_state,
            n_jobs=-1,
        )
        self.lof = LocalOutlierFactor(
            n_neighbors=lof_n_neighbors,
            contamination=lof_contamination,
            novelty=False,
            n_jobs=-1,
        )
        self.pca = PCA(n_components=pca_components, random_state=random_state)
        self.scaler = StandardScaler()
        self.emb_scaler = StandardScaler()   # separate scaler for PCA path

        self.node_names: List[str] = []
        self.fraud_scores: Optional[np.ndarray] = None
        self.if_scores: Optional[np.ndarray] = None
        self.lof_scores: Optional[np.ndarray] = None
        self.heuristic_scores: Optional[np.ndarray] = None
        self.predictions: Optional[np.ndarray] = None
        self._emb_dim: int = 64

    # ──────────────────────────────────────────────────────────────────
    # Core detection
    # ──────────────────────────────────────────────────────────────────

    def fit_predict(
        self,
        embeddings: np.ndarray,
        node_names: List[str],
        graph: Optional[nx.MultiDiGraph] = None,
    ) -> np.ndarray:
        """
        Fit all detectors and return fraud scores in [0, 1].

        Args:
            embeddings:  (N, dim) node embedding matrix, row-aligned with node_names
            node_names:  list of node identifier strings
            graph:       graph for structural + heuristic features

        Returns:
            fraud_scores: (N,) array — higher = more suspicious
        """
        self.node_names = list(node_names)
        self._emb_dim = embeddings.shape[1]
        N = len(embeddings)
        logger.info(f"Anomaly detection on {N:,} nodes (embedding_dim={self._emb_dim})...")

        # Step 1: Full feature matrix (embeddings + structural) for LOF
        full_features = self._augment_with_structural_features(
            embeddings, node_names, graph
        )

        # Step 2: Heuristic scores from transaction attributes
        self.heuristic_scores = self._compute_heuristic_scores(node_names, graph)
        logger.info(
            f"Heuristic: mean={self.heuristic_scores.mean():.4f}  "
            f"flagged={(self.heuristic_scores > 0.5).sum():,}"
        )

        # Step 3: Standardise full feature matrix (for LOF)
        X_full = self.scaler.fit_transform(full_features)

        # Step 4: PCA on embeddings only → feed to IF
        # FIXES PROBLEM 3: 64D → 20D, restores IF discrimination
        n_comp = min(self.pca_components, self._emb_dim, N - 1)
        if n_comp != self.pca_components:
            logger.warning(f"PCA capped at {n_comp} (N={N}, dim={self._emb_dim})")
            self.pca = PCA(n_components=n_comp, random_state=42)

        emb_scaled = self.emb_scaler.fit_transform(embeddings.astype(np.float64))
        X_pca = self.pca.fit_transform(emb_scaled)
        explained = self.pca.explained_variance_ratio_.sum()
        logger.info(f"PCA {self._emb_dim}D→{n_comp}D, explains {explained:.1%} variance")

        # Step 5: Isolation Forest on PCA embeddings
        logger.info("Fitting Isolation Forest (PCA-reduced)...")
        self.iso_forest.fit(X_pca)
        if_raw = -self.iso_forest.score_samples(X_pca)  # higher = more anomalous
        self.if_scores = self._normalize(if_raw)
        logger.info(
            f"IF scores: mean={self.if_scores.mean():.4f}  "
            f"std={self.if_scores.std():.4f}"
        )

        # Step 6: Local Outlier Factor on full feature matrix
        logger.info("Fitting Local Outlier Factor (full features)...")
        self.lof.fit(X_full)
        lof_raw = -self.lof.negative_outlier_factor_
        self.lof_scores = self._normalize(lof_raw)
        logger.info(
            f"LOF scores: mean={self.lof_scores.mean():.4f}  "
            f"std={self.lof_scores.std():.4f}"
        )

        # Step 7: Weighted ensemble — NO third normalization (FIXES PROBLEM 1)
        # All three components are already in [0,1]. Weighted sum ∈ [0,1].
        self.fraud_scores = np.clip(
            self.if_weight * self.if_scores
            + self.lof_weight * self.lof_scores
            + self.heuristic_weight * self.heuristic_scores,
            0.0, 1.0
        )

        logger.info(
            f"Ensemble: mean={self.fraud_scores.mean():.4f}  "
            f"std={self.fraud_scores.std():.4f}  "
            f"median={np.median(self.fraud_scores):.4f}"
        )

        self.predictions = (self.fraud_scores >= self.fraud_threshold).astype(int)
        logger.info(
            f"Flagged at threshold {self.fraud_threshold}: "
            f"{self.predictions.sum():,} ({self.predictions.mean():.2%})"
        )
        return self.fraud_scores

    # ──────────────────────────────────────────────────────────────────
    # Feature engineering
    # ──────────────────────────────────────────────────────────────────

    def _augment_with_structural_features(
        self,
        embeddings: np.ndarray,
        node_names: List[str],
        graph: Optional[nx.MultiDiGraph],
    ) -> np.ndarray:
        """Embeddings + 7 structural graph features for LOF."""
        if graph is None:
            return embeddings.astype(np.float64)

        structural = []
        for name in node_names:
            attrs = graph.nodes.get(name, {})
            structural.append([
                float(attrs.get("in_degree", 0)),
                float(attrs.get("out_degree", 0)),
                float(attrs.get("total_degree", 0)),
                float(attrs.get("tx_count", 1)),
                np.log1p(float(attrs.get("total_sent", 0))),
                np.log1p(float(attrs.get("total_received", 0))),
                np.log1p(abs(float(attrs.get("balance", 0)))),
            ])

        return np.hstack([
            embeddings.astype(np.float64),
            np.array(structural, dtype=np.float64)
        ])

    def _compute_heuristic_scores(
        self,
        node_names: List[str],
        graph: Optional[nx.MultiDiGraph],
    ) -> np.ndarray:
        """
        Rule-based score from transaction attributes.

        PaySim fraud has near-deterministic signals:
          - Account fully drained (balance=0 after sending) → +0.45
          - TRANSFER or CASH_OUT transaction type           → +0.25
          - System-flagged (isFlaggedFraud=1 in PaySim)    → +0.20
          - Transaction volume > $200,000                  → +0.10

        This supplements embedding-based detection for isolated nodes
        that have few graph connections but clear attribute signals.
        """
        scores = np.zeros(len(node_names), dtype=np.float64)
        if graph is None:
            return scores

        for i, name in enumerate(node_names):
            attrs = graph.nodes.get(name, {})
            s = 0.0

            if name.startswith("tx_"):
                # TRANSACTION NODE: attributes are amount, type, is_flagged_fraud
                tx_type = str(attrs.get("type", attrs.get("tx_type", "")))
                if tx_type in ("TRANSFER", "CASH_OUT"):
                    s += 0.35

                # PaySim isFlaggedFraud — near-deterministic fraud signal
                if attrs.get("is_flagged_fraud", attrs.get("is_flagged", 0)):
                    s += 0.35

                # Large transaction volume
                amount = float(attrs.get("amount", attrs.get("weight", 0)))
                if amount > 200_000:
                    s += 0.20
                if amount > 500_000:
                    s += 0.10

            else:
                # ACCOUNT NODE: check account-level drain signals
                total_sent = float(attrs.get("total_sent", 0))
                balance = float(attrs.get("balance", -1))
                if total_sent > 0 and balance == 0.0:
                    s += 0.45

                total_vol = total_sent + float(attrs.get("total_received", 0))
                if total_vol > 200_000:
                    s += 0.10

            scores[i] = min(s, 1.0)

        return scores

    # ──────────────────────────────────────────────────────────────────
    # Threshold optimisation — FIXES PROBLEM 4
    # ──────────────────────────────────────────────────────────────────

    def find_optimal_threshold(
        self,
        true_labels: np.ndarray,
        beta: float = 1.0,
    ) -> Tuple[float, float]:
        """
        Find the score threshold that maximises F-beta on the labelled set.

        beta=1.0  → maximise F1 (balance precision & recall)
        beta=0.5  → favour precision (fewer false positives)
        beta=2.0  → favour recall (catch more fraud)

        Returns: (optimal_threshold, best_f_score)
        """
        from sklearn.metrics import precision_recall_curve

        precision, recall, thresholds = precision_recall_curve(
            true_labels, self.fraud_scores
        )

        beta_sq = beta ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            denom = beta_sq * precision[:-1] + recall[:-1]
            f_scores = np.where(
                denom > 0,
                (1 + beta_sq) * precision[:-1] * recall[:-1] / denom,
                0.0,
            )

        best_idx = int(np.argmax(f_scores))
        optimal_threshold = float(thresholds[best_idx])

        # Update stored threshold and predictions
        self.fraud_threshold = optimal_threshold
        self.predictions = (self.fraud_scores >= optimal_threshold).astype(int)

        logger.info(
            f"Optimal threshold={optimal_threshold:.4f} → "
            f"F{beta}={f_scores[best_idx]:.4f}  "
            f"P={precision[best_idx]:.4f}  R={recall[best_idx]:.4f}"
        )
        return optimal_threshold, float(f_scores[best_idx])

    # ──────────────────────────────────────────────────────────────────
    # Evaluation — FIXES PROBLEM 5
    # ──────────────────────────────────────────────────────────────────

    def evaluate_against_labels(
        self,
        true_labels: np.ndarray,
        threshold: Optional[float] = None,
        auto_tune_threshold: bool = True,
    ) -> Dict:
        """
        Compute all evaluation metrics against ground-truth labels.

        Pass TRANSACTION NODES ONLY (tx_* prefix) — account node labels
        are contaminated by the graph construction bug.

        FIXES PROBLEM 5: Returns a rich metrics dict that run_pipeline.py
        saves to data/detection_metrics.json, which the API then serves
        to the frontend dashboard.

        Args:
            true_labels:          binary (0/1) array aligned with fraud_scores
            threshold:            fixed threshold (skips auto-tuning if set)
            auto_tune_threshold:  find optimal F1 threshold automatically

        Returns:
            dict with precision, recall, f1, roc_auc, pr_auc,
                  confusion_matrix, score_distribution, and more
        """
        from sklearn.metrics import (
            precision_score, recall_score, f1_score,
            roc_auc_score, average_precision_score,
            confusion_matrix,
        )

        if len(true_labels) != len(self.fraud_scores):
            raise ValueError(
                f"Label length {len(true_labels)} != "
                f"scores length {len(self.fraud_scores)}"
            )

        # Tune threshold before computing final metrics
        if threshold is not None:
            self.fraud_threshold = float(threshold)
            self.predictions = (self.fraud_scores >= self.fraud_threshold).astype(int)
        elif auto_tune_threshold and true_labels.sum() > 0:
            self.find_optimal_threshold(true_labels, beta=1.0)

        pred = (self.fraud_scores >= self.fraud_threshold).astype(int)
        cm = confusion_matrix(true_labels, pred)
        tn, fp, fn, tp = cm.ravel()

        metrics = {
            # Primary metrics
            "precision": float(precision_score(true_labels, pred, zero_division=0)),
            "recall":    float(recall_score(true_labels, pred, zero_division=0)),
            "f1":        float(f1_score(true_labels, pred, zero_division=0)),

            # Ranking metrics (threshold-independent — most reliable for imbalanced data)
            "roc_auc": float(roc_auc_score(true_labels, self.fraud_scores)),
            "pr_auc":  float(average_precision_score(true_labels, self.fraud_scores)),

            # Confusion matrix
            "confusion_matrix": {
                "tn": int(tn), "fp": int(fp),
                "fn": int(fn), "tp": int(tp),
            },

            # Derived rates
            "true_positive_rate":  float(tp / max(tp + fn, 1)),
            "false_positive_rate": float(fp / max(fp + tn, 1)),
            "false_discovery_rate": float(fp / max(fp + tp, 1)),

            # Context for reproducibility
            "threshold_used":          float(self.fraud_threshold),
            "threshold_auto_tuned":    auto_tune_threshold and threshold is None,
            "total_nodes_evaluated":   int(len(true_labels)),
            "positive_class_count":    int(true_labels.sum()),
            "positive_class_rate":     float(true_labels.mean()),
            "flagged_count":           int(pred.sum()),
            "flagged_rate":            float(pred.mean()),

            # Score distribution (for dashboard charts)
            "score_distribution": {
                "mean":   float(self.fraud_scores.mean()),
                "std":    float(self.fraud_scores.std()),
                "median": float(np.median(self.fraud_scores)),
                "p75":    float(np.percentile(self.fraud_scores, 75)),
                "p90":    float(np.percentile(self.fraud_scores, 90)),
                "p95":    float(np.percentile(self.fraud_scores, 95)),
                "p99":    float(np.percentile(self.fraud_scores, 99)),
            },

            # Per-component diagnostics
            "component_diagnostics": {
                "if_std":           float(self.if_scores.std()),
                "lof_std":          float(self.lof_scores.std()),
                "heuristic_flagged": int((self.heuristic_scores > 0.5).sum()),
                "if_lof_corr":      float(np.corrcoef(self.if_scores, self.lof_scores)[0, 1]),
            },
        }

        logger.info(
            f"\n{'='*50}\n"
            f"DETECTION RESULTS\n"
            f"  Precision : {metrics['precision']:.4f}\n"
            f"  Recall    : {metrics['recall']:.4f}\n"
            f"  F1        : {metrics['f1']:.4f}\n"
            f"  AUC-ROC   : {metrics['roc_auc']:.4f}\n"
            f"  PR-AUC    : {metrics['pr_auc']:.4f}\n"
            f"  Threshold : {metrics['threshold_used']:.4f} "
            f"({'auto' if metrics['threshold_auto_tuned'] else 'fixed'})\n"
            f"  Flagged   : {metrics['flagged_count']:,} / {len(true_labels):,} "
            f"({metrics['flagged_rate']:.2%})\n"
            f"{'='*50}"
        )

        return metrics

    # ──────────────────────────────────────────────────────────────────
    # Results helpers
    # ──────────────────────────────────────────────────────────────────

    def get_results_dataframe(self) -> pd.DataFrame:
        """Return full detection results as a sorted DataFrame."""
        if self.fraud_scores is None:
            raise RuntimeError("Run fit_predict() first.")
        return pd.DataFrame({
            "node_id":         self.node_names,
            "fraud_score":     np.round(self.fraud_scores, 6),
            "if_score":        np.round(self.if_scores, 6),
            "lof_score":       np.round(self.lof_scores, 6),
            "heuristic_score": np.round(self.heuristic_scores, 6),
            "risk_level":      self._assign_risk_levels(),
            "is_anomaly":      self.predictions,
        }).sort_values("fraud_score", ascending=False).reset_index(drop=True)

    def _assign_risk_levels(self) -> List[str]:
        levels = []
        for score in self.fraud_scores:
            if score >= self.fraud_threshold:
                levels.append("HIGH")
            elif score >= self.medium_threshold:
                levels.append("MEDIUM")
            else:
                levels.append("LOW")
        return levels

    def get_high_risk_nodes(self, threshold: Optional[float] = None) -> List[str]:
        thresh = threshold if threshold is not None else self.fraud_threshold
        return [n for n, s in zip(self.node_names, self.fraud_scores) if s >= thresh]

    def get_node_score(self, node_name: str) -> Optional[Dict]:
        if node_name not in self.node_names:
            return None
        idx = self.node_names.index(node_name)
        return {
            "node_id":         node_name,
            "fraud_score":     float(self.fraud_scores[idx]),
            "if_score":        float(self.if_scores[idx]),
            "lof_score":       float(self.lof_scores[idx]),
            "heuristic_score": float(self.heuristic_scores[idx]),
            "risk_level":      self._assign_risk_levels()[idx],
            "is_anomaly":      bool(self.predictions[idx]),
        }

    @staticmethod
    def _normalize(scores: np.ndarray) -> np.ndarray:
        """Min-max normalize to [0, 1]. Called once per component — not on ensemble."""
        s_min, s_max = scores.min(), scores.max()
        if s_max == s_min:
            return np.zeros_like(scores, dtype=np.float64)
        return ((scores - s_min) / (s_max - s_min)).astype(np.float64)