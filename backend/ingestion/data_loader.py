"""
backend/ingestion/data_loader.py

Loads, validates, and feature-engineers the PaySim financial transaction
dataset into a clean DataFrame ready for graph construction.

PaySim columns:
  step        - time step (1 step = 1 hour)
  type        - CASH_IN | CASH_OUT | DEBIT | PAYMENT | TRANSFER
  amount      - transaction amount
  nameOrig    - origin account ID
  oldbalanceOrg / newbalanceOrig
  nameDest    - destination account ID
  oldbalanceDest / newbalanceDest
  isFraud     - ground-truth fraud label (1=fraud)
  isFlaggedFraud - system-flagged (large transfers >200k)
"""

import pandas as pd
import numpy as np
import logging
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class PaySimLoader:
    """
    Loads and preprocesses the PaySim CSV dataset.

    Responsibilities:
    - Load raw CSV
    - Validate schema
    - Engineer temporal and behavioral features
    - Return clean transaction DataFrame
    """

    REQUIRED_COLUMNS = [
        "step", "type", "amount", "nameOrig", "oldbalanceOrg",
        "newbalanceOrig", "nameDest", "oldbalanceDest",
        "newbalanceDest", "isFraud", "isFlaggedFraud"
    ]

    TRANSACTION_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]

    def __init__(self, csv_path: str, sample_size: Optional[int] = None):
        """
        Args:
            csv_path: Path to paysim.csv
            sample_size: If set, load only N rows (useful for dev/testing)
        """
        self.csv_path = Path(csv_path)
        self.sample_size = sample_size
        self.df: Optional[pd.DataFrame] = None

    def load(self) -> pd.DataFrame:
        """Load raw CSV and validate schema."""
        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"PaySim dataset not found at {self.csv_path}.\n"
                "Download from: https://www.kaggle.com/datasets/ealaxi/paysim1\n"
                "Or run: python data_pipeline/generate_synthetic.py"
            )

        logger.info(f"Loading PaySim dataset from {self.csv_path}...")
        self.df = pd.read_csv(
            self.csv_path,
            nrows=self.sample_size,
            dtype={
                "nameOrig": str,
                "nameDest": str,
                "isFraud": int,
                "isFlaggedFraud": int,
            }
        )

        self._validate_schema()
        logger.info(f"Loaded {len(self.df):,} transactions | "
                    f"Fraud rate: {self.df['isFraud'].mean():.2%}")
        return self.df

    def _validate_schema(self):
        """Ensure all required columns are present."""
        missing = set(self.REQUIRED_COLUMNS) - set(self.df.columns)
        if missing:
            raise ValueError(f"Missing columns in dataset: {missing}")

    def engineer_features(self) -> pd.DataFrame:
        """
        Add derived features used for both graph construction and ML.

        New columns added:
        - hour_of_day       : step % 24
        - day_of_sim        : step // 24
        - balance_delta_orig: change in origin balance
        - balance_delta_dest: change in destination balance
        - amount_log        : log1p(amount) for scaling
        - is_round_amount   : flag for suspiciously round amounts
        - orig_zeroed_out   : origin account emptied
        - dest_is_merchant  : destination ID starts with 'M'
        - type_encoded      : integer encoding of transaction type
        """
        df = self.df.copy()

        # Temporal features
        df["hour_of_day"] = df["step"] % 24
        df["day_of_sim"] = df["step"] // 24

        # Balance behavior features
        df["balance_delta_orig"] = df["newbalanceOrig"] - df["oldbalanceOrg"]
        df["balance_delta_dest"] = df["newbalanceDest"] - df["oldbalanceDest"]
        df["amount_log"] = np.log1p(df["amount"])

        # Anomaly-indicative flags
        df["is_round_amount"] = (df["amount"] % 1000 == 0).astype(int)
        df["orig_zeroed_out"] = (
            (df["newbalanceOrig"] == 0) & (df["oldbalanceOrg"] > 0)
        ).astype(int)
        df["dest_is_merchant"] = df["nameDest"].str.startswith("M").astype(int)

        # Transaction type encoding
        type_map = {t: i for i, t in enumerate(self.TRANSACTION_TYPES)}
        df["type_encoded"] = df["type"].map(type_map).fillna(-1).astype(int)

        # Fraud-only transaction types in PaySim
        df["is_risky_type"] = df["type"].isin(["TRANSFER", "CASH_OUT"]).astype(int)

        self.df = df
        logger.info("Feature engineering complete. "
                    f"Total features: {len(df.columns)}")
        return df

    def get_graph_ready_df(self) -> pd.DataFrame:
        """
        Full pipeline: load + engineer features.
        Returns DataFrame ready for graph_builder module.
        """
        self.load()
        self.engineer_features()
        return self.df

    def get_fraud_stats(self) -> dict:
        """Return summary statistics about fraud in dataset."""
        if self.df is None:
            raise RuntimeError("Call load() first.")
        return {
            "total_transactions": len(self.df),
            "fraud_count": int(self.df["isFraud"].sum()),
            "fraud_rate": float(self.df["isFraud"].mean()),
            "fraud_by_type": self.df.groupby("type")["isFraud"].mean().to_dict(),
            "avg_fraud_amount": float(
                self.df[self.df["isFraud"] == 1]["amount"].mean()
            ),
            "avg_legit_amount": float(
                self.df[self.df["isFraud"] == 0]["amount"].mean()
            ),
            "step_range": (int(self.df["step"].min()), int(self.df["step"].max())),
        }

    def get_train_test_split(
        self,
        test_ratio: float = 0.2,
        temporal_split: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split data into train/test sets.

        Args:
            test_ratio: Fraction of data for test set
            temporal_split: If True, split by time (more realistic).
                            If False, random split.
        """
        if self.df is None:
            raise RuntimeError("Call load() first.")

        if temporal_split:
            split_step = self.df["step"].quantile(1 - test_ratio)
            train = self.df[self.df["step"] <= split_step]
            test = self.df[self.df["step"] > split_step]
        else:
            from sklearn.model_selection import train_test_split
            train, test = train_test_split(
                self.df, test_size=test_ratio, random_state=42,
                stratify=self.df["isFraud"]
            )

        logger.info(f"Train: {len(train):,} | Test: {len(test):,}")
        return train, test