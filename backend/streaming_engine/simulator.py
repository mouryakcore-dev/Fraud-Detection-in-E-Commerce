"""
backend/streaming_engine/simulator.py

Real-Time Transaction Stream Simulator

Simulates a live e-commerce / financial transaction environment by:
1. Replaying historical PaySim transactions at configurable speed
2. Injecting synthetic fraud bursts for stress testing
3. Emitting transactions via async queue for WebSocket delivery
4. Supporting dynamic graph updates in near real-time
"""

import asyncio
import random
import time
import logging
import numpy as np
import pandas as pd
from typing import AsyncGenerator, Dict, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class StreamingTransaction:
    """Single transaction event in the stream."""
    tx_id: str
    step: int
    tx_type: str
    amount: float
    name_orig: str
    name_dest: str
    old_balance_orig: float
    new_balance_orig: float
    old_balance_dest: float
    new_balance_dest: float
    is_fraud: int
    is_flagged: int
    timestamp: str
    # Derived for real-time scoring
    fraud_score: float = 0.0
    risk_level: str = "LOW"
    is_new_node: bool = False
    community_id: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class TransactionStreamSimulator:
    """
    Simulates a real-time transaction stream from PaySim data.

    Modes:
      - REPLAY: stream historical transactions at configurable rate
      - BURST:  inject synthetic fraud bursts between real transactions
      - HYBRID: combination (default for demos)
    """

    FRAUD_PATTERNS = [
        # Pattern 1: Account drain (CASH_OUT after TRANSFER)
        {
            "name": "account_drain",
            "type_sequence": ["TRANSFER", "CASH_OUT"],
            "amount_multiplier": (5, 20),
            "burst_size": (3, 8),
        },
        # Pattern 2: Rapid small transfers (smurfing)
        {
            "name": "smurfing",
            "type_sequence": ["TRANSFER"],
            "amount_range": (500, 5000),
            "burst_size": (10, 30),
        },
        # Pattern 3: Round-number suspicious transfers
        {
            "name": "round_amounts",
            "type_sequence": ["TRANSFER", "PAYMENT"],
            "amount_range": (10000, 50000),
            "round": True,
            "burst_size": (2, 5),
        },
    ]

    def __init__(
        self,
        df: pd.DataFrame,
        transactions_per_second: float = 5.0,
        burst_probability: float = 0.02,
        burst_size_range: tuple = (5, 25),
        seed: int = 42,
    ):
        """
        Args:
            df:                     Loaded PaySim DataFrame
            transactions_per_second: Base streaming rate
            burst_probability:      Probability of a fraud burst event
            burst_size_range:       (min, max) transactions in a burst
            seed:                   Random seed for reproducibility
        """
        self.df = df.reset_index(drop=True)
        self.tps = transactions_per_second
        self.burst_probability = burst_probability
        self.burst_size_range = burst_size_range

        random.seed(seed)
        np.random.seed(seed)

        self._running = False
        self._tx_queue: asyncio.Queue = None
        self._current_idx = 0
        self._total_streamed = 0
        self._fraud_injected = 0
        self._start_time: Optional[float] = None

        # Callbacks for real-time processing hooks
        self._on_transaction_callbacks: List[Callable] = []

    def add_callback(self, fn: Callable):
        """Register callback invoked for each streamed transaction."""
        self._on_transaction_callbacks.append(fn)

    # ──────────────────────────────────────────────────────────────────
    # Async stream generation
    # ──────────────────────────────────────────────────────────────────

    async def start_stream(self, queue: asyncio.Queue):
        """
        Main streaming coroutine. Call from FastAPI WebSocket handler.

        Args:
            queue: asyncio.Queue to push StreamingTransaction objects
        """
        self._tx_queue = queue
        self._running = True
        self._start_time = time.time()
        self._current_idx = 0
        delay = 1.0 / self.tps

        logger.info(f"Stream started at {self.tps} TPS | "
                    f"Burst prob: {self.burst_probability:.0%}")

        while self._running and self._current_idx < len(self.df):
            # Check for fraud burst injection
            if random.random() < self.burst_probability:
                burst_txs = self._generate_fraud_burst()
                for tx in burst_txs:
                    await queue.put(tx)
                    self._fraud_injected += 1
                    await asyncio.sleep(delay / 4)  # burst faster

            # Stream next real transaction
            row = self.df.iloc[self._current_idx]
            tx = self._row_to_streaming_tx(row)

            await queue.put(tx)
            self._current_idx += 1
            self._total_streamed += 1

            # Fire callbacks
            for cb in self._on_transaction_callbacks:
                try:
                    cb(tx)
                except Exception as e:
                    logger.warning(f"Callback error: {e}")

            await asyncio.sleep(delay)

        logger.info(
            f"Stream complete: {self._total_streamed} real + "
            f"{self._fraud_injected} synthetic fraud transactions"
        )

    async def stream_generator(self) -> AsyncGenerator[Dict, None]:
        """
        Alternative: async generator interface.
        Usage: async for tx in simulator.stream_generator(): process(tx)
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        asyncio.create_task(self.start_stream(queue))

        while True:
            try:
                tx = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield tx.to_dict()
            except asyncio.TimeoutError:
                break

    def stop(self):
        """Stop the stream."""
        self._running = False
        logger.info("Stream stopped.")

    # ──────────────────────────────────────────────────────────────────
    # Transaction construction
    # ──────────────────────────────────────────────────────────────────

    def _row_to_streaming_tx(self, row: pd.Series) -> StreamingTransaction:
        """Convert a PaySim DataFrame row to StreamingTransaction."""
        sim_time = datetime.now() + timedelta(hours=int(row["step"]))

        return StreamingTransaction(
            tx_id=f"tx_{self._current_idx:08d}",
            step=int(row["step"]),
            tx_type=str(row["type"]),
            amount=float(row["amount"]),
            name_orig=str(row["nameOrig"]),
            name_dest=str(row["nameDest"]),
            old_balance_orig=float(row["oldbalanceOrg"]),
            new_balance_orig=float(row["newbalanceOrig"]),
            old_balance_dest=float(row["oldbalanceDest"]),
            new_balance_dest=float(row["newbalanceDest"]),
            is_fraud=int(row["isFraud"]),
            is_flagged=int(row["isFlaggedFraud"]),
            timestamp=sim_time.isoformat(),
        )

    def _generate_fraud_burst(self) -> List[StreamingTransaction]:
        """
        Generate a synthetic fraud burst event.
        Simulates coordinated fraudulent activity.
        """
        pattern = random.choice(self.FRAUD_PATTERNS)
        burst_size = random.randint(*self.burst_size_range)

        # Shared origin account (the fraud ring orchestrator)
        ring_orig = f"C_FRAUD_{random.randint(10000, 99999)}"

        transactions = []
        for i in range(burst_size):
            tx_type = random.choice(pattern.get("type_sequence", ["TRANSFER"]))

            if "amount_range" in pattern:
                amount = random.uniform(*pattern["amount_range"])
            else:
                base_amount = random.uniform(1000, 20000)
                multiplier = random.uniform(*pattern.get("amount_multiplier", (1, 5)))
                amount = base_amount * multiplier

            if pattern.get("round"):
                amount = round(amount / 1000) * 1000

            dest = f"C_DEST_{random.randint(10000, 99999)}"
            old_bal = amount * random.uniform(1.1, 2.0)

            sim_time = datetime.now() + timedelta(minutes=i * 2)

            transactions.append(StreamingTransaction(
                tx_id=f"tx_BURST_{self._fraud_injected}_{i:04d}",
                step=random.randint(1, 700),
                tx_type=tx_type,
                amount=amount,
                name_orig=ring_orig if i % 3 != 0 else f"C_MULE_{i}",
                name_dest=dest,
                old_balance_orig=old_bal,
                new_balance_orig=max(0, old_bal - amount),
                old_balance_dest=0.0,
                new_balance_dest=amount,
                is_fraud=1,
                is_flagged=1 if amount > 200_000 else 0,
                timestamp=sim_time.isoformat(),
                fraud_score=random.uniform(0.7, 0.99),
                risk_level="HIGH",
            ))

        logger.info(
            f"Injected fraud burst: pattern={pattern['name']} | "
            f"size={burst_size}"
        )
        return transactions

    # ──────────────────────────────────────────────────────────────────
    # Stream statistics
    # ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Return current streaming statistics."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            "total_streamed": self._total_streamed,
            "fraud_injected": self._fraud_injected,
            "current_tps": (
                self._total_streamed / elapsed if elapsed > 0 else 0
            ),
            "progress_pct": (
                self._current_idx / len(self.df) * 100
                if len(self.df) > 0 else 0
            ),
            "elapsed_seconds": round(elapsed, 1),
            "is_running": self._running,
        }


class MicroBatchProcessor:
    """
    Collects streaming transactions into micro-batches for
    efficient graph updates and re-scoring without per-transaction overhead.
    """

    def __init__(self, batch_size: int = 50, flush_interval_sec: float = 2.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval_sec
        self._buffer: List[StreamingTransaction] = []
        self._last_flush = time.time()

    def add(self, tx: StreamingTransaction):
        self._buffer.append(tx)

    def should_flush(self) -> bool:
        return (
            len(self._buffer) >= self.batch_size or
            time.time() - self._last_flush >= self.flush_interval
        )

    def flush(self) -> List[StreamingTransaction]:
        batch = self._buffer.copy()
        self._buffer.clear()
        self._last_flush = time.time()
        return batch