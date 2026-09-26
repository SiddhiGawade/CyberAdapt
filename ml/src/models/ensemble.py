"""
Weighted Soft Voting Ensemble Module for Cyber Threat Intelligence.

Combines predicted class probability distributions from tree-based estimators
(LightGBM, XGBoost, Random Forest) using validation Macro F1 optimized weights.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import joblib
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class WeightedSoftVotingEnsemble:
    """Production Weighted Soft Voting Ensemble classifier."""

    def __init__(
        self,
        estimators: List[Tuple[str, Any]],
        weights: Optional[List[float]] = None,
        class_order: Optional[List[str]] = None,
    ):
        """Initialize ensemble.

        Args:
            estimators: List of (name, model_object) tuples.
            weights: Optional float weights for each estimator. Must sum to 1.0 or will be normalized.
            class_order: Canonical list of string class names.
        """
        self.estimators = estimators
        self.class_order = class_order
        self.num_estimators = len(estimators)

        if weights is None:
            self.weights = np.ones(self.num_estimators) / self.num_estimators
        else:
            weights_arr = np.array(weights, dtype=float)
            self.weights = weights_arr / np.sum(weights_arr)

        logger.info(
            f"Initialized WeightedSoftVotingEnsemble with {self.num_estimators} estimators. "
            f"Weights: {dict(zip([e[0] for e in estimators], self.weights))}"
        )

    def fit(
        self, X: np.ndarray, y: np.ndarray, sample_weights: Optional[np.ndarray] = None
    ) -> "WeightedSoftVotingEnsemble":
        """Fit all base estimators if they are not already fitted.

        Args:
            X: Preprocessed training features ndarray.
            y: Integer encoded training targets ndarray.
            sample_weights: Optional sample weight vector.

        Returns:
            Fitted ensemble instance.
        """
        for name, model in self.estimators:
            logger.info(f"Fitting ensemble base estimator: {name}...")
            if sample_weights is not None and hasattr(model, "fit"):
                try:
                    model.fit(X, y, sample_weight=sample_weights)
                except TypeError:
                    model.fit(X, y)
            elif hasattr(model, "fit"):
                model.fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Compute weighted average class probabilities across base estimators.

        Args:
            X: Input feature array (shape N, D).

        Returns:
            Probabilities array of shape (N, K).
        """
        combined_proba = None

        for idx, (name, model) in enumerate(self.estimators):
            if not hasattr(model, "predict_proba"):
                raise AttributeError(f"Base estimator '{name}' does not implement predict_proba().")

            proba = model.predict_proba(X)
            weight = self.weights[idx]

            if combined_proba is None:
                combined_proba = weight * proba
            else:
                combined_proba += weight * proba

        return combined_proba

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict target class indices with maximum weighted probability.

        Args:
            X: Input feature array (shape N, D).

        Returns:
            1D array of predicted class index integers.
        """
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)

    def save(self, filepath: Path) -> None:
        """Serialize ensemble artifact using joblib."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, filepath)
        logger.info(f"Saved ensemble model artifact to {filepath}")

    @classmethod
    def load(cls, filepath: Path) -> "WeightedSoftVotingEnsemble":
        """Load ensemble artifact from disk."""
        ensemble = joblib.load(filepath)
        logger.info(f"Loaded ensemble model artifact from {filepath}")
        return ensemble
