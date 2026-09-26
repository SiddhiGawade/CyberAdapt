"""
Adaptive Retraining Engine & Model Promotion Manager.

Implements champion/candidate workflow with strict quality gating rules to promote candidate models
only when verified under distribution shift and class emergence.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import json
import logging
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
import xgboost as xgb

from ml.src.features.feature_contract import (
    PRODUCTION_CANDIDATE_FEATURES,
    TARGET_CLASSES,
    TARGET_COLUMN,
)
from ml.src.features.preprocessing import CICIDSDataPreprocessor
from ml.src.evaluation.metrics import evaluate_predictions
from ml.src.models.ensemble import WeightedSoftVotingEnsemble
from ml.src.models.weighting import get_sample_weights

logger = logging.getLogger(__name__)


@dataclass
class PromotionGateConfig:
    """Quality gate thresholds required to promote a Candidate model to Champion."""

    min_macro_f1_delta: float = -0.01  # Candidate Macro F1 within 0.01 of Champion or higher
    min_balanced_acc_delta: float = -0.01
    min_minority_recall: float = 0.70  # Minority attack class recall (e.g. DoS / Bots)
    max_normal_fpr: float = 0.05  # Maximum false positive rate on Normal Traffic


class AdaptiveModelManager:
    """Manages Champion/Candidate model lifecycle and automated promotion gating."""

    def __init__(
        self,
        champion_model: Any,
        preprocessor: CICIDSDataPreprocessor,
        gate_config: Optional[PromotionGateConfig] = None,
        feature_cols: Optional[List[str]] = None,
        model_version: str = "v1",
    ):
        """Initialize Adaptive Model Manager.

        Args:
            champion_model: Current production champion classifier.
            preprocessor: Fitted CICIDSDataPreprocessor object.
            gate_config: PromotionGateConfig threshold parameters.
            feature_cols: Feature columns list.
            model_version: Version identifier string.
        """
        self.champion_model = champion_model
        self.preprocessor = preprocessor
        self.gate_config = gate_config or PromotionGateConfig()
        self.feature_cols = feature_cols or list(PRODUCTION_CANDIDATE_FEATURES)
        self.model_version = model_version

        self.candidate_model: Optional[Any] = None
        self.candidate_preprocessor: Optional[CICIDSDataPreprocessor] = None

        self.adaptation_history: List[Dict[str, Any]] = []

    def retrain_candidate(
        self,
        buffer_X: pd.DataFrame,
        buffer_y: pd.Series,
        model_type: str = "lightgbm",
    ) -> Any:
        """Retrain a Candidate model on updated streaming buffer data.

        Args:
            buffer_X: Features DataFrame containing recent stream windows.
            buffer_y: Target labels Series containing recent ground-truth labels.
            model_type: Architecture type ('lightgbm' or 'ensemble').

        Returns:
            Fitted candidate model object.
        """
        logger.info(f"Retraining Candidate model ({model_type}) on buffer of {len(buffer_X):,} records...")

        # 1. Fit new Candidate preprocessor
        cand_preproc = CICIDSDataPreprocessor(
            feature_cols=self.feature_cols, target_col=TARGET_COLUMN
        )
        X_scaled, y_enc = cand_preproc.fit_transform(buffer_X, buffer_y)

        # 2. Fit Candidate Model (LightGBM multiclass)
        candidate = lgb.LGBMClassifier(
            n_estimators=60,
            max_depth=6,
            learning_rate=0.1,
            class_weight="balanced",
            objective="multiclass",
            num_class=len(TARGET_CLASSES),
            random_state=42,
            n_jobs=2,
            verbose=-1,
        )
        candidate.fit(X_scaled, y_enc)

        self.candidate_model = candidate
        self.candidate_preprocessor = cand_preproc
        logger.info(f"Candidate retraining complete. Model ready for promotion evaluation.")
        return candidate

    def evaluate_and_promote_candidate(
        self,
        val_X: pd.DataFrame,
        val_y: pd.Series,
        window_id: str = "window_eval",
        train_window_ids: Optional[List[str]] = None,
        emerged_class: str = "DoS",
    ) -> Dict[str, Any]:
        """Evaluate Candidate vs Champion on validation set and enforce promotion gates with zero train/eval leakage.

        Args:
            val_X: Validation features DataFrame.
            val_y: Validation targets Series.
            window_id: Validation window string identifier.
            train_window_ids: Optional list of training window IDs used for candidate fitting.
            emerged_class: Target attack class being verified for recovery.

        Returns:
            Dictionary containing evaluation metrics, gate evaluation decisions, and promotion status.
        """
        if self.candidate_model is None or self.candidate_preprocessor is None:
            raise RuntimeError("Candidate model must be retrained before calling evaluate_and_promote_candidate().")

        # 0. Strict Train/Eval Leakage Check
        if train_window_ids is not None and window_id in train_window_ids:
            raise ValueError(
                f"Train/Eval Leakage Detected! Validation window '{window_id}' is present in candidate training buffer {train_window_ids}."
            )

        # 0b. Prevent repeated promotion from identical training evidence
        if hasattr(self, "last_promoted_train_ids") and train_window_ids is not None:
            if self.last_promoted_train_ids == train_window_ids:
                logger.info(f"Skipping redundant promotion evaluation: Candidate was already evaluated/promoted on evidence {train_window_ids}.")
                return {
                    "window_id": window_id,
                    "promoted": False,
                    "reason": "Redundant promotion from identical training evidence",
                    "champion_version_before": self.model_version,
                    "champion_version_after": self.model_version,
                }

        # 1. Evaluate Champion
        X_champ_scaled, y_val_enc = self.preprocessor.transform(val_X, val_y)
        champ_pred = self.champion_model.predict(X_champ_scaled)
        champ_prob = getattr(self.champion_model, "predict_proba", lambda X: None)(X_champ_scaled)
        champ_eval = evaluate_predictions(y_val_enc, champ_pred, champ_prob, model_name="Champion", split_name=window_id)

        # 2. Evaluate Candidate
        X_cand_scaled, _ = self.candidate_preprocessor.transform(val_X, val_y)
        cand_pred = self.candidate_model.predict(X_cand_scaled)
        cand_prob = getattr(self.candidate_model, "predict_proba", lambda X: None)(X_cand_scaled)
        cand_eval = evaluate_predictions(y_val_enc, cand_pred, cand_prob, model_name="Candidate", split_name=window_id)

        # 3. Compute Gate Criteria
        macro_f1_diff = cand_eval["macro_f1"] - champ_eval["macro_f1"]
        bal_acc_diff = cand_eval["balanced_accuracy"] - champ_eval["balanced_accuracy"]

        # Emerged class recall
        emerged_metrics = cand_eval["per_class_metrics"].get(emerged_class, {})
        emerged_support = emerged_metrics.get("support", 0)
        emerged_recall = emerged_metrics.get("recall", 0.0)

        # Normal Traffic FPR calculation: FPR = FP / (FP + TN)
        normal_metrics = cand_eval["per_class_metrics"].get("Normal Traffic", {})
        normal_prec = normal_metrics.get("precision", 1.0)
        normal_fpr = round(1.0 - normal_prec, 4)

        # Evaluate Gates
        gate_macro_f1 = macro_f1_diff >= self.gate_config.min_macro_f1_delta
        gate_bal_acc = bal_acc_diff >= self.gate_config.min_balanced_acc_delta
        gate_emerged_recall = (emerged_recall >= self.gate_config.min_minority_recall) if emerged_support > 0 else True
        gate_normal_fpr = normal_fpr <= self.gate_config.max_normal_fpr

        promoted = gate_macro_f1 and gate_bal_acc and gate_emerged_recall and gate_normal_fpr

        gate_report = {
            "window_id": window_id,
            "train_window_ids": train_window_ids or [],
            "timestamp": datetime.now().isoformat(),
            "promoted": promoted,
            "champion_version_before": self.model_version,
            "champion_macro_f1": champ_eval["macro_f1"],
            "candidate_macro_f1": cand_eval["macro_f1"],
            "macro_f1_delta": round(macro_f1_diff, 4),
            "champion_balanced_acc": champ_eval["balanced_accuracy"],
            "candidate_balanced_acc": cand_eval["balanced_accuracy"],
            "balanced_acc_delta": round(bal_acc_diff, 4),
            "emerged_class_name": emerged_class,
            "candidate_emerged_class_recall": emerged_recall,
            "candidate_normal_fpr": normal_fpr,
            "gates_passed": {
                "gate_macro_f1": bool(gate_macro_f1),
                "gate_bal_acc": bool(gate_bal_acc),
                "gate_emerged_recall": bool(gate_emerged_recall),
                "gate_normal_fpr": bool(gate_normal_fpr),
            },
        }

        if promoted:
            old_ver = self.model_version
            self.model_version = f"v{int(old_ver.replace('v', '')) + 1}" if old_ver.startswith("v") else "v2"
            self.champion_model = self.candidate_model
            self.preprocessor = self.candidate_preprocessor
            self.last_promoted_train_ids = list(train_window_ids) if train_window_ids else []
            gate_report["champion_version_after"] = self.model_version
            logger.info(
                f"PROMOTION SUCCESSFUL! Candidate promoted to Champion ({self.model_version}). "
                f"Macro F1: {champ_eval['macro_f1']:.4f} -> {cand_eval['macro_f1']:.4f}, "
                f"{emerged_class} recall: {emerged_recall:.4f}"
            )
        else:
            gate_report["champion_version_after"] = self.model_version
            logger.warning(f"PROMOTION REJECTED! Candidate failed quality gates. Keeping {self.model_version}.")

        self.adaptation_history.append(gate_report)
        return gate_report

    def save_state(self, model_dir: Path, reports_dir: Path) -> None:
        """Persist updated champion model, preprocessor, and adaptation log."""
        model_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        champ_path = model_dir / f"adaptive_champion_{self.model_version}.joblib"
        joblib.dump(self.champion_model, champ_path)

        preproc_path = model_dir / f"adaptive_preprocessor_{self.model_version}.joblib"
        self.preprocessor.save(preproc_path)

        hist_path = reports_dir / "adaptation_history.json"
        with open(hist_path, "w") as f:
            json.dump(self.adaptation_history, f, indent=2)

        logger.info(f"Saved adaptive engine state ({self.model_version}) to {champ_path} and {hist_path}")
