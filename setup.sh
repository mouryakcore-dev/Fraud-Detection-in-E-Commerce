#!/bin/bash
# setup.sh — One-shot setup for Antigravity / local development

set -e

echo "=================================="
echo "  FRAUD DETECTION GRAPH SYSTEM"
echo "  Setup Script"
echo "=================================="

# ── Python environment ─────────────────────────────────────────────
echo ""
echo "[1/5] Setting up Python environment..."
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

pip install --upgrade pip -q
pip install -r backend/requirements.txt -q
echo "  ✅ Python dependencies installed"

# ── Create data directories ────────────────────────────────────────
echo ""
echo "[2/5] Creating directories..."
mkdir -p data models experiments/outputs
echo "  ✅ Directories created"

# ── Dataset ───────────────────────────────────────────────────────
echo ""
echo "[3/5] Setting up dataset..."
if [ ! -f "data/paysim.csv" ]; then
    echo "  PaySim dataset not found."
    echo "  Generating synthetic dataset (50,000 transactions)..."
    python data_pipeline/generate_synthetic.py --n 50000
    echo "  ✅ Synthetic dataset ready"
    echo ""
    echo "  NOTE: For real research, download the PaySim dataset from:"
    echo "  https://www.kaggle.com/datasets/ealaxi/paysim1"
    echo "  Place it at: data/paysim.csv"
else
    echo "  ✅ Dataset found"
fi

# ── Frontend ──────────────────────────────────────────────────────
echo ""
echo "[4/5] Setting up frontend..."
if command -v npm &>/dev/null; then
    cd frontend && npm install --silent && cd ..
    echo "  ✅ Frontend dependencies installed"
else
    echo "  ⚠️  npm not found. Install Node.js from https://nodejs.org"
fi

echo ""
echo "[5/5] Setup complete!"
echo ""
echo "=================================="
echo "  NEXT STEPS"
echo "=================================="
echo ""
echo "1. Run the ML pipeline (builds graph, trains embeddings, detects fraud):"
echo "   python data_pipeline/run_pipeline.py --sample 20000"
echo ""
echo "2. Start the backend API:"
echo "   uvicorn backend.api.main:app --reload --port 8000"
echo ""
echo "3. Start the frontend (in a new terminal):"
echo "   cd frontend && npm start"
echo ""
echo "4. Open in browser:"
echo "   http://localhost:3000"
echo ""
echo "5. Run experiment analysis:"
echo "   python experiments/analysis.py"
echo ""
echo "Quick demo (pipeline on small sample):"
echo "   python data_pipeline/run_pipeline.py --sample 5000"
echo ""