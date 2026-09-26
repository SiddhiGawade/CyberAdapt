"""
Evaluation Metrics & Performance Benchmarking Module.

Provides comprehensive metric calculation: Macro F1, Weighted F1, Balanced Accuracy,
per-class recall/precision/F1, confusion matrix, ROC-AUC, PR-AUC, and inference latency.
"""

from typing import Dict, List, Optional, Any, Union, Tuple
import time
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from ml.src.features.feature_contract import TARGET_CLASSES


def evaluate_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: Optional[np.ndarray] = None,
    inference_time_sec: float = 0.0,
    model_name: str = "Model",
    split_name: str = "ordered_holdout_proxy",
    class_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Calculate thorough classification metrics across all classes and minority subsets.

    Args:
        y_true: True integer class labels (shape N,).
        y_pred: Predicted integer class labels (shape N,).
        y_prob: Optional predicted class probabilities (shape N, K).
        inference_time_sec: Total duration in seconds taken for inference pass over test set.
        model_name: Name identifier for model.
        split_name: Evaluation split strategy label.
        class_names: List of string class names.

    Returns:
        Structured dictionary containing summary metrics, per-class breakdown, and confusion matrices.
    """
    labels = class_names or TARGET_CLASSES
    num_classes = len(labels)
    num_samples = len(y_true)

    # Core Macro and Weighted Metrics
    acc = float(accuracy_score(y_true, y_pred))
    bal_acc = float(balanced_accuracy_score(y_true, y_pred))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    weighted_f1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
    macro_prec = float(precision_score(y_true, y_pred, average="macro", zero_division=0))
    macro_rec = float(recall_score(y_true, y_pred, average="macro", zero_division=0))

    # Per-Class Precision, Recall, F1, Support
    report_dict = classification_report(
        y_true,
        y_pred,
        labels=list(range(num_classes)),
        target_names=labels,
        output_dict=True,
        zero_division=0,
    )

    per_class_metrics = {}
    minority_recalls = {}
    for idx, cname in enumerate(labels):
        if cname in report_dict:
            rec = float(report_dict[cname]["recall"])
            prec = float(report_dict[cname]["precision"])
            f1 = float(report_dict[cname]["f1-score"])
            supp = int(report_dict[cname]["support"])
            per_class_metrics[cname] = {
                "precision": prec,
                "recall": rec,
                "f1_score": f1,
                "support": supp,
            }
            # Track minority recalls (Bots, Web Attacks, Brute Force)
            if cname in ["Bots", "Web Attacks", "Brute Force"]:
                minority_recalls[f"recall_{cname.lower().replace(' ', '_')}"] = rec

    # Confusion Matrix
    cm_raw = confusion_matrix(y_true, y_pred, labels=list(range(num_classes)))
    # Normalized confusion matrix (row-wise normalized by true counts)
    cm_norm = np.zeros_like(cm_raw, dtype=float)
    row_sums = cm_raw.sum(axis=1, keepdims=True)
    nonzero_rows = row_sums > 0
    cm_norm[nonzero_rows.squeeze()] = cm_raw[nonzero_rows.squeeze()] / row_sums[nonzero_rows.squeeze()]

    # Multiclass ROC-AUC (OVR)
    roc_auc_val = None
    if y_prob is not None:
        try:
            # Check if all classes are present in y_true
            present_classes = np.unique(y_true)
            if len(present_classes) == num_classes:
                roc_auc_val = float(
                    roc_auc_score(y_true, y_prob, multi_class="ovr", average="macro")
                )
        except Exception as e:
            logger.warning(f"Could not calculate ROC-AUC for {model_name}: {e}")

    # Latency per sample in milliseconds
    latency_ms_per_sample = (
        (inference_time_sec * 1000.0) / num_samples if num_samples > 0 else 0.0
    )

    result = {
        "model_name": model_name,
        "split_strategy": split_name,
        "num_test_samples": num_samples,
        "accuracy": acc,
        "balanced_accuracy": bal_acc,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "macro_precision": macro_prec,
        "macro_recall": macro_rec,
        "roc_auc_macro": roc_auc_val,
        "inference_time_total_sec": float(inference_time_sec),
        "inference_latency_ms_per_sample": float(latency_ms_per_sample),
        "minority_recalls": minority_recalls,
        "per_class_metrics": per_class_metrics,
        "confusion_matrix_raw": cm_raw.tolist(),
        "confusion_matrix_norm": cm_norm.tolist(),
    }

    return result


def benchmark_model_inference(
    model: Any, X_test: np.ndarray, num_runs: int = 1
) -> Tuple[np.ndarray, Optional[np.ndarray], float]:
    """Execute timed inference benchmark on test set.

    Args:
        model: Trained classifier object with predict / predict_proba.
        X_test: Preprocessed feature array.
        num_runs: Number of benchmark passes.

    Returns:
        Tuple of (y_pred, y_prob, elapsed_time_seconds)
    """
    t0 = time.perf_counter()
    for _ in range(num_runs):
        y_pred = model.predict(X_test)
    t1 = time.perf_counter()

    elapsed = (t1 - t0) / num_runs

    y_prob = None
    if hasattr(model, "predict_proba"):
        try:
            y_prob = model.predict_proba(X_test)
        except Exception:
            y_prob = None

    return y_pred, y_prob, elapsed
