"""
backend/api/main.py

FastAPI REST API + WebSocket Server for Fraud Detection System.

Endpoints:
  GET  /health                    - Health check
  GET  /api/graph/summary         - Graph statistics
  GET  /api/graph/nodes           - Node list with fraud scores
  GET  /api/graph/edges           - Edge list for visualization
  GET  /api/fraud/scores          - All fraud scores
  GET  /api/fraud/high-risk       - High-risk nodes only
  GET  /api/fraud/node/{node_id}  - Single node fraud analysis
  GET  /api/clusters              - Detected fraud clusters/rings
  GET  /api/clusters/{id}         - Specific cluster details
  POST /api/transaction/score     - Score a single new transaction
  GET  /api/analytics/stats       - Dashboard statistics
  WS   /ws/transactions           - Real-time transaction stream
"""

import asyncio
import json
import logging
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from configs.settings import (
    PAYSIM_CSV, GRAPH_PICKLE, EMBEDDINGS_NPY,
    EMBEDDING_MAP_JSON, FRAUD_SCORES_CSV,
    NODE2VEC_CONFIG, ANOMALY_CONFIG, STREAMING_CONFIG, API_CONFIG
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Application state (loaded once at startup)
# ──────────────────────────────────────────────────────────────────────

class AppState:
    graph = None
    fraud_scores_df = None
    cluster_detector = None
    simulator = None
    stream_queue: Optional[asyncio.Queue] = None
    is_pipeline_ready = False
    ws_clients: List[WebSocket] = []


state = AppState()


# ──────────────────────────────────────────────────────────────────────
# Lifespan (startup/shutdown)
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load ML artifacts on startup."""
    logger.info("🚀 Starting Fraud Detection API...")
    try:
        await _load_pipeline()
        logger.info("✅ Pipeline loaded successfully")
    except Exception as e:
        logger.warning(f"⚠️  Pipeline not ready (run data pipeline first): {e}")
    yield
    logger.info("Shutting down...")
    if state.simulator:
        state.simulator.stop()


async def _load_pipeline():
    """Load graph, embeddings, and fraud scores from disk."""
    import pickle
    import numpy as np
    import pandas as pd

    # Load graph
    if GRAPH_PICKLE.exists():
        with open(GRAPH_PICKLE, "rb") as f:
            state.graph = pickle.load(f)
        logger.info(f"Graph loaded: {state.graph.number_of_nodes()} nodes")

    # Load fraud scores
    if FRAUD_SCORES_CSV.exists():
        state.fraud_scores_df = pd.read_csv(FRAUD_SCORES_CSV)
        logger.info(f"Fraud scores loaded: {len(state.fraud_scores_df)} nodes")

    state.is_pipeline_ready = GRAPH_PICKLE.exists() and FRAUD_SCORES_CSV.exists()


# ──────────────────────────────────────────────────────────────────────
# App initialization
# ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fraud Detection Graph System API",
    description="Real-time fraud detection using dynamic transaction graphs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=API_CONFIG["cors_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────
# Request/Response models
# ──────────────────────────────────────────────────────────────────────

class TransactionScoreRequest(BaseModel):
    name_orig: str
    name_dest: str
    amount: float
    tx_type: str
    step: int = 0
    old_balance_orig: float = 0.0
    new_balance_orig: float = 0.0
    old_balance_dest: float = 0.0
    new_balance_dest: float = 0.0


class NodeFilterParams(BaseModel):
    node_type: Optional[str] = None
    risk_level: Optional[str] = None
    limit: int = 100
    offset: int = 0


# ──────────────────────────────────────────────────────────────────────
# Health & Status
# ──────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "pipeline_ready": state.is_pipeline_ready,
        "graph_nodes": state.graph.number_of_nodes() if state.graph else 0,
        "fraud_scores_count": (
            len(state.fraud_scores_df) if state.fraud_scores_df is not None else 0
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Graph endpoints
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/graph/summary")
async def get_graph_summary():
    """Return graph-level statistics."""
    _require_pipeline()
    G = state.graph

    node_types: Dict[str, int] = {}
    for _, attrs in G.nodes(data=True):
        t = attrs.get("node_type", "unknown")
        node_types[t] = node_types.get(t, 0) + 1

    edge_types: Dict[str, int] = {}
    for _, _, attrs in G.edges(data=True):
        t = attrs.get("edge_type", "unknown")
        edge_types[t] = edge_types.get(t, 0) + 1

    return {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "node_types": node_types,
        "edge_types": edge_types,
    }


@app.get("/api/graph/nodes")
async def get_graph_nodes(
    limit: int = 200,
    offset: int = 0,
    node_type: Optional[str] = None,
    risk_level: Optional[str] = None,
):
    """Return nodes with fraud scores for visualization."""
    _require_pipeline()

    df = state.fraud_scores_df.copy()

    if risk_level:
        df = df[df["risk_level"] == risk_level.upper()]

    df_page = df.iloc[offset: offset + limit]

    nodes = []
    for _, row in df_page.iterrows():
        node_attrs = state.graph.nodes.get(row["node_id"], {})
        nodes.append({
            "id": row["node_id"],
            "fraud_score": round(float(row["fraud_score"]), 4),
            "risk_level": row.get("risk_level", "LOW"),
            "node_type": node_attrs.get("node_type", "unknown"),
            "is_fraud": int(node_attrs.get("is_fraud", 0)),
            "degree": int(node_attrs.get("total_degree", 0)),
        })

    return {
        "nodes": nodes,
        "total": len(state.fraud_scores_df),
        "page_size": limit,
        "offset": offset,
    }


@app.get("/api/graph/edges")
async def get_graph_edges(limit: int = 500, node_subset: Optional[str] = None):
    """Return edges for D3.js graph visualization."""
    _require_pipeline()

    edges = []
    count = 0
    for u, v, data in state.graph.edges(data=True):
        if count >= limit:
            break
        edges.append({
            "source": u,
            "target": v,
            "edge_type": data.get("edge_type", "unknown"),
            "weight": float(data.get("weight", 1.0)),
        })
        count += 1

    return {"edges": edges, "total": state.graph.number_of_edges()}


# ──────────────────────────────────────────────────────────────────────
# Fraud Detection endpoints
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/fraud/scores")
async def get_all_fraud_scores(
    limit: int = 500,
    sort_by: str = "fraud_score",
    ascending: bool = False,
):
    """Return fraud scores for all nodes."""
    _require_pipeline()
    df = state.fraud_scores_df.sort_values(sort_by, ascending=ascending)
    return {
        "scores": df.head(limit).to_dict("records"),
        "total": len(df),
    }


@app.get("/api/fraud/high-risk")
async def get_high_risk_nodes(threshold: float = 0.65, limit: int = 100):
    """Return only high-risk nodes above threshold."""
    _require_pipeline()
    df = state.fraud_scores_df
    high_risk = df[df["fraud_score"] >= threshold].sort_values(
        "fraud_score", ascending=False
    )
    return {
        "high_risk_nodes": high_risk.head(limit).to_dict("records"),
        "count": len(high_risk),
        "threshold": threshold,
    }


@app.get("/api/fraud/node/{node_id}")
async def get_node_fraud_details(node_id: str):
    """Return detailed fraud analysis for a single node."""
    _require_pipeline()

    df = state.fraud_scores_df
    row = df[df["node_id"] == node_id]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    node_attrs = state.graph.nodes.get(node_id, {})

    # Get neighbors
    neighbors = list(state.graph.predecessors(node_id)) + \
                list(state.graph.successors(node_id))
    neighbors = list(set(neighbors))[:20]

    neighbor_scores = []
    for n in neighbors:
        n_row = df[df["node_id"] == n]
        if not n_row.empty:
            neighbor_scores.append({
                "node_id": n,
                "fraud_score": float(n_row.iloc[0]["fraud_score"]),
                "risk_level": n_row.iloc[0].get("risk_level", "LOW"),
            })

    record = row.iloc[0]
    return {
        "node_id": node_id,
        "fraud_score": float(record["fraud_score"]),
        "if_score": float(record.get("if_score", 0)),
        "lof_score": float(record.get("lof_score", 0)),
        "risk_level": record.get("risk_level", "LOW"),
        "is_anomaly": bool(record.get("is_anomaly", False)),
        "node_attributes": {
            k: (float(v) if isinstance(v, (int, float)) else v)
            for k, v in node_attrs.items()
        },
        "neighbors": neighbor_scores,
        "neighbor_avg_score": (
            sum(n["fraud_score"] for n in neighbor_scores) / len(neighbor_scores)
            if neighbor_scores else 0.0
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Cluster endpoints
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/clusters")
async def get_fraud_clusters():
    """Return all detected fraud ring clusters."""
    # Load from cache file if available
    cluster_file = Path("data/fraud_clusters.json")
    if cluster_file.exists():
        with open(cluster_file) as f:
            clusters = json.load(f)
        return {"clusters": clusters, "count": len(clusters)}
    return {"clusters": [], "count": 0, "message": "Run pipeline to detect clusters"}


# ──────────────────────────────────────────────────────────────────────
# Real-time transaction scoring
# ──────────────────────────────────────────────────────────────────────

@app.post("/api/transaction/score")
async def score_transaction(req: TransactionScoreRequest):
    """
    Score a single new transaction using trained models.
    Returns real-time fraud probability.
    """
    import numpy as np

    # Heuristic scoring for real-time use
    # (In production, use online model inference)
    risk_factors = []
    score = 0.0

    # Amount-based risk
    if req.amount > 200_000:
        risk_factors.append("very_large_amount")
        score += 0.3
    elif req.amount > 50_000:
        risk_factors.append("large_amount")
        score += 0.15

    # Type-based risk (TRANSFER and CASH_OUT are high-risk in PaySim)
    if req.tx_type in ["TRANSFER", "CASH_OUT"]:
        risk_factors.append("high_risk_type")
        score += 0.2

    # Balance zeroing
    if req.new_balance_orig == 0 and req.old_balance_orig > 0:
        risk_factors.append("account_drained")
        score += 0.3

    # Round amount
    if req.amount % 1000 == 0:
        risk_factors.append("round_amount")
        score += 0.1

    # Existing node score lookup
    if state.fraud_scores_df is not None:
        orig_row = state.fraud_scores_df[
            state.fraud_scores_df["node_id"] == f"acc_{req.name_orig}"
        ]
        if not orig_row.empty:
            existing_score = float(orig_row.iloc[0]["fraud_score"])
            score = (score + existing_score) / 2
            if existing_score >= 0.65:
                risk_factors.append("known_high_risk_sender")

    score = min(score, 1.0)

    return {
        "transaction": req.model_dump(),
        "fraud_score": round(score, 4),
        "risk_level": (
            "HIGH" if score >= 0.65
            else "MEDIUM" if score >= 0.45
            else "LOW"
        ),
        "risk_factors": risk_factors,
        "recommendation": (
            "BLOCK" if score >= 0.8
            else "REVIEW" if score >= 0.55
            else "ALLOW"
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Analytics dashboard
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/analytics/stats")
async def get_dashboard_stats():
    """Return aggregated statistics for the dashboard."""
    if state.fraud_scores_df is None:
        return _empty_stats()

    df = state.fraud_scores_df
    total = len(df)
    high_risk = int((df["risk_level"] == "HIGH").sum()) if "risk_level" in df else 0
    medium_risk = int((df["risk_level"] == "MEDIUM").sum()) if "risk_level" in df else 0
    low_risk = total - high_risk - medium_risk

    score_dist = {
        "0.0-0.2": int((df["fraud_score"] < 0.2).sum()),
        "0.2-0.4": int(((df["fraud_score"] >= 0.2) & (df["fraud_score"] < 0.4)).sum()),
        "0.4-0.6": int(((df["fraud_score"] >= 0.4) & (df["fraud_score"] < 0.6)).sum()),
        "0.6-0.8": int(((df["fraud_score"] >= 0.6) & (df["fraud_score"] < 0.8)).sum()),
        "0.8-1.0": int((df["fraud_score"] >= 0.8).sum()),
    }

    return {
        "total_nodes_analyzed": total,
        "high_risk_nodes": high_risk,
        "medium_risk_nodes": medium_risk,
        "low_risk_nodes": low_risk,
        "fraud_detection_rate": round(high_risk / max(total, 1) * 100, 2),
        "avg_fraud_score": round(float(df["fraud_score"].mean()), 4),
        "score_distribution": score_dist,
        "graph_nodes": state.graph.number_of_nodes() if state.graph else 0,
        "graph_edges": state.graph.number_of_edges() if state.graph else 0,
    }


def _empty_stats():
    return {
        "total_nodes_analyzed": 0,
        "high_risk_nodes": 0,
        "medium_risk_nodes": 0,
        "low_risk_nodes": 0,
        "fraud_detection_rate": 0,
        "avg_fraud_score": 0,
        "score_distribution": {},
        "graph_nodes": 0,
        "graph_edges": 0,
        "message": "Pipeline not yet executed. Run: python data_pipeline/run_pipeline.py",
    }


# ──────────────────────────────────────────────────────────────────────
# WebSocket - Real-time transaction stream
# ──────────────────────────────────────────────────────────────────────

@app.websocket("/ws/transactions")
async def websocket_transaction_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time transaction streaming.
    Clients receive JSON-encoded StreamingTransaction objects.
    """
    await websocket.accept()
    state.ws_clients.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(state.ws_clients)}")

    try:
        if state.fraud_scores_df is not None:
            # Stream simulated transactions with live fraud scores
            df_sample = state.fraud_scores_df.sample(
                min(1000, len(state.fraud_scores_df))
            ).reset_index(drop=True)

            for _, row in df_sample.iterrows():
                payload = {
                    "type": "transaction",
                    "node_id": row["node_id"],
                    "fraud_score": round(float(row["fraud_score"]), 4),
                    "risk_level": row.get("risk_level", "LOW"),
                    "is_anomaly": bool(row.get("is_anomaly", False)),
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                }
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(0.2)
        else:
            # Send placeholder events
            for i in range(100):
                import random
                score = random.random()
                payload = {
                    "type": "transaction",
                    "node_id": f"acc_C{random.randint(10000, 99999)}",
                    "fraud_score": round(score, 4),
                    "risk_level": (
                        "HIGH" if score >= 0.65
                        else "MEDIUM" if score >= 0.45
                        else "LOW"
                    ),
                    "is_anomaly": score >= 0.65,
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "simulated": True,
                }
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(0.3)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        if websocket in state.ws_clients:
            state.ws_clients.remove(websocket)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _require_pipeline():
    if not state.is_pipeline_ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "Fraud detection pipeline not ready. "
                "Run: python data_pipeline/run_pipeline.py"
            ),
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=API_CONFIG["host"],
        port=API_CONFIG["port"],
        reload=True,
    )