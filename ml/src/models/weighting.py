"""
Class Imbalance & Sample Weighting Utilities for Cyber Threat Intelligence ML.

Computes balanced class weights and sample weight arrays for models handling severe class imbalance.
"""

from typing import Dict, List, Optional, Union
import numpy as np
import pandas as pd
from sklearn.utils.class_weight import compute_class_weight

from ml.src.features.feature_contract import TARGET_CLASSES


def get_balanced_class_weight_dict(
    y: Union[pd.Series, np.ndarray], class_order: Optional[List[str]] = None
) -> Dict[int, float]:
    """Compute balanced class weights dictionary mapping integer class index to weight.

    Args:
        y: Integer encoded or string target labels array.
        class_order: Ordered list of string class names.

    Returns:
        Dict mapping integer class index to computed weight.
    """
    classes_list = class_order or TARGET_CLASSES

    if isinstance(y[0], (str, np.str_)):
        unique_classes = np.array(classes_list)
        weights = compute_class_weight(class_weight="balanced", classes=unique_classes, y=y)
        weight_dict = {i: float(w) for i, w in enumerate(weights)}
    else:
        unique_classes = np.array(list(range(len(classes_list))))
        weights = compute_class_weight(class_weight="balanced", classes=unique_classes, y=y)
        weight_dict = {int(c): float(w) for c, w in zip(unique_classes, weights)}

    return weight_dict


def get_sample_weights(
    y_encoded: np.ndarray, class_weight_dict: Optional[Dict[int, float]] = None
) -> np.ndarray:
    """Compute per-sample weight vector based on class frequencies.

    Args:
        y_encoded: Integer class indices for samples.
        class_weight_dict: Optional dict mapping class index to weight.

    Returns:
        Numpy array of shape (N,) containing weight for each sample.
    """
    if class_weight_dict is None:
        unique_classes = np.unique(y_encoded)
        weights = compute_class_weight(class_weight="balanced", classes=unique_classes, y=y_encoded)
        class_weight_dict = {int(c): float(w) for c, w in zip(unique_classes, weights)}

    sample_weights = np.array([class_weight_dict.get(int(lbl), 1.0) for lbl in y_encoded], dtype=np.float32)
    return sample_weights
