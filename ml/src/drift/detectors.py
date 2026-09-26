"""
Concept Drift & Distribution Shift Detection Module using ADWIN (Adaptive Windowing).

Monitors streaming error rates, prediction confidence, and feature statistical signals.
"""

from typing import Dict, List, Optional, Tuple, Any
import logging
import numpy as np
from river.drift import ADWIN

logger = logging.getLogger(__name__)


class ADWINDriftDetector:
    """ADWIN (Adaptive Windowing) Concept Drift Detector wrapper."""

    def __init__(self, delta: float = 0.002, signal_name: str = "error_rate"):
        """Initialize ADWIN detector.

        Args:
            delta: ADWIN confidence value parameter (smaller delta = stricter drift sensitivity).
            signal_name: Name of stream signal being monitored.
        """
        self.delta = delta
        self.signal_name = signal_name
        self.adwin = ADWIN(delta=delta)
        self.total_updates = 0
        self.drift_count = 0
        self.drift_history: List[Dict[str, Any]] = []

    def update(self, value: float) -> Tuple[bool, float, float]:
        """Update ADWIN with a new stream observation.

        Args:
            value: Numerical observation (e.g. 1.0 for prediction error, 0.0 for correct).

        Returns:
            Tuple of (drift_detected_bool, adwin_width, adwin_estimation)
        """
        self.total_updates += 1
        self.adwin.update(value)

        drift_detected = self.adwin.drift_detected
        width = float(self.adwin.width)
        estimation = float(self.adwin.estimation)

        if drift_detected:
            self.drift_count += 1
            logger.info(
                f"ADWIN Drift Alert [{self.signal_name}] at update {self.total_updates:,}! "
                f"Window width: {width}, Mean estimation: {estimation:.4f}"
            )

        return drift_detected, width, estimation

    def reset(self) -> None:
        """Reset ADWIN detector state."""
        self.adwin = ADWIN(delta=self.delta)
        self.total_updates = 0
        self.drift_count = 0


class StreamDriftMonitor:
    """Monitors streaming batch predictions for error rate drift and distribution shift."""

    def __init__(
        self,
        error_delta: float = 0.002,
        feature_delta: float = 0.01,
    ):
        """Initialize multi-signal stream monitor.

        Args:
            error_delta: ADWIN delta parameter for prediction error stream.
            feature_delta: ADWIN delta parameter for feature signal stream.
        """
        self.error_detector = ADWINDriftDetector(delta=error_delta, signal_name="prediction_error")
        self.feature_detector = ADWINDriftDetector(delta=feature_delta, signal_name="flow_bytes_signal")
        self.drift_events_log: List[Dict[str, Any]] = []

    def process_window(
        self,
        window_id: str,
        window_idx: int,
        y_true: Optional[Any],
        y_pred: Any,
        feature_signal: Optional[float] = None,
        metric_before: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Process predictions and labels for a streaming window batch.

        Args:
            window_id: Window string identifier.
            window_idx: Integer window index.
            y_true: True integer label array (if available).
            y_pred: Predicted integer label array.
            feature_signal: Optional numeric feature aggregation signal.
            metric_before: Macro F1 or Accuracy score prior to window processing.

        Returns:
            Dictionary detailing drift detection flags and detector states.
        """
        error_drift = False
        feature_drift = False
        trigger_sample_idx = None

        if y_true is not None and len(y_true) == len(y_pred):
            errors = (np.array(y_true) != np.array(y_pred)).astype(float)
            for sample_idx, err in enumerate(errors):
                d_err, _, _ = self.error_detector.update(float(err))
                if d_err:
                    error_drift = True
                    trigger_sample_idx = sample_idx
                    self.error_detector.reset()
                    break

        if feature_signal is not None:
            d_feat, _, _ = self.feature_detector.update(float(feature_signal))
            if d_feat:
                feature_drift = True

        any_drift = error_drift or feature_drift

        if any_drift:
            event = {
                "window_id": window_id,
                "window_idx": window_idx,
                "trigger_sample_idx": trigger_sample_idx,
                "error_drift": error_drift,
                "feature_drift": feature_drift,
                "detector": "ADWIN",
                "signal": "prediction_error" if error_drift else "flow_bytes_signal",
                "metric_before_drift": float(metric_before) if metric_before is not None else None,
            }
            self.drift_events_log.append(event)
            logger.info(f"StreamDriftMonitor logged drift event for {window_id} at sample {trigger_sample_idx}: {event}")

        return {
            "window_id": window_id,
            "window_idx": window_idx,
            "drift_detected": any_drift,
            "trigger_sample_idx": trigger_sample_idx,
            "error_drift": error_drift,
            "feature_drift": feature_drift,
            "error_detector_estimation": self.error_detector.adwin.estimation,
            "error_detector_width": self.error_detector.adwin.width,
        }
