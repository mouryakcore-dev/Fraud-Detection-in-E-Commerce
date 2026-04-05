"""
data_pipeline/generate_synthetic.py

Generates a synthetic PaySim-compatible dataset for development/testing
when the real PaySim dataset is not available.

Generates realistic transaction patterns including:
- Normal account transfers and payments
- Fraudulent account draining sequences
- Money mule networks
- Smurfing (many small transactions)

Output: data/paysim.csv (PaySim-compatible schema)
"""

import numpy as np
import pandas as pd
import random
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TRANSACTION_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]
FRAUD_TYPES = ["TRANSFER", "CASH_OUT"]


def generate_synthetic_paysim(
    n_transactions: int = 50_000,
    fraud_rate: float = 0.013,
    n_accounts: int = 5_000,
    n_merchants: int = 500,
    n_steps: int = 744,
    output_path: str = "data/paysim.csv",
    seed: int = 42
) -> pd.DataFrame:
    """
    Generate a synthetic PaySim-compatible transaction dataset.

    Args:
        n_transactions: Total number of transactions to generate
        fraud_rate:     Target fraud rate (PaySim ~1.3%)
        n_accounts:     Number of unique customer accounts
        n_merchants:    Number of merchant accounts
        n_steps:        Time steps (PaySim = 744 hours = 31 days)
        output_path:    Output CSV path
        seed:           Random seed

    Returns:
        DataFrame with PaySim schema
    """
    np.random.seed(seed)
    random.seed(seed)

    # Account ID pools
    accounts = [f"C{str(i).zfill(10)}" for i in range(1, n_accounts + 1)]
    merchants = [f"M{str(i).zfill(9)}" for i in range(1, n_merchants + 1)]

    records = []
    n_fraud = int(n_transactions * fraud_rate)
    n_normal = n_transactions - n_fraud

    logger.info(f"Generating {n_normal:,} normal + {n_fraud:,} fraud transactions...")

    # ── Generate normal transactions ───────────────────────────────
    for i in range(n_normal):
        step = random.randint(1, n_steps)
        tx_type = random.choices(
            TRANSACTION_TYPES,
            weights=[0.35, 0.20, 0.10, 0.25, 0.10]
        )[0]
        amount = _sample_amount(tx_type, is_fraud=False)
        orig = random.choice(accounts)
        dest = (random.choice(merchants) if tx_type in ["PAYMENT", "DEBIT"]
                else random.choice(accounts))

        old_bal_orig = random.uniform(amount, amount * 5)
        new_bal_orig = old_bal_orig - amount if tx_type != "CASH_IN" else old_bal_orig + amount
        old_bal_dest = random.uniform(0, 100_000)
        new_bal_dest = old_bal_dest + amount

        records.append({
            "step": step,
            "type": tx_type,
            "amount": round(amount, 2),
            "nameOrig": orig,
            "oldbalanceOrg": round(old_bal_orig, 2),
            "newbalanceOrig": round(max(0, new_bal_orig), 2),
            "nameDest": dest,
            "oldbalanceDest": round(old_bal_dest, 2),
            "newbalanceDest": round(new_bal_dest, 2),
            "isFraud": 0,
            "isFlaggedFraud": 0,
        })

    # ── Generate fraud transactions ────────────────────────────────
    fraud_patterns = [
        _generate_account_drain_fraud,
        _generate_smurfing_fraud,
        _generate_money_mule_fraud,
    ]

    fraud_accounts = random.sample(accounts, min(50, len(accounts)))
    frauds_added = 0

    while frauds_added < n_fraud:
        pattern_fn = random.choice(fraud_patterns)
        fraud_txs = pattern_fn(
            fraud_accounts, accounts, merchants, n_steps
        )
        for tx in fraud_txs:
            if frauds_added >= n_fraud:
                break
            records.append(tx)
            frauds_added += 1

    # Create DataFrame
    df = pd.DataFrame(records)
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)  # shuffle

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    actual_fraud_rate = df["isFraud"].mean()
    logger.info(
        f"Synthetic dataset generated: {len(df):,} transactions | "
        f"Fraud rate: {actual_fraud_rate:.2%} | Saved to {output_path}"
    )
    return df


def _sample_amount(tx_type: str, is_fraud: bool) -> float:
    """Sample transaction amount based on type and fraud status."""
    if is_fraud:
        # Fraud transactions tend to be larger
        return np.random.lognormal(mean=10.5, sigma=1.2)
    if tx_type == "CASH_IN":
        return np.random.lognormal(mean=7.0, sigma=1.5)
    elif tx_type == "CASH_OUT":
        return np.random.lognormal(mean=8.0, sigma=1.3)
    elif tx_type == "PAYMENT":
        return np.random.lognormal(mean=6.5, sigma=1.0)
    elif tx_type == "TRANSFER":
        return np.random.lognormal(mean=9.0, sigma=1.8)
    return np.random.lognormal(mean=7.5, sigma=1.2)


def _generate_account_drain_fraud(
    fraud_accounts, all_accounts, merchants, n_steps
) -> list:
    """Pattern: Transfer then CASH_OUT to drain account."""
    orig = random.choice(fraud_accounts)
    dest = random.choice(all_accounts)
    amount = random.uniform(10_000, 500_000)
    step = random.randint(1, n_steps)

    old_bal = amount * random.uniform(0.9, 1.1)

    tx1 = {
        "step": step,
        "type": "TRANSFER",
        "amount": round(amount, 2),
        "nameOrig": orig,
        "oldbalanceOrg": round(old_bal, 2),
        "newbalanceOrig": 0.0,
        "nameDest": dest,
        "oldbalanceDest": 0.0,
        "newbalanceDest": round(amount, 2),
        "isFraud": 1,
        "isFlaggedFraud": 1 if amount > 200_000 else 0,
    }
    tx2 = {
        "step": step + 1,
        "type": "CASH_OUT",
        "amount": round(amount, 2),
        "nameOrig": dest,
        "oldbalanceOrg": round(amount, 2),
        "newbalanceOrig": 0.0,
        "nameDest": random.choice(merchants),
        "oldbalanceDest": 0.0,
        "newbalanceDest": round(amount, 2),
        "isFraud": 1,
        "isFlaggedFraud": 1 if amount > 200_000 else 0,
    }
    return [tx1, tx2]


def _generate_smurfing_fraud(
    fraud_accounts, all_accounts, merchants, n_steps
) -> list:
    """Pattern: many small transfers to avoid detection."""
    orig = random.choice(fraud_accounts)
    step = random.randint(1, n_steps)
    n_transfers = random.randint(5, 15)
    amount_each = random.uniform(500, 4999)  # stay under threshold

    txs = []
    for i in range(n_transfers):
        dest = random.choice(all_accounts)
        txs.append({
            "step": step + i,
            "type": "TRANSFER",
            "amount": round(amount_each, 2),
            "nameOrig": orig,
            "oldbalanceOrg": round(amount_each * (n_transfers - i), 2),
            "newbalanceOrig": round(amount_each * (n_transfers - i - 1), 2),
            "nameDest": dest,
            "oldbalanceDest": 0.0,
            "newbalanceDest": round(amount_each, 2),
            "isFraud": 1,
            "isFlaggedFraud": 0,
        })
    return txs


def _generate_money_mule_fraud(
    fraud_accounts, all_accounts, merchants, n_steps
) -> list:
    """Pattern: chain of transfers through mule accounts."""
    chain_length = random.randint(3, 6)
    amount = random.uniform(5_000, 50_000)
    step = random.randint(1, n_steps)

    chain = random.sample(fraud_accounts, min(chain_length, len(fraud_accounts)))

    txs = []
    for i in range(len(chain) - 1):
        txs.append({
            "step": step + i,
            "type": "TRANSFER",
            "amount": round(amount * 0.95 ** i, 2),
            "nameOrig": chain[i],
            "oldbalanceOrg": round(amount * 0.95 ** i * 1.1, 2),
            "newbalanceOrig": 0.0,
            "nameDest": chain[i + 1],
            "oldbalanceDest": 0.0,
            "newbalanceDest": round(amount * 0.95 ** i, 2),
            "isFraud": 1,
            "isFlaggedFraud": 0,
        })
    return txs


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50_000,
                        help="Number of transactions (default: 50000)")
    parser.add_argument("--output", default="data/paysim.csv",
                        help="Output CSV path")
    args = parser.parse_args()

    generate_synthetic_paysim(
        n_transactions=args.n,
        output_path=args.output,
    )
    print(f"\n✅ Synthetic dataset ready at: {args.output}")
    print("Run pipeline: python data_pipeline/run_pipeline.py --sample 20000")