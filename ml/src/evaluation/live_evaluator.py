"""
Live Evaluation Module — rolling-window pseudo-labeled metrics.

Implements the frozen §9.4 interface (`LiveEvaluator`) for the CyberAdapt
member-3 live-evaluation pipeline. The champion model is scored against the
same pseudo-labels that feed adaptation (master plan §5.4):

    1. explicit ``ground_truth_label`` from an independently labeled source
    2. ``LBL::<CLASS_NAME>::`` simulator tag
    3. deterministic application-rule override
    4. everything else is excluded — model predictions are never treated as
       ground truth

``get_metrics()`` returns the exact §8 ``GET /evaluation`` contract, including
a pre/post-adaptation split driven by the last ``promoted: true`` timestamp in
``ml/artifacts/state/adaptation_history.json`` (written by TASK-04's
``LiveAdapter``; tolerated if absent).

State (§5.2): ``eval_window.jsonl`` — bounded rolling log, one JSON row per
labeled flow ``{ts, ts_epoch, y_true, y_pred, conf, confidence, version}``.
The file holds at most ``window`` lines and is restored on boot; corrupt lines
are skipped.

Wiring (TASK-10): api.py owns the instance and calls
``_evaluator.record(batch_records, latency_ms)`` inside ``predict()`` after the
adapter, plus ``reset()`` from ``/admin/reset``. If a ``version`` key is added
to ``batch_record`` it flows through to persisted rows; otherwise rows are
tagged ``"v1"`` (the original champion).

Thread-safe: a single ``threading.Lock`` guards all mutation. ``record()`` is
O(1) amortized for bookkeeping (deque appends); the bounded JSONL rewrite runs
once per batch, as required by §5.2.
"""

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ml.src.evaluation.metrics import evaluate_predictions
from ml.src.features.feature_contract import TARGET_CLASSES

logger = logging.getLogger(__name__)

# --- Constants (locked by master plan §5.4 / §8) ----------------------------
LBL_PREFIX = "LBL::"
MIN_LABELED_SAMPLES = 30          # below this -> "insufficient_data": true
LATENCY_DEQUE_MAXLEN = 500
DEFAULT_MODEL_VERSION = "v1"      # original champion before any promotion
DATASET_LABEL = "Live Labrooms stream (verified/rule-labeled)"
_EVAL_WINDOW_FILENAME = "eval_window.jsonl"
_ADAPTATION_HISTORY_FILENAME = "adaptation_history.json"
_NUM_CLASSES = len(TARGET_CLASSES)


# ---------------------------------------------------------------------------
# §5.4 pseudo-label resolution — implemented IDENTICALLY to LiveAdapter.observe
# ---------------------------------------------------------------------------
def _safe_index(value: Any) -> Optional[int]:
    """Coerce a class index; None if missing/out of TARGET_CLASSES range."""
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    return idx if 0 <= idx < _NUM_CLASSES else None


def _resolve_pseudo_label(record: Dict[str, Any]) -> Optional[int]:
    """Resolve a batch_record to a pseudo-label index per §5.4, in order.

    Returns the TARGET_CLASSES index to treat as ground truth, or None when
    the flow carries no usable label (such flows are NOT recorded).
    """
    # 1. Explicit label from an independently labeled, trusted source.
    label = record.get("ground_truth_label")
    if label in TARGET_CLASSES:
        return TARGET_CLASSES.index(label)

    # 2. LBL::<CLASS_NAME>:: flow_id simulator ground-truth tag.
    flow_id = str(record.get("flow_id") or "")
    if flow_id.startswith(LBL_PREFIX):
        parts = flow_id.split("::")
        if len(parts) >= 3:
            class_name = parts[1].replace("_", " ")
            if class_name in TARGET_CLASSES:
                return TARGET_CLASSES.index(class_name)
        return None

    # 3. Rule-override label for the deterministic patterns.
    if record.get("rule_override"):
        idx = _safe_index(record.get("label_index"))
        if idx is not None:
            return idx
        label = record.get("label")
        if label in TARGET_CLASSES:
            return TARGET_CLASSES.index(label)
        # unresolvable override label -> keep trying

    # Everything else is excluded; never score against the model's own guess.
    return None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp_epoch(value: Any) -> Optional[float]:
    """Tolerant timestamp -> epoch-seconds parser.

    Handles epoch seconds (int/float or numeric string), epoch milliseconds,
    ISO-8601 strings with 'Z'/offset, and naive ISO strings (interpreted as
    local time — matching the adapter's ``datetime.now().isoformat()``).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _normalize_epoch(float(value))

    s = str(value).strip()
    if not s:
        return None
    try:
        return _normalize_epoch(float(s))
    except ValueError:
        pass

    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    try:
        return dt.timestamp()  # naive -> local time (same basis as adapter)
    except (OverflowError, OSError, ValueError):
        return None


def _normalize_epoch(epoch: float) -> Optional[float]:
    if epoch <= 0:
        return None
    if epoch > 1e12:  # milliseconds, not seconds
        epoch /= 1000.0
    return epoch


class LiveEvaluator:
    """Rolling-window evaluator over pseudo-labeled live predictions (§9.4).

    Args:
        state_path: Path to ``eval_window.jsonl`` (§5.2). For defensive
            wiring, a directory may be passed instead — the file is then
            ``<dir>/eval_window.jsonl``. ``adaptation_history.json`` is always
            looked up as a sibling of the window file.
        window: Max number of labeled rows kept in the rolling window (and
            persisted to disk). Default 500.
    """

    def __init__(self, state_path: Path, window: int = 500):
        state_path = Path(state_path)
        if state_path.suffix.lower() != ".jsonl":
            # tolerate being handed the state directory instead of the file
            state_path = state_path / _EVAL_WINDOW_FILENAME
        self._state_path: Path = state_path
        self._history_path: Path = state_path.parent / _ADAPTATION_HISTORY_FILENAME
        self._window: int = int(window)
        self._rows: deque = deque(maxlen=self._window)
        self._latencies: deque = deque(maxlen=LATENCY_DEQUE_MAXLEN)
        self._lock = threading.Lock()
        self._restore()

    # -- public API (frozen §9.4) -------------------------------------------

    def record(self, records: List[dict], latency_ms: float) -> None:
        """Append pseudo-labeled rows only (§5.4 rule — same as the adapter).

        One row per labeled flow: ``{ts, ts_epoch, y_true, y_pred, conf,
        confidence, version}``. Unlabeled flows are skipped entirely.
        ``latency_ms`` is the /predict batch latency; it feeds the p95 metric
        via a bounded deque. Persists ``eval_window.jsonl`` once per batch.
        """
        now = datetime.now(timezone.utc)
        ts_iso = now.isoformat().replace("+00:00", "Z")
        ts_epoch = now.timestamp()

        appended = 0
        with self._lock:
            lat = _as_float(latency_ms)
            if lat is not None:
                self._latencies.append(lat)
            for rec in records or []:
                if not isinstance(rec, dict):
                    continue
                y_true = _resolve_pseudo_label(rec)
                if y_true is None:
                    continue
                y_pred = _safe_index(rec.get("label_index"))
                if y_pred is None:
                    continue  # no usable prediction -> cannot score agreement
                conf = _as_float(rec.get("confidence"))
                row = {
                    "ts": ts_iso,
                    "ts_epoch": ts_epoch,
                    "y_true": y_true,
                    "y_pred": y_pred,
                    "conf": conf,
                    "confidence": conf,
                    "version": str(
                        rec.get("version")
                        or rec.get("model_version")
                        or DEFAULT_MODEL_VERSION
                    ),
                }
                self._rows.append(row)
                appended += 1
            if appended:
                self._persist_locked()

    def get_metrics(self) -> dict:
        """Exact §8 /evaluation contract; insufficient_data when <30 samples."""
        with self._lock:
            rows = list(self._rows)
            latencies = list(self._latencies)

        size = len(rows)
        since = rows[0].get("ts") if rows else None
        latency_p95 = (
            float(np.percentile(np.asarray(latencies, dtype=float), 95))
            if latencies
            else 0.0
        )

        if size < MIN_LABELED_SAMPLES:
            return {
                "dataset": DATASET_LABEL,
                "insufficient_data": True,
                "window": {"size": size, "capacity": self._window, "since": since},
                "overall_metrics": {
                    "accuracy": 0.0,
                    "precision_macro": 0.0,
                    "recall_macro": 0.0,
                    "f1_macro": 0.0,
                    "latency_p95_ms": latency_p95,
                },
                "per_class_metrics": {
                    name: {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}
                    for name in TARGET_CLASSES
                },
                "confusion_matrix": [
                    [0] * _NUM_CLASSES for _ in range(_NUM_CLASSES)
                ],
                "class_names": list(TARGET_CLASSES),
                "pre_post_adaptation": self._pre_post_block(rows, sufficient=False),
            }

        y_true = np.asarray([r["y_true"] for r in rows], dtype=int)
        y_pred = np.asarray([r["y_pred"] for r in rows], dtype=int)
        res = evaluate_predictions(
            y_true, y_pred, class_names=TARGET_CLASSES
        )

        per_class: Dict[str, Dict[str, Any]] = {}
        for name in TARGET_CLASSES:
            m = res["per_class_metrics"].get(name, {})
            per_class[name] = {
                "precision": float(m.get("precision", 0.0)),
                "recall": float(m.get("recall", 0.0)),
                # metrics.py emits "f1_score"; the §8 contract wants "f1"
                "f1": float(m.get("f1_score", 0.0)),
                "support": int(m.get("support", 0)),
            }

        return {
            "dataset": DATASET_LABEL,
            "window": {"size": size, "capacity": self._window, "since": since},
            "overall_metrics": {
                "accuracy": float(res["accuracy"]),
                "precision_macro": float(res["macro_precision"]),
                "recall_macro": float(res["macro_recall"]),
                "f1_macro": float(res["macro_f1"]),
                "latency_p95_ms": latency_p95,
            },
            "per_class_metrics": per_class,
            "confusion_matrix": res["confusion_matrix_raw"],
            "class_names": list(TARGET_CLASSES),
            "pre_post_adaptation": self._pre_post_block(rows, sufficient=True),
        }

    def reset(self) -> None:
        """Clear window + latencies and remove eval_window.jsonl (/admin/reset)."""
        with self._lock:
            self._rows.clear()
            self._latencies.clear()
            try:
                if self._state_path.exists():
                    self._state_path.unlink()
            except OSError as exc:
                logger.warning("LiveEvaluator.reset: could not delete %s: %s",
                               self._state_path, exc)

    # -- persistence ---------------------------------------------------------

    def _persist_locked(self) -> None:
        """Rewrite eval_window.jsonl with the current window. Caller holds lock.

        Full bounded rewrite (<= ``window`` lines) via tmp+replace so the file
        is always truncated to the last ``window`` rows on every write.
        """
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_name(self._state_path.name + ".tmp")
            payload = "".join(
                json.dumps(row, separators=(",", ":")) + "\n" for row in self._rows
            )
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(self._state_path)
        except OSError as exc:
            logger.warning("LiveEvaluator: persist to %s failed: %s",
                           self._state_path, exc)

    def _restore(self) -> None:
        """Reload eval_window.jsonl on boot; tolerate absence and corruption."""
        if not self._state_path.exists():
            return
        try:
            lines = self._state_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("LiveEvaluator: restore from %s failed: %s",
                           self._state_path, exc)
            return

        restored = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate corruption
            if not isinstance(row, dict):
                continue
            if not isinstance(row.get("y_true"), int) or not isinstance(
                row.get("y_pred"), int
            ):
                continue
            if not isinstance(row.get("ts_epoch"), (int, float)):
                row["ts_epoch"] = _parse_timestamp_epoch(row.get("ts")) or 0.0
            if "conf" not in row:
                row["conf"] = row.get("confidence")
            if "confidence" not in row:
                row["confidence"] = row.get("conf")
            self._rows.append(row)
            restored += 1

        if restored:
            logger.info(
                "LiveEvaluator: restored %d labeled row(s) from %s",
                restored, self._state_path,
            )

    # -- pre/post adaptation split ------------------------------------------

    def _last_promoted_marker(self) -> Optional[Tuple[float, Any]]:
        """Last ``promoted: true`` entry in adaptation_history.json.

        Returns ``(epoch_seconds, raw_timestamp)`` or None — tolerates the file
        missing, being corrupt, or being a dict instead of a list.
        """
        if not self._history_path.exists():
            return None
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "LiveEvaluator: cannot read %s: %s", self._history_path, exc
            )
            return None

        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            # tolerate wrapper shapes or a single gate report
            for key in ("retraining_history", "history", "entries"):
                if isinstance(data.get(key), list):
                    entries = data[key]
                    break
            else:
                entries = [data] if "promoted" in data else []
        else:
            return None

        best: Optional[Tuple[float, Any]] = None
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("promoted"):
                continue
            raw_ts = entry.get("timestamp", entry.get("ts"))
            epoch = _parse_timestamp_epoch(raw_ts)
            if epoch is None:
                continue
            if best is None or epoch > best[0]:
                best = (epoch, raw_ts)
        return best

    def _window_f1_macro(self, rows: List[dict]) -> float:
        """Macro F1 via evaluate_predictions — identical averaging to the main path."""
        if not rows:
            return 0.0
        y_true = np.asarray([r["y_true"] for r in rows], dtype=int)
        y_pred = np.asarray([r["y_pred"] for r in rows], dtype=int)
        res = evaluate_predictions(y_true, y_pred, class_names=TARGET_CLASSES)
        return float(res["macro_f1"])

    def _pre_post_block(self, rows: List[dict], sufficient: bool) -> dict:
        """Split the window at the last promotion timestamp (§8 contract).

        Never promoted -> last_adaptation: null, pre = whole window, post = null.
        """
        marker = self._last_promoted_marker()
        if marker is None:
            return {
                "pre": {
                    "f1_macro": self._window_f1_macro(rows) if sufficient else 0.0,
                    "samples": len(rows),
                },
                "post": None,
                "last_adaptation": None,
            }

        promoted_epoch, raw_ts = marker
        pre_rows = [r for r in rows if r.get("ts_epoch", 0.0) <= promoted_epoch]
        post_rows = [r for r in rows if r.get("ts_epoch", 0.0) > promoted_epoch]

        last_adaptation = raw_ts if isinstance(raw_ts, str) else (
            datetime.fromtimestamp(promoted_epoch, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return {
            "pre": {
                "f1_macro": self._window_f1_macro(pre_rows) if sufficient else 0.0,
                "samples": len(pre_rows),
            },
            "post": {
                "f1_macro": self._window_f1_macro(post_rows) if sufficient else 0.0,
                "samples": len(post_rows),
            },
            "last_adaptation": last_adaptation,
        }
