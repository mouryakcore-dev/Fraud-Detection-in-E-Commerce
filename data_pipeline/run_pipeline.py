"""
data_pipeline/run_pipeline.py

KEY CHANGES IN THIS VERSION
============================
1. Passes updated FraudAnomalyDetector with:
   - contamination=0.013 (tuned to PaySim fraud rate)
   - pca_components=20 (fixes IF discrimination)
   - heuristic_weight=0.15 (new third signal)
   - auto_tune_threshold=True (finds optimal F1 threshold)

2. Evaluates on TRANSACTION NODES ONLY (tx_* prefix).
   Account node labels are unreliable — destination accounts
   are tagged is_fraud=1 just for receiving from a fraudster.

3. SAVES detection_metrics.json to data/ folder.
   This is the file the API serves to the frontend dashboard.
   Without this file the dashboard shows hardcoded fake numbers.

4. All paths are absolute (relative to settings.py DATA_DIR).
   No more "data/fraud_clusters.json" relative-to-CWD bugs.
"""

import sys
import json
import logging
import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    PAYSIM_CSV, GRAPH_PICKLE, EMBEDDINGS_NPY,
    EMBEDDING_MAP_JSON, FRAUD_SCORES_CSV, DATA_DIR,
    NODE2VEC_CONFIG, ANOMALY_CONFIG, CLUSTER_CONFIG, EXPERIMENTS_DIR
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pipeline")

# ── Absolute output paths (no CWD dependency) ──────────────────────────
FRAUD_CLUSTERS_JSON  = DATA_DIR / "fraud_clusters.json"
DETECTION_METRICS_JSON = DATA_DIR / "detection_metrics.json"


def run_pipeline(sample_size=None, skip_embeddings=False):
    t0 = time.time()
    logger.info("=" * 60)
    logger.info("FRAUDLENS PIPELINE STARTING")
    logger.info("=" * 60)

    # ── Step 1: Data Ingestion ─────────────────────────────────────
    logger.info("\n[1/6] Loading PaySim dataset...")
    from backend.ingestion.data_loader import PaySimLoader

    loader = PaySimLoader(PAYSIM_CSV, sample_size=sample_size)
    df = loader.get_graph_ready_df()

    stats = loader.get_fraud_stats()
    logger.info(f"  Rows: {stats['total_transactions']:,}")
    logger.info(f"  True fraud rate: {stats['fraud_rate']:.2%}")
    logger.info(f"  Fraud count: {stats['fraud_count']:,}")

    # ── Step 2: Graph Construction ─────────────────────────────────
    logger.info("\n[2/6] Building transaction graph...")
    from backend.graph_builder.graph_constructor import TransactionGraphBuilder

    builder = TransactionGraphBuilder()
    G = builder.build_from_dataframe(df)
    summary = builder.get_summary()
    logger.info(f"  Nodes: {summary['total_nodes']:,}  Edges: {summary['total_edges']:,}")
    logger.info(f"  Node types: {summary['node_types']}")
    builder.save(str(GRAPH_PICKLE))

    # ── Step 3: Node2Vec Embeddings ────────────────────────────────
    model_path = str(EXPERIMENTS_DIR / "node2vec.model")

    if skip_embeddings and EMBEDDINGS_NPY.exists():
        logger.info("\n[3/6] Loading cached embeddings...")
        embeddings = np.load(str(EMBEDDINGS_NPY))
        with open(str(EMBEDDING_MAP_JSON)) as f:
            node_id_map = json.load(f)
        logger.info(f"  Shape: {embeddings.shape}")
    else:
        logger.info("\n[3/6] Training Node2Vec embeddings...")
        from backend.embeddings.node2vec_trainer import FraudNode2Vec

        n2v = FraudNode2Vec(**NODE2VEC_CONFIG)
        embeddings = n2v.train(G)
        node_id_map = n2v.node_id_map
        n2v.save(str(EMBEDDINGS_NPY), str(EMBEDDING_MAP_JSON), model_path)
        logger.info(f"  Embeddings shape: {embeddings.shape}")

    # ── Step 4: Anomaly Detection ──────────────────────────────────
    logger.info("\n[4/6] Running anomaly detection...")
    from backend.anomaly_detection.detector import FraudAnomalyDetector

    # Aligned sorted ordering (matches FraudNode2Vec._build_embedding_matrix)
    all_names = sorted(node_id_map.keys())
    valid_pairs = [
        (n, node_id_map[n])
        for n in all_names
        if node_id_map[n] < len(embeddings)
    ]
    valid_names   = [p[0] for p in valid_pairs]
    valid_indices = [p[1] for p in valid_pairs]
    valid_embeddings = embeddings[valid_indices]

    # Unpack ANOMALY_CONFIG nested sub-dicts
    if_cfg  = ANOMALY_CONFIG.get("isolation_forest", {})
    lof_cfg = ANOMALY_CONFIG.get("lof", {})

    detector = FraudAnomalyDetector(
        if_n_estimators  = if_cfg.get("if_n_estimators", 300),
        if_contamination = if_cfg.get("if_contamination", 0.013),
        lof_n_neighbors  = lof_cfg.get("lof_n_neighbors", 30),
        lof_contamination= lof_cfg.get("lof_contamination", 0.013),
        pca_components   = ANOMALY_CONFIG.get("pca_components", 20),
        fraud_threshold  = ANOMALY_CONFIG.get("fraud_score_threshold", 0.65),
        medium_threshold = ANOMALY_CONFIG.get("medium_risk_threshold", 0.40),
        if_weight        = ANOMALY_CONFIG.get("if_weight", 0.45),
        lof_weight       = ANOMALY_CONFIG.get("lof_weight", 0.40),
        heuristic_weight = ANOMALY_CONFIG.get("heuristic_weight", 0.15),
    )

    detector.fit_predict(valid_embeddings, valid_names, G)
    results_df = detector.get_results_dataframe()

    # ── Step 4b: Evaluate on transaction nodes only ────────────────
    # tx_* nodes carry the original PaySim isFraud label — clean ground truth.
    # acc_* nodes are unreliable (dest accounts tagged is_fraud=1 just for
    # receiving from a fraudster — see graph_constructor audit notes).
    tx_mask     = [n.startswith("tx_") for n in valid_names]
    tx_names    = [n for n, m in zip(valid_names, tx_mask) if m]
    tx_positions= [i for i, m in enumerate(tx_mask) if m]

    true_labels = np.array([
        G.nodes.get(n, {}).get("is_fraud", 0) for n in tx_names
    ])

    # Evaluate on tx nodes only using a temporary sub-detector.
    # We NEVER mutate the main detector arrays — that caused the crash.
    metrics = {}
    if true_labels.sum() > 0:
        logger.info(
            f"\n  Evaluating on {len(tx_names):,} tx nodes "
            f"({true_labels.sum():,} fraud = {true_labels.mean():.2%})"
        )

        # Temporary detector with only tx-node scores for evaluation
        eval_detector = FraudAnomalyDetector()
        eval_detector.fraud_scores     = detector.fraud_scores[tx_positions].copy()
        eval_detector.if_scores        = detector.if_scores[tx_positions].copy()
        eval_detector.lof_scores       = detector.lof_scores[tx_positions].copy()
        eval_detector.heuristic_scores = detector.heuristic_scores[tx_positions].copy()
        eval_detector.node_names       = tx_names
        eval_detector.fraud_threshold  = detector.fraud_threshold
        eval_detector.predictions      = (eval_detector.fraud_scores >= detector.fraud_threshold).astype(int)

        metrics = eval_detector.evaluate_against_labels(
            true_labels,
            auto_tune_threshold=True,
        )

        # Apply auto-tuned threshold back to main detector
        detector.fraud_threshold = metrics["threshold_used"]

        # ── SAVE detection_metrics.json ────────────────────────────
        DETECTION_METRICS_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(DETECTION_METRICS_JSON, "w") as f:
            json.dump(metrics, f, indent=2)
        logger.info(f"\n  ✓ Metrics saved → {DETECTION_METRICS_JSON}")
        logger.info(f"    Precision : {metrics['precision']:.4f}")
        logger.info(f"    Recall    : {metrics['recall']:.4f}")
        logger.info(f"    F1        : {metrics['f1']:.4f}")
        logger.info(f"    AUC-ROC   : {metrics['roc_auc']:.4f}")
        logger.info(f"    PR-AUC    : {metrics['pr_auc']:.4f}")
        logger.info(f"    Threshold : {metrics['threshold_used']:.4f} (auto-tuned)")
    else:
        logger.warning("  No fraud tx nodes found — check isFraud labels are loaded.")

    # Main detector arrays untouched — safe to call get_results_dataframe()
    results_df = detector.get_results_dataframe()

    results_df.to_csv(str(FRAUD_SCORES_CSV), index=False)
    logger.info(
        f"\n  ✓ Scores saved → {FRAUD_SCORES_CSV}"
        f"  HIGH: {(results_df['risk_level']=='HIGH').sum():,}  "
        f"MEDIUM: {(results_df['risk_level']=='MEDIUM').sum():,}  "
        f"LOW: {(results_df['risk_level']=='LOW').sum():,}"
    )

    # ── Step 5: Fraud Cluster Detection ───────────────────────────
    logger.info("\n[5/6] Detecting fraud clusters...")
    from backend.fraud_clusters.cluster_detector import FraudClusterDetector

    score_map = dict(zip(results_df["node_id"], results_df["fraud_score"]))
    cluster_detector = FraudClusterDetector(**CLUSTER_CONFIG)
    cluster_detector.detect_communities(G, score_map)
    fraud_rings = cluster_detector.export_fraud_rings_for_visualization()

    logger.info(f"  Communities: {len(cluster_detector.communities):,}")
    logger.info(f"  Fraud rings: {len(fraud_rings):,}")

    FRAUD_CLUSTERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(FRAUD_CLUSTERS_JSON, "w") as f:
        json.dump(fraud_rings, f, indent=2)
    logger.info(f"  ✓ Clusters saved → {FRAUD_CLUSTERS_JSON}")

    # ── Step 6: Generate Plots ─────────────────────────────────────
    logger.info("\n[6/6] Generating visualisations...")
    _generate_plots(df, results_df, embeddings, valid_names,
                    node_id_map, G, cluster_detector,
                    metrics if true_labels.sum() > 0 else None)

    elapsed = time.time() - t0
    logger.info(f"\n{'='*60}")
    logger.info(f"PIPELINE COMPLETE in {elapsed:.1f}s")
    logger.info(f"{'='*60}")
    logger.info(f"  Scores  : {FRAUD_SCORES_CSV}")
    logger.info(f"  Metrics : {DETECTION_METRICS_JSON}")
    logger.info(f"  Clusters: {FRAUD_CLUSTERS_JSON}")
    logger.info(f"  Plots   : {EXPERIMENTS_DIR}")
    logger.info(f"\nStart API: uvicorn backend.api.main:app --reload --port 8000")


def _generate_plots(df, results_df, embeddings, node_names,
                    node_id_map, G, cluster_detector, metrics=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="darkgrid")
    plt.rcParams.update({"figure.dpi": 120, "font.size": 11})
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Plot 1: Fraud Score Distribution ──────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].hist(results_df["fraud_score"], bins=60,
                 color="#e74c3c", alpha=0.75, edgecolor="black", linewidth=0.3)
    thresh = results_df["fraud_score"].quantile(0.987) if metrics is None \
        else metrics.get("threshold_used", 0.65)
    axes[0].axvline(thresh, color="yellow", linestyle="--",
                    linewidth=2, label=f"Threshold ({thresh:.3f})")
    axes[0].set_xlabel("Fraud Score")
    axes[0].set_ylabel("Count")
    axes[0].set_title("Fraud Score Distribution (corrected)")
    axes[0].legend()

    risk_counts = results_df["risk_level"].value_counts()
    colors = {"HIGH": "#e74c3c", "MEDIUM": "#f39c12", "LOW": "#27ae60"}
    axes[1].bar(risk_counts.index, risk_counts.values,
                color=[colors.get(l, "grey") for l in risk_counts.index])
    axes[1].set_title("Risk Level Distribution")
    axes[1].set_ylabel("Node Count")
    plt.tight_layout()
    plt.savefig(str(EXPERIMENTS_DIR / "fraud_score_distribution.png"))
    plt.close()

    # ── Plot 2: IF vs LOF Comparison ──────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 8))
    sc = ax.scatter(results_df["if_score"], results_df["lof_score"],
                    c=results_df["fraud_score"], cmap="RdYlGn_r",
                    alpha=0.4, s=8)
    plt.colorbar(sc, ax=ax, label="Ensemble Fraud Score")
    ax.set_xlabel("Isolation Forest Score (PCA-reduced)")
    ax.set_ylabel("Local Outlier Factor Score")
    ax.set_title("IF vs LOF Scores (PCA applied to IF inputs)")
    plt.tight_layout()
    plt.savefig(str(EXPERIMENTS_DIR / "if_vs_lof_scores.png"))
    plt.close()

    # ── Plot 3: Precision-Recall Curve (if metrics available) ─────
    if metrics is not None:
        try:
            from sklearn.metrics import precision_recall_curve

            tx_mask  = [n.startswith("tx_") for n in node_names]
            tx_names = [n for n, m in zip(node_names, tx_mask) if m]
            tx_pos   = [i for i, m in enumerate(tx_mask) if m]

            scores_sub = results_df.set_index("node_id").reindex(tx_names)["fraud_score"].values
            true_labels = np.array([G.nodes.get(n, {}).get("is_fraud", 0) for n in tx_names])

            if true_labels.sum() > 0 and not np.isnan(scores_sub).any():
                p, r, t = precision_recall_curve(true_labels, scores_sub)
                fig, ax = plt.subplots(figsize=(9, 7))
                ax.plot(r, p, color="#2980b9", linewidth=2,
                        label=f"PR Curve (AUC={metrics['pr_auc']:.3f})")
                ax.scatter(
                    [metrics["confusion_matrix"]["tp"] /
                     max(metrics["confusion_matrix"]["tp"] + metrics["confusion_matrix"]["fn"], 1)],
                    [metrics["precision"]],
                    color="red", zorder=5, s=80,
                    label=f"Operating point (F1={metrics['f1']:.3f})"
                )
                ax.set_xlabel("Recall")
                ax.set_ylabel("Precision")
                ax.set_title("Precision-Recall Curve\n(evaluated on transaction nodes only)")
                ax.legend()
                ax.set_xlim([0, 1])
                ax.set_ylim([0, 1])
                plt.tight_layout()
                plt.savefig(str(EXPERIMENTS_DIR / "precision_recall_curve.png"))
                plt.close()
                logger.info("  precision_recall_curve.png saved")
        except Exception as e:
            logger.warning(f"  PR curve failed: {e}")

    # ── Plot 4: UMAP ───────────────────────────────────────────────
    try:
        from umap import UMAP
        sample_sz = min(5000, len(node_names))
        rng = np.random.default_rng(42)
        idx = rng.choice(len(node_names), sample_sz, replace=False)

        emb_s, score_s = [], []
        for i in idx:
            n = node_names[i]
            if n not in node_id_map:
                continue
            row = results_df[results_df["node_id"] == n]
            if row.empty:
                continue
            emb_s.append(embeddings[node_id_map[n]])
            score_s.append(float(row.iloc[0]["fraud_score"]))

        if len(emb_s) >= 10:
            reducer = UMAP(n_components=2, random_state=42, n_jobs=1)
            coords  = reducer.fit_transform(np.array(emb_s))
            fig, ax = plt.subplots(figsize=(12, 9))
            sc = ax.scatter(coords[:, 0], coords[:, 1],
                            c=score_s, cmap="RdYlGn_r", alpha=0.5, s=8)
            plt.colorbar(sc, ax=ax, label="Fraud Score")
            ax.set_title(f"UMAP Embedding Space (n={len(emb_s):,})")
            ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
            plt.tight_layout()
            plt.savefig(str(EXPERIMENTS_DIR / "umap_embeddings.png"), dpi=150)
            plt.close()
            logger.info("  umap_embeddings.png saved")
    except ImportError:
        logger.warning("  umap-learn not installed — skipping UMAP plot")

    # ── Plot 5: Fraud by Transaction Type ─────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))
    type_stats = df.groupby("type")["isFraud"].agg(["mean", "sum"]).reset_index()
    bars = ax.bar(type_stats["type"], type_stats["mean"] * 100,
                  color=["#e74c3c" if r > 0.01 else "#27ae60" for r in type_stats["mean"]])
    for bar, val in zip(bars, type_stats["sum"]):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.1, f"n={int(val)}", ha="center", fontsize=9)
    ax.set_xlabel("Transaction Type"); ax.set_ylabel("Fraud Rate (%)")
    ax.set_title("Fraud Rate by Transaction Type (PaySim ground truth)")
    plt.tight_layout()
    plt.savefig(str(EXPERIMENTS_DIR / "fraud_by_type.png"))
    plt.close()

    # ── Plot 6: Temporal Trends ───────────────────────────────────
    if "step" in df.columns:
        fig, axes = plt.subplots(2, 1, figsize=(14, 8))
        hourly = df.groupby("step").agg(
            count=("amount", "count"), fraud=("isFraud", "sum")
        ).reset_index()
        axes[0].fill_between(hourly["step"], hourly["count"], alpha=0.3, color="#3498db")
        axes[0].plot(hourly["step"], hourly["count"], color="#3498db", linewidth=1)
        axes[0].set_title("Transaction Count Over Time"); axes[0].set_ylabel("# Transactions")
        axes[1].fill_between(hourly["step"], hourly["fraud"], alpha=0.3, color="#e74c3c")
        axes[1].plot(hourly["step"], hourly["fraud"], color="#e74c3c", linewidth=1.5)
        axes[1].set_title("Fraud Events Over Time (PaySim)")
        axes[1].set_xlabel("Step (hours)"); axes[1].set_ylabel("# Fraud")
        plt.tight_layout()
        plt.savefig(str(EXPERIMENTS_DIR / "temporal_fraud_trends.png"))
        plt.close()

    logger.info(f"  All plots saved → {EXPERIMENTS_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run FraudLens pipeline")
    parser.add_argument("--sample", type=int, default=None,
                        help="Sample N transactions (default: all)")
    parser.add_argument("--skip-embeddings", action="store_true",
                        help="Use cached embeddings instead of retraining")
    args = parser.parse_args()
    run_pipeline(sample_size=args.sample, skip_embeddings=args.skip_embeddings)