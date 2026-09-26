"""
Data Preprocessing Pipeline Module for Adaptive Cyber Threat Intelligence.

Provides zero-leakage scaling, label encoding, nan/infinity imputation, and model deployment persistence.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import joblib
import logging
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler

from ml.src.features.feature_contract import (
    PRODUCTION_CANDIDATE_FEATURES,
    TARGET_CLASSES,
    TARGET_COLUMN,
)

logger = logging.getLogger(__name__)


class CICIDSDataPreprocessor:
    """Production preprocessor for CICIDS2017 dataset enforcing zero-leakage training-serving consistency."""

    def __init__(
        self,
        feature_cols: Optional[List[str]] = None,
        target_col: str = TARGET_COLUMN,
        class_order: Optional[List[str]] = None,
    ):
        """Initialize preprocessor.

        Args:
            feature_cols: List of feature names to select. Defaults to PRODUCTION_CANDIDATE_FEATURES.
            target_col: Name of target column. Defaults to TARGET_COLUMN.
            class_order: Canonical list of target class labels to enforce fixed integer ordering.
        """
        self.feature_cols = feature_cols or list(PRODUCTION_CANDIDATE_FEATURES)
        self.target_col = target_col
        self.class_order = class_order or list(TARGET_CLASSES)

        self.scaler = StandardScaler()
        self.label_encoder = LabelEncoder()
        self.is_fitted = False

        # Class maps
        self.class_to_idx: Dict[str, int] = {c: i for i, c in enumerate(self.class_order)}
        self.idx_to_class: Dict[int, str] = {i: c for i, c in enumerate(self.class_order)}

    def fit(self, X: pd.DataFrame, y: Optional[Union[pd.Series, np.ndarray]] = None) -> "CICIDSDataPreprocessor":
        """Fit feature scaler and label encoder strictly on training data.

        Args:
            X: Input training features DataFrame.
            y: Optional training target labels.

        Returns:
            Fitted CICIDSDataPreprocessor object.
        """
        X_sub = X[self.feature_cols].copy()
        X_clean = self._clean_numeric(X_sub)

        self.scaler.fit(X_clean)

        if y is not None:
            if isinstance(y, pd.Series):
                y_vals = y.values
            else:
                y_vals = y
            self.label_encoder.fit(self.class_order)

        self.is_fitted = True
        logger.info(f"Fitted preprocessor on {len(X)} training records with {len(self.feature_cols)} features.")
        return self

    def transform(
        self, X: pd.DataFrame, y: Optional[Union[pd.Series, np.ndarray]] = None
    ) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        """Transform features and optional labels using fitted scaler.

        Args:
            X: Input features DataFrame.
            y: Optional target labels Series/ndarray.

        Returns:
            X_scaled ndarray, or (X_scaled, y_encoded) tuple if y is provided.
        """
        if not self.is_fitted:
            raise RuntimeError("CICIDSDataPreprocessor must be fitted before calling transform().")

        X_sub = X[self.feature_cols].copy()
        X_clean = self._clean_numeric(X_sub)
        X_scaled = self.scaler.transform(X_clean)

        if y is not None:
            if isinstance(y, pd.Series):
                y_str = y.astype(str).values
            else:
                y_str = np.array(y, dtype=str)

            # Map target labels deterministically using class_to_idx
            y_encoded = np.array([self.class_to_idx.get(lbl, 0) for lbl in y_str], dtype=int)
            return X_scaled, y_encoded

        return X_scaled

    def fit_transform(
        self, X: pd.DataFrame, y: Optional[Union[pd.Series, np.ndarray]] = None
    ) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        """Fit scaler on X (and y if provided) and transform in one step.

        Args:
            X: Input features DataFrame.
            y: Optional target labels.

        Returns:
            X_scaled ndarray or (X_scaled, y_encoded) tuple.
        """
        return self.fit(X, y).transform(X, y)

    def inverse_transform_target(self, y_encoded: np.ndarray) -> List[str]:
        """Convert integer class indices back to string attack class names.

        Args:
            y_encoded: Array of integer class predictions.

        Returns:
            List of string class names.
        """
        return [self.idx_to_class.get(int(idx), "Unknown") for idx in y_encoded]

    def _clean_numeric(self, df: pd.DataFrame) -> pd.DataFrame:
        """Replace Inf / NaN values cleanly to prevent numerical instability."""
        df_clean = df.copy()
        # Replace positive and negative infinity with NaN, then fillna with 0
        df_clean = df_clean.replace([np.inf, -np.inf], np.nan)
        df_clean = df_clean.fillna(0.0)
        return df_clean

    def save(self, filepath: Path) -> None:
        """Serialize preprocessor object to disk using joblib.

        Args:
            filepath: Target file path.
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, filepath)
        logger.info(f"Saved preprocessor artifact to {filepath}")

    @classmethod
    def load(cls, filepath: Path) -> "CICIDSDataPreprocessor":
        """Load serialized preprocessor object from disk.

        Args:
            filepath: Path to serialized preprocessor.

        Returns:
            Loaded CICIDSDataPreprocessor object.
        """
        preprocessor = joblib.load(filepath)
        logger.info(f"Loaded preprocessor artifact from {filepath}")
        return preprocessor
