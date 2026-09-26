"""
Visualization Helpers Module for ML Model Benchmarking.

Produces publication-grade plots for Macro F1 comparison, per-class recall,
normalized confusion matrices, and split strategy benchmark comparisons.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from ml.src.features.feature_contract import TARGET_CLASSES

# Dark theme palette styling
COLORS = ["#2b5c8f", "#3a86ff", "#8338ec", "#ff006e", "#fb5607", "#ffbe0b", "#38b000"]


def plot_model_comparison_bar(
    metrics_df: pd.DataFrame,
    metric_name: str = "macro_f1",
    output_path: Optional[Path] = None,
    title: str = "Model Comparison — Macro F1 Score",
) -> None:
    """Generate bar chart comparing models on a specific metric.

    Args:
        metrics_df: DataFrame with 'model_name' and metric_name columns.
        metric_name: Column name of metric to plot.
        output_path: File path to save output figure PNG.
        title: Plot title.
    """
    fig, ax = plt.subplots(figsize=(10, 6))

    df_sorted = metrics_df.sort_values(by=metric_name, ascending=True)
    models = df_sorted["model_name"]
    values = df_sorted[metric_name]

    bars = ax.barh(models, values, color="#2b5c8f", edgecolor="#142c44", height=0.55)
    ax.set_xlabel(metric_name.replace("_", " ").title(), fontsize=11, fontweight="bold")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=15)
    ax.set_xlim(0, 1.05)
    ax.grid(True, which="both", linestyle="--", alpha=0.3)

    for bar, val in zip(bars, values):
        ax.text(
            val + 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.4f}",
            va="center",
            ha="left",
            fontsize=9,
            fontweight="bold",
        )

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def plot_normalized_confusion_matrix(
    cm_norm: np.ndarray,
    model_name: str,
    output_path: Optional[Path] = None,
    class_names: Optional[List[str]] = None,
) -> None:
    """Generate heatmap of normalized confusion matrix.

    Args:
        cm_norm: 2D numpy array of row-normalized values (0.0 to 1.0).
        model_name: Name of model.
        output_path: File path to save figure.
        class_names: Target class label strings.
    """
    labels = class_names or TARGET_CLASSES

    fig, ax = plt.subplots(figsize=(9, 7))
    sns.heatmap(
        cm_norm,
        annot=True,
        fmt=".3f",
        cmap="Blues",
        xticklabels=labels,
        yticklabels=labels,
        ax=ax,
        cbar_kws={"label": "Normalized Recall"},
        vmin=0.0,
        vmax=1.0,
    )

    ax.set_title(f"Normalized Confusion Matrix — {model_name}", fontsize=13, fontweight="bold", pad=15)
    ax.set_xlabel("Predicted Label", fontsize=11, fontweight="bold")
    ax.set_ylabel("True Label", fontsize=11, fontweight="bold")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def plot_minority_recall_comparison(
    metrics_df: pd.DataFrame, output_path: Optional[Path] = None
) -> None:
    """Generate grouped bar chart comparing recall for minority classes (Bots, Web Attacks, Brute Force).

    Args:
        metrics_df: DataFrame with 'model_name', 'recall_bots', 'recall_web_attacks', 'recall_brute_force'.
        output_path: File path to save figure PNG.
    """
    minority_cols = [c for c in ["recall_bots", "recall_web_attacks", "recall_brute_force"] if c in metrics_df.columns]
    if not minority_cols:
        return

    df_melted = metrics_df.melt(
        id_vars=["model_name"],
        value_vars=minority_cols,
        var_name="minority_class",
        value_name="recall",
    )
    df_melted["minority_class"] = df_melted["minority_class"].str.replace("recall_", "").str.replace("_", " ").str.title()

    fig, ax = plt.subplots(figsize=(11, 6))
    sns.barplot(
        data=df_melted,
        x="model_name",
        y="recall",
        hue="minority_class",
        palette=["#e63946", "#f4a261", "#2a9d8f"],
        ax=ax,
        edgecolor="#142c44",
    )

    ax.set_title("Minority Attack Class Recall Comparison", fontsize=13, fontweight="bold", pad=15)
    ax.set_xlabel("Model Architecture", fontsize=11, fontweight="bold")
    ax.set_ylabel("Recall Score", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.grid(True, which="both", linestyle="--", alpha=0.3)
    plt.xticks(rotation=30, ha="right")
    ax.legend(title="Minority Class", frameon=True)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def plot_split_strategy_comparison(
    random_df: pd.DataFrame,
    ordered_df: pd.DataFrame,
    output_path: Optional[Path] = None,
) -> None:
    """Plot comparison between Random Stratified Benchmark vs. Ordered Holdout Proxy.

    Args:
        random_df: Metrics DataFrame from random_stratified_benchmark.
        ordered_df: Metrics DataFrame from ordered_holdout_proxy.
        output_path: Output PNG path.
    """
    df_rand = random_df[["model_name", "macro_f1"]].copy()
    df_rand["split_strategy"] = "Random Stratified"

    df_ord = ordered_df[["model_name", "macro_f1"]].copy()
    df_ord["split_strategy"] = "Ordered Holdout Proxy"

    df_combined = pd.concat([df_rand, df_ord], ignore_index=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    sns.barplot(
        data=df_combined,
        x="model_name",
        y="macro_f1",
        hue="split_strategy",
        palette=["#1d3557", "#e63946"],
        ax=ax,
        edgecolor="#142c44",
    )

    ax.set_title("Evaluation Split Strategy Impact: Random Stratified vs Ordered Holdout Proxy", fontsize=12, fontweight="bold", pad=15)
    ax.set_xlabel("Model Architecture", fontsize=11, fontweight="bold")
    ax.set_ylabel("Macro F1 Score", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.grid(True, which="both", linestyle="--", alpha=0.3)
    plt.xticks(rotation=25, ha="right")
    ax.legend(title="Split Strategy", frameon=True)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
