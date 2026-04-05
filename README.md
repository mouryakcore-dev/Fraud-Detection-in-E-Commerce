<<<<<<< HEAD
# Graph-Based Real-Time Fraud & Anomaly Detection in E-Commerce
## Using Dynamic User–Order Networks

---

## System Architecture Overview

This system models e-commerce transactions as a **dynamic heterogeneous graph** and identifies fraudulent activity using **graph representation learning** + **unsupervised anomaly detection**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                  │
│  PaySim Dataset → CSV Loader → Schema Validator → Feature Engineer  │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────────┐
│                    GRAPH CONSTRUCTION PIPELINE                       │
│  Heterogeneous Graph Builder → Dynamic Update Engine → NetworkX/PyG │
│  Nodes: Users, Orders, Devices, Addresses, Payments, Coupons        │
│  Edges: places, uses_device, delivered_to, applies_coupon, shares   │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────────┐
│                 GRAPH EMBEDDING MODULE                               │
│  Node2Vec → DeepWalk → Random Walk Sampler → Skip-Gram Training     │
│  Output: 64/128-dim node embedding vectors                          │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────────┐
│               ANOMALY DETECTION ENGINE                               │
│  Isolation Forest | Local Outlier Factor | DBSCAN Cluster Analysis  │
│  Per-node fraud scores → Threshold-based alerting                   │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────────┐
│              FRAUD CLUSTER DETECTION                                 │
│  Louvain Community Detection → Ring Analysis → Subgraph Extraction  │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────────┐
│              STREAMING SIMULATOR + REST API                         │
│  FastAPI → WebSocket → Transaction Queue → Real-time Scoring        │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────────┐
│              REACT DASHBOARD                                         │
│  D3.js Graph Viz | Fraud Alerts | Risk Scores | Cluster View        │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Install backend dependencies
cd backend && pip install -r requirements.txt

# 2. Download PaySim dataset
python data_pipeline/download_data.py

# 3. Run full pipeline
python data_pipeline/run_pipeline.py

# 4. Start API server
uvicorn backend.api.main:app --reload --port 8000

# 5. Start frontend
cd frontend && npm install && npm start
```

## Module Descriptions

| Module | Purpose |
|--------|---------|
| `ingestion/` | Load, validate, feature-engineer PaySim CSV |
| `graph_builder/` | Build heterogeneous NetworkX graph |
| `embeddings/` | Node2Vec / DeepWalk training |
| `anomaly_detection/` | IsolationForest + LOF scoring |
| `fraud_clusters/` | Community detection, ring identification |
| `streaming_engine/` | Real-time transaction simulation |
| `api/` | FastAPI REST + WebSocket layer |
| `experiments/` | Plots, metrics, analysis notebooks |
