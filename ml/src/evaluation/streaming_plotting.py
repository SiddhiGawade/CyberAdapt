"""
Visualization Plotting Helpers for Streaming Concept Drift & Adaptive Retraining.

Generates publication-quality charts: streaming Macro F1 trajectory, drift event timelines,
and pre- vs post-adaptation recovery performance.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


def plot_streaming_macro_f1(
    metrics_history: List[Dict[str, Any]],
    drift_events: List[Dict[str, Any]],
    output_path: Optional[Path] = None,
    title: str = "Streaming Performance Trajectory — ADWIN Drift Alert & Adaptation Recovery",
) -> None:
    """Plot window-by-window Macro F1 trajectory showing baseline, degradation, drift, and recovery.

    Args:
        metrics_history: List of per-window metric dictionaries.
        drift_events: List of detected drift event dictionaries.
        output_path: Output PNG filepath.
        title: Chart title string.
    """
    fig, ax = plt.subplots(figsize=(12, 6))

    windows = [m["window_id"] for m in metrics_history]
    macro_f1s = [m["macro_f1"] for m in metrics_history]
    dos_recalls = [m.get("per_class_metrics", {}).get("DoS", {}).get("recall", 0.0) for m in metrics_history]

    x_indices = np.arange(len(windows))

    ax.plot(x_indices, macro_f1s, marker="o", linewidth=2.5, color="#1d3557", label="Macro F1 Score")
    ax.plot(x_indices, dos_recalls, marker="s", linestyle="--", linewidth=2.0, color="#e63946", label="DoS Attack Recall")

    # Draw vertical lines for ADWIN drift events
    drift_window_ids = {e["window_id"] for e in drift_events}
    for idx, win_id in enumerate(windows):
        if win_id in drift_window_ids:
            ax.axvline(x=idx, color="#d90429", linestyle=":", linewidth=2.0, alpha=0.8)
            ax.text(
                idx,
                0.95,
                " ADWIN Alert",
                color="#d90429",
                fontweight="bold",
                fontsize=9,
                rotation=90,
                va="top",
            )

    ax.set_title(title, fontsize=13, fontweight="bold", pad=15)
    ax.set_xlabel("Streaming Window Sequence (50,000 records/window)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Metric Score (0.0 - 1.0)", fontsize=11, fontweight="bold")
    ax.set_xticks(x_indices)
    ax.set_xticklabels(windows, rotation=45, ha="right")
    ax.set_ylim(0, 1.05)
    ax.grid(True, which="both", linestyle="--", alpha=0.3)
    ax.legend(loc="lower left", frameon=True)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def plot_drift_events_timeline(
    drift_events: List[Dict[str, Any]],
    total_windows: int = 15,
    output_path: Optional[Path] = None,
) -> None:
    """Plot timeline visualization of ADWIN drift alerts across stream windows."""
    fig, ax = plt.subplots(figsize=(11, 4))

    window_indices = np.arange(total_windows)
    window_labels = [f"win_{i}" for i in window_indices]
    drift_idxs = [e["window_idx"] for e in drift_events if "window_idx" in e]

    ax.scatter(window_indices, np.zeros_like(window_indices), color="#2b5c8f", s=100, label="Normal Stream Window")
    if drift_idxs:
        ax.scatter(drift_idxs, np.zeros_like(drift_idxs), color="#d90429", s=250, zorder=5, marker="*", label="ADWIN Drift Alert")

    ax.set_yticks([])
    ax.set_xticks(window_indices)
    ax.set_xticklabels(window_labels, rotation=45, ha="right")
    ax.set_title("Stream ADWIN Drift Event Timeline", fontsize=12, fontweight="bold", pad=15)
    ax.set_xlabel("Sequential Stream Window ID", fontsize=11, fontweight="bold")
    ax.legend(loc="upper right", frameon=True)
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def plot_pre_vs_post_adaptation(
    pre_metrics: Dict[str, float],
    degraded_metrics: Dict[str, float],
    post_metrics: Dict[str, float],
    output_path: Optional[Path] = None,
) -> None:
    """Plot comparison of metrics across Pre-Shift Baseline, Degraded Shift, and Post-Adaptation states."""
    metric_names = ["Macro F1", "Weighted F1", "Balanced Accuracy", "DoS Recall"]
    
    pre_vals = [pre_metrics.get("macro_f1", 0), pre_metrics.get("weighted_f1", 0), pre_metrics.get("balanced_accuracy", 0), pre_metrics.get("dos_recall", 0)]
    deg_vals = [degraded_metrics.get("macro_f1", 0), degraded_metrics.get("weighted_f1", 0), degraded_metrics.get("balanced_accuracy", 0), degraded_metrics.get("dos_recall", 0)]
    post_vals = [post_metrics.get("macro_f1", 0), post_metrics.get("weighted_f1", 0), post_metrics.get("balanced_accuracy", 0), post_metrics.get("dos_recall", 0)]

    x = np.arange(len(metric_names))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(x - width, pre_vals, width, label="1. Pre-Shift Baseline", color="#2b5c8f", edgecolor="#142c44")
    ax.bar(x, deg_vals, width, label="2. Distribution Shift / Unseen DoS", color="#e63946", edgecolor="#142c44")
    ax.bar(x + width, post_vals, width, label="3. Post-Adaptation Champion", color="#38b000", edgecolor="#142c44")

    ax.set_title("Performance Recovery via ADWIN Detection & Adaptive Retraining", fontsize=12, fontweight="bold", pad=15)
    ax.set_ylabel("Metric Score", fontsize=11, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(metric_names, fontweight="bold")
    ax.set_ylim(0, 1.1)
    ax.grid(True, which="both", linestyle="--", alpha=0.3)
    ax.legend(frameon=True)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
