"""
experiments/analysis.py

Standalone experiment analysis script.
Run after the pipeline to generate all research observation plots
and print a comprehensive evaluation report.

Usage:
    python experiments/analysis.py
"""

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    FRAUD_SCORES_CSV, EMBEDDINGS_NPY, EMBEDDING_MAP_JSON,
    EXPERIMENTS_DIR, GRAPH_PICKLE
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="darkgrid", palette="deep")

OUTPUT_DIR = EXPERIMENTS_DIR


def run_analysis():
    print("\n" + "=" * 60)
    print("  FRAUD DETECTION SYSTEM — EXPERIMENT ANALYSIS")
    print("=" * 60 + "\n")

    if not FRAUD_SCORES_CSV.exists():
        print("❌ No fraud scores found. Run: python data_pipeline/run_pipeline.py")
        return

    scores_df = pd.read_csv(FRAUD_SCORES_CSV)
    print(f"✅ Loaded fraud scores: {len(scores_df)} nodes")
    print_score_summary(scores_df)

    if EMBEDDINGS_NPY.exists():
        embeddings = np.load(str(EMBEDDINGS_NPY))
        print(f"✅ Loaded embeddings: shape={embeddings.shape}")
        plot_embedding_analysis(embeddings, scores_df)

    plot_score_analysis(scores_df)
    plot_model_comparison(scores_df)

    if GRAPH_PICKLE.exists():
        import pickle
        with open(GRAPH_PICKLE, "rb") as f:
            G = pickle.load(f)
        plot_graph_degree_analysis(G, scores_df)

    print(f"\n✅ All plots saved to: {OUTPUT_DIR}")
    print("\nKey findings:")
    print(f"  - High-risk nodes: {(scores_df['risk_level'] == 'HIGH').sum()}")
    print(f"  - Medium-risk nodes: {(scores_df['risk_level'] == 'MEDIUM').sum()}")
    print(f"  - Low-risk nodes: {(scores_df['risk_level'] == 'LOW').sum()}")
    print(f"  - Avg fraud score: {scores_df['fraud_score'].mean():.4f}")
    print(f"  - 95th percentile: {scores_df['fraud_score'].quantile(0.95):.4f}")


def print_score_summary(df):
    print("\n📊 Score Summary:")
    print(f"   Mean:   {df['fraud_score'].mean():.4f}")
    print(f"   Median: {df['fraud_score'].median():.4f}")
    print(f"   Std:    {df['fraud_score'].std():.4f}")
    print(f"   Max:    {df['fraud_score'].max():.4f}")
    if "risk_level" in df.columns:
        print(f"\n   Risk breakdown:")
        for level, count in df["risk_level"].value_counts().items():
            print(f"     {level}: {count} ({count/len(df)*100:.1f}%)")


def plot_score_analysis(df):
    """Comprehensive fraud score analysis plots."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Fraud Score Analysis", fontsize=14, fontweight="bold")

    # 1. Score distribution
    axes[0, 0].hist(df["fraud_score"], bins=60, color="#e74c3c", alpha=0.75)
    axes[0, 0].axvline(0.65, color="yellow", linestyle="--", label="High-risk (0.65)")
    axes[0, 0].axvline(0.45, color="orange", linestyle="--", label="Medium-risk (0.45)")
    axes[0, 0].set_title("Fraud Score Distribution")
    axes[0, 0].set_xlabel("Score")
    axes[0, 0].set_ylabel("Count")
    axes[0, 0].legend(fontsize=8)

    # 2. Cumulative distribution
    sorted_scores = np.sort(df["fraud_score"])
    cdf = np.arange(1, len(sorted_scores) + 1) / len(sorted_scores)
    axes[0, 1].plot(sorted_scores, cdf, color="#3498db", linewidth=2)
    axes[0, 1].axvline(0.65, color="red", linestyle="--", alpha=0.7)
    axes[0, 1].set_title("CDF of Fraud Scores")
    axes[0, 1].set_xlabel("Score")
    axes[0, 1].set_ylabel("Cumulative Proportion")

    # 3. IF vs LOF
    if "if_score" in df.columns and "lof_score" in df.columns:
        scatter = axes[1, 0].scatter(
            df["if_score"], df["lof_score"],
            c=df["fraud_score"], cmap="RdYlGn_r",
            alpha=0.5, s=8
        )
        plt.colorbar(scatter, ax=axes[1, 0])
        axes[1, 0].set_title("IF Score vs LOF Score")
        axes[1, 0].set_xlabel("Isolation Forest Score")
        axes[1, 0].set_ylabel("LOF Score")

    # 4. Top 50 node scores
    top50 = df.nlargest(50, "fraud_score")
    colors_bar = [
        "#e74c3c" if r == "HIGH" else "#f39c12" if r == "MEDIUM" else "#27ae60"
        for r in top50.get("risk_level", ["HIGH"] * 50)
    ]
    axes[1, 1].barh(range(50), top50["fraud_score"].values, color=colors_bar, alpha=0.8)
    axes[1, 1].set_title("Top 50 Highest-Risk Nodes")
    axes[1, 1].set_xlabel("Fraud Score")
    axes[1, 1].set_ylabel("Rank")
    axes[1, 1].invert_yaxis()

    plt.tight_layout()
    plt.savefig(str(OUTPUT_DIR / "score_analysis.png"), dpi=120)
    plt.close()
    print("  ✅ Saved: score_analysis.png")


def plot_model_comparison(df):
    """Compare IF vs LOF model contributions."""
    if "if_score" not in df.columns:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(3)
    width = 0.35

    metrics = {
        "IF Score": [
            df[df.get("risk_level", pd.Series(["LOW"]*len(df))) == "HIGH"]["if_score"].mean(),
            df[df.get("risk_level", pd.Series(["LOW"]*len(df))) == "MEDIUM"]["if_score"].mean(),
            df[df.get("risk_level", pd.Series(["LOW"]*len(df))) == "LOW"]["if_score"].mean(),
        ],
        "LOF Score": [
            df[df.get("risk_level", pd.Series(["LOW"]*len(df))) == "HIGH"]["lof_score"].mean(),
            df[df.get("risk_level", pd.Series(["LOW"]*len(df))) == "MEDIUM"]["lof_score"].mean(),
            df[df.get("risk_level", pd.Series(["LOW"]*len(df))) == "LOW"]["lof_score"].mean(),
        ]
    }

    ax.bar(x - width/2, metrics["IF Score"], width, label="Isolation Forest",
           color="#e74c3c", alpha=0.8)
    ax.bar(x + width/2, metrics["LOF Score"], width, label="Local Outlier Factor",
           color="#3498db", alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(["HIGH Risk", "MEDIUM Risk", "LOW Risk"])
    ax.set_ylabel("Mean Score")
    ax.set_title("Model Score Comparison by Risk Level")
    ax.legend()
    plt.tight_layout()
    plt.savefig(str(OUTPUT_DIR / "model_comparison.png"), dpi=120)
    plt.close()
    print("  ✅ Saved: model_comparison.png")


def plot_embedding_analysis(embeddings, scores_df):
    """PCA visualization of embeddings."""
    from sklearn.decomposition import PCA

    n_sample = min(3000, len(embeddings))
    idx = np.random.choice(len(embeddings), n_sample, replace=False)
    emb_sample = embeddings[idx]

    pca = PCA(n_components=2)
    coords = pca.fit_transform(emb_sample)

    # Get corresponding scores
    node_ids = scores_df["node_id"].tolist()
    sample_scores = [
        float(scores_df[scores_df["node_id"] == node_ids[i]]["fraud_score"].values[0])
        if i < len(node_ids) and node_ids[i] in scores_df["node_id"].values
        else 0.0
        for i in idx
    ]

    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(
        coords[:, 0], coords[:, 1],
        c=sample_scores, cmap="RdYlGn_r",
        alpha=0.5, s=10
    )
    plt.colorbar(scatter, ax=ax, label="Fraud Score")
    ax.set_title(
        f"PCA of Node2Vec Embeddings (dim={embeddings.shape[1]})\n"
        f"Variance explained: {pca.explained_variance_ratio_.sum():.1%}"
    )
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
    plt.tight_layout()
    plt.savefig(str(OUTPUT_DIR / "pca_embeddings.png"), dpi=120)
    plt.close()
    print("  ✅ Saved: pca_embeddings.png")


def plot_graph_degree_analysis(G, scores_df):
    """Degree vs fraud score correlation."""
    degrees = dict(G.degree())
    data = []
    for _, row in scores_df.iterrows():
        node = row["node_id"]
        if node in degrees:
            data.append({
                "degree": degrees[node],
                "fraud_score": row["fraud_score"],
                "risk_level": row.get("risk_level", "LOW"),
            })

    if not data:
        return

    data_df = pd.DataFrame(data)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].scatter(
        data_df["degree"], data_df["fraud_score"],
        alpha=0.3, s=8, c=data_df["fraud_score"],
        cmap="RdYlGn_r"
    )
    axes[0].set_xlabel("Node Degree")
    axes[0].set_ylabel("Fraud Score")
    axes[0].set_title("Node Degree vs Fraud Score")
    axes[0].set_xscale("log")

    # Degree distribution by risk level
    for level, color in [("HIGH", "#e74c3c"), ("MEDIUM", "#f39c12"), ("LOW", "#27ae60")]:
        subset = data_df[data_df["risk_level"] == level]["degree"]
        if len(subset) > 0:
            axes[1].hist(subset, bins=30, alpha=0.6, label=level, color=color)

    axes[1].set_xlabel("Degree")
    axes[1].set_ylabel("Count")
    axes[1].set_title("Degree Distribution by Risk Level")
    axes[1].legend()
    axes[1].set_xscale("log")

    plt.tight_layout()
    plt.savefig(str(OUTPUT_DIR / "degree_fraud_analysis.png"), dpi=120)
    plt.close()
    print("  ✅ Saved: degree_fraud_analysis.png")


if __name__ == "__main__":
    run_analysis()