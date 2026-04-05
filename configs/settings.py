"""
configs/settings.py
Central configuration for the Fraud Detection Graph System.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
EXPERIMENTS_DIR = BASE_DIR / "experiments" / "outputs"

PAYSIM_CSV         = DATA_DIR / "paysim.csv"
GRAPH_PICKLE       = DATA_DIR / "transaction_graph.pkl"
EMBEDDINGS_NPY     = DATA_DIR / "node_embeddings.npy"
EMBEDDING_MAP_JSON = DATA_DIR / "node_id_map.json"
FRAUD_SCORES_CSV   = DATA_DIR / "fraud_scores.csv"

# Create dirs if missing
for _d in [DATA_DIR, MODELS_DIR, EXPERIMENTS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Graph Construction ─────────────────────────────────────────────────
GRAPH_CONFIG = {
    "node_types": ["account", "transaction", "merchant"],
    "edge_types": ["sends", "receives", "involves"],
    "max_nodes": 50_000,
    "temporal_window_hours": 24,
}

# ── Node2Vec Embedding ─────────────────────────────────────────────────
NODE2VEC_CONFIG = {
    "dimensions":  64,
    "walk_length": 20,
    "num_walks":   80,
    "p":           1.0,
    "q":           0.5,
    "window":      10,
    "workers":     4,
    "epochs":      3,
    "seed":        42,
}

# ── Anomaly Detection ──────────────────────────────────────────────────
# contamination tuned to PaySim true fraud rate (~0.32-1.3%)
# pca_components: reduces IF input from 64D → 20D (fixes IF discrimination)
# heuristic_weight: third ensemble component from transaction attributes
ANOMALY_CONFIG = {
    "isolation_forest": {
        "if_n_estimators":  300,
        "if_contamination": 0.013,
    },
    "lof": {
        "lof_n_neighbors":   30,
        "lof_contamination": 0.013,
    },
    "pca_components":        20,
    "fraud_score_threshold": 0.65,   # auto-tuned at runtime; this is the fallback
    "medium_risk_threshold": 0.40,
    "if_weight":             0.45,
    "lof_weight":            0.40,
    "heuristic_weight":      0.15,
}

# ── Fraud Cluster Detection ────────────────────────────────────────────
CLUSTER_CONFIG = {
    "min_cluster_size":      3,
    "louvain_resolution":    1.0,
    "fraud_ratio_threshold": 0.4,
}

# ── Streaming Simulator ────────────────────────────────────────────────
STREAMING_CONFIG = {
    "transactions_per_second": 5,
    "burst_probability":       0.02,
    "burst_size":              20,
    "queue_maxsize":           1000,
}

# ── API ────────────────────────────────────────────────────────────────
API_CONFIG = {
    "host":         "0.0.0.0",
    "port":         8000,
    "cors_origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
    "ws_endpoint":  "/ws/transactions",
}