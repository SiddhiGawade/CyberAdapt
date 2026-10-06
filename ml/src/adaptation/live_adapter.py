"""
Live Adaptation Module — drift-triggered candidate retraining + gated promotion.

Implements the Member-3 frozen interface `LiveAdapter` (master plan §9.3).
The module is fully self-contained: every runtime dependency is an *injected
callable* passed to the constructor — it never imports `ml.api` or
`live_monitor`, which is what makes Wave-A parallel authoring safe.

Wiring note for TASK-09
-----------------------
Instantiate ONE api-owned ``LiveAdapter`` next to ``_drift_monitor`` and inject::

    get_champion          -> returns (_champion_model, _preprocessor)
    set_champion          -> reassigns api globals + bumps _model_loaded_at/_model_path_used
    extract_features      -> _extract_labrooms_features  (raw 52-slot -> named dict)
    consume_drift_event   -> _drift_monitor.consume_drift_event
    reset_drift_reference -> _drift_monitor.reset_reference

Then inside ``predict()`` (guarded block, per §9.5)::
    _adapter.observe(batch_records)
    _adapter.maybe_trigger()

The module-level ``adapt_model()`` below is the team deliverable name from the
v1 plan; it wraps a lazy module-level singleton built on local no-op callables.
TASK-09 should prefer constructor injection on the api-owned instance — the
singleton exists for standalone/notebook use only.

Design notes
------------
* Training labels come only from a verified label, an LBL:: simulator tag,
  or a deterministic rule override; model predictions are never reused.
* The 4-gate promotion semantics and gate-report shape replicate
  ``ml.src.models.adaptive_engine.AdaptiveModelManager`` (same
  ``PromotionGateConfig`` thresholds, same report keys: ``window_id``,
  ``promoted``, ``champion_*``, ``candidate_*``, ``gates_passed``, timestamps).
  The engine itself is not reused because it operates on 52-feature CICIDS
  frames, while live buffer rows are 8-feature Labrooms dicts
  (``LABROOMS_DEPLOYMENT_FEATURES``). ``evaluate_predictions`` is reused for
  both champion and candidate evaluation.
* State files live under ``state_dir`` (``ml/artifacts/state/``):
  ``adaptation_history.json`` (gate reports, engine shape + live extras),
  ``active_model.json`` (``{model_path, preprocessor_path, version}`` —
  *written* here; reading it to pick the boot model is api.py's job in
  TASK-09), and ``adapter_state.json`` (label-source counters + version +
  last_event so they survive restarts). Promoted artifacts go to
  ``<state_dir>/../models/adaptive_{champion,preprocessor}_vN.joblib``.
"""

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from ml.src.evaluation.metrics import evaluate_predictions
from ml.src.features.feature_contract import (
    LABROOMS_DEPLOYMENT_FEATURES,
    TARGET_CLASSES,
)
from ml.src.features.preprocessing import CICIDSDataPreprocessor
from ml.src.models.adaptive_engine import PromotionGateConfig

logger = logging.getLogger(__name__)

NORMAL_CLASS: str = "Normal Traffic"
HISTORY_CAP: int = 50
TRAIN_FRACTION: float = 0.75


def _utc_now_iso() -> str:
    """UTC timestamp in the same 'YYYY-MM-DDTHH:MM:SSZ' format api.py emits."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_float(value: Any) -> float:
    """Best-effort float coercion; NaN/inf/unparseable -> 0.0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(v) or np.isinf(v):
        return 0.0
    return v


def _bump_version(version: str) -> str:
    """v1 -> v2 -> v3 ... (same rule as AdaptiveModelManager)."""
    if isinstance(version, str) and version.startswith("v") and version[1:].isdigit():
        return f"v{int(version[1:]) + 1}"
    return "v2"


def _read_json(path: Path) -> Any:
    """Read a JSON file tolerantly. Returns None on missing/corrupt."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.warning(f"Could not restore {path.name}: {exc}")
    return None


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON defensively (mkdir first, never raise to caller's caller)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


class LiveAdapter:
    """Pseudo-label buffer + drift-triggered retrain + 4-gate champion promotion.

    All external dependencies are injected callables — see §9.3. Construct one
    instance per process (api.py owns it after TASK-09).

    Args:
        state_dir: Directory for adapter state files (``ml/artifacts/state``).
        get_champion: ``() -> (model, preprocessor)`` — current production pair.
        set_champion: ``(model, preprocessor, version: str) -> None`` — hot-swap.
        extract_features: ``(raw_52: list, feature_schema: str) -> dict`` —
            raw sensor vector to named model features.
        consume_drift_event: ``() -> dict | None`` — pops pending drift trigger.
        reset_drift_reference: ``() -> None`` — called after every retrain so
            the monitor's reference windows rebaseline post-adaptation.
        capacity: Ring buffer max size (labeled samples).
        min_buffer: Minimum labeled samples required before a retrain fires.
        min_attack: Minimum non-Normal samples required before a retrain fires.
        cooldown_sec: Minimum seconds between automatic (drift) triggers.
    """

    def __init__(
        self,
        state_dir: Path,
        get_champion: Callable[[], Tuple[Any, Any]],
        set_champion: Callable[[Any, Any, str], None],
        extract_features: Callable[..., Dict[str, float]],
        consume_drift_event: Callable[[], Optional[Dict[str, Any]]],
        reset_drift_reference: Callable[[], None],
        capacity: int = 5000,
        min_buffer: int = 200,
        min_attack: int = 30,
        cooldown_sec: int = 60,
    ):
        self.state_dir = Path(state_dir)
        self._get_champion = get_champion
        self._set_champion = set_champion
        self._extract_features = extract_features
        self._consume_drift_event = consume_drift_event
        self._reset_drift_reference = reset_drift_reference

        self.capacity = int(capacity)
        self.min_buffer = int(min_buffer)
        self.min_attack = int(min_attack)
        self.cooldown_sec = int(cooldown_sec)

        self._lock = threading.Lock()
        self._buffer: "deque[Dict[str, Any]]" = deque(maxlen=self.capacity)
        self._label_sources: Dict[str, int] = {
            "verified_label": 0,
            "rule_override": 0,
            "flow_id_tag": 0,
        }
        self._history: List[Dict[str, Any]] = []          # gate reports, cap 50
        self._last_event: Optional[Dict[str, Any]] = None
        self._pending_drift_event: Optional[Dict[str, Any]] = None
        self._version: str = "v1"
        self._champion_since: str = _utc_now_iso()
        self._retrain_in_progress: bool = False
        self._last_auto_trigger_ts: float = 0.0
        self._retrain_count: int = 0

        self.gate_config = PromotionGateConfig()

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._restore()

    # ── Public interface (§9.3) ──────────────────────────────────────────────

    def observe(self, records: List[Dict[str, Any]]) -> None:
        """Append pseudo-labeled samples (§5.4 rule) to the ring buffer.

        Resolution order per record:
          1. Explicit ``ground_truth_label`` from a trusted labeled source.
          2. ``LBL::<CLASS_NAME>::`` simulator tag.
          3. A deterministic rule override.
          4. Otherwise the record is excluded. Model predictions are never
             treated as training labels.
        """
        if not records:
            return

        prepared: List[Dict[str, Any]] = []
        for rec in records:
            try:
                resolved = self._resolve_pseudo_label(rec)
                if resolved is None:
                    continue
                y_idx, source = resolved
                feats = self._extract_features(
                    rec.get("raw_features"),
                    rec.get("feature_schema", "labrooms-app-layer-v2"),
                )
                if not isinstance(feats, dict):
                    continue
                row = {name: _safe_float(feats.get(name)) for name in LABROOMS_DEPLOYMENT_FEATURES}
                prepared.append(
                    {"x": row, "y": int(y_idx), "ts": _utc_now_iso(), "source": source}
                )
            except Exception:
                # Never let one malformed record break the ingest path.
                continue

        if not prepared:
            return

        with self._lock:
            for item in prepared:
                self._buffer.append(item)
                self._label_sources[item["source"]] += 1
        self._persist_state()

    def maybe_trigger(self) -> None:
        """Fire an automatic retrain when a drift event is pending.

        Retains the drift event until the buffer and cooldown requirements are
        met. A one-shot drift alert must not be lost while trusted labels arrive.
        """
        with self._lock:
            if self._pending_drift_event is None:
                try:
                    self._pending_drift_event = self._consume_drift_event()
                except Exception as exc:
                    logger.warning(f"consume_drift_event() raised: {exc}")
                    return
            event = self._pending_drift_event
            if event is None:
                return

            trigger_desc = self._describe_drift_event(event)
            if self._retrain_in_progress:
                self._set_last_event_locked("waiting", f"retrain already in progress ({trigger_desc})")
                self._persist_state_locked()
                return
            elapsed = time.time() - self._last_auto_trigger_ts
            if elapsed < self.cooldown_sec:
                self._set_last_event_locked(
                    "waiting",
                    f"cooldown active ({self.cooldown_sec - elapsed:.0f}s remaining) ({trigger_desc})",
                )
                self._persist_state_locked()
                return
            ok, detail, _n = self._buffer_check_locked()
            if not ok:
                self._set_last_event_locked("waiting", f"waiting for trusted labels: {detail} ({trigger_desc})")
                self._persist_state_locked()
                return
            self._pending_drift_event = None
            self._retrain_in_progress = True
            self._last_auto_trigger_ts = time.time()
            self._persist_state_locked()

        self._spawn_retrain(trigger_desc)

    def trigger(self, reason: str) -> Dict[str, Any]:
        """Manual retrain trigger (POST /adaptation/trigger path).

        Ignores the auto-trigger cooldown but respects the one-retrain lock and
        buffer minimums. Returns ``{status: accepted|busy|insufficient, ...}``.
        """
        reason = str(reason or "manual")
        with self._lock:
            if self._retrain_in_progress:
                return {
                    "status": "busy",
                    "detail": "candidate retrain already in progress",
                    "buffer_size": len(self._buffer),
                }
            ok, detail, n = self._buffer_check_locked()
            if not ok:
                self._set_last_event_locked(
                    "skipped", f"manual trigger '{reason}' rejected — {detail}"
                )
                self._persist_state_locked()
                return {"status": "insufficient", "detail": detail, "buffer_size": n}
            self._pending_drift_event = None
            self._retrain_in_progress = True
            self._persist_state_locked()

        trigger_desc = f"Manual trigger ({reason})"
        self._spawn_retrain(trigger_desc)
        return {
            "status": "accepted",
            "job": "candidate_retrain",
            "buffer_size": n,
            "reason": reason,
        }

    def get_status(self) -> Dict[str, Any]:
        """Exact §8 ``GET /adaptation`` contract payload."""
        try:
            champ_model, _ = self._get_champion()
            champion_name = type(champ_model).__name__ if champ_model is not None else "unloaded"
        except Exception:
            champion_name = "unavailable"

        with self._lock:
            size = len(self._buffer)
            history = [
                {
                    "version": r.get("champion_version_after", r.get("champion_version_before")),
                    "timestamp": r.get("timestamp"),
                    "f1_score": r.get("candidate_macro_f1"),
                    "trigger": r.get("trigger"),
                    "promoted": r.get("promoted"),
                    "gates_passed": r.get("gates_passed"),
                }
                for r in self._history
            ]
            return {
                "champion_model": champion_name,
                "champion_version": self._version,
                "adaptation_mode": "Drift-triggered candidate retrain + gated promotion",
                "model_loaded_at": self._champion_since,
                "adaptation_in_progress": self._retrain_in_progress,
                "online_learning_buffer": {
                    "capacity": self.capacity,
                    "current_size": size,
                    "fill_percentage": round(100.0 * size / self.capacity, 1) if self.capacity else 0.0,
                    "label_sources": dict(self._label_sources),
                },
                "retraining_history": history,
                "last_event": self._last_event,
            }

    def reset(self) -> None:
        """Clear buffer, history, label counters, last_event; version -> v1.

        Used by POST /admin/reset. Does NOT delete ``active_model.json`` —
        api.py removes it and reloads the original artifacts (TASK-09).
        """
        with self._lock:
            self._buffer.clear()
            for k in self._label_sources:
                self._label_sources[k] = 0
            self._history.clear()
            self._last_event = None
            self._pending_drift_event = None
            self._version = "v1"
            self._champion_since = _utc_now_iso()
            self._last_auto_trigger_ts = 0.0
            self._persist_history_locked()
            self._persist_state_locked()
        logger.info("LiveAdapter reset — buffer, history and counters cleared (version=v1).")

    @property
    def champion_version(self) -> str:
        """Current champion version string ('v1', 'v2', ...)."""
        with self._lock:
            return self._version

    # ── Pseudo-labeling (§5.4) ───────────────────────────────────────────────

    def _resolve_pseudo_label(self, rec: Dict[str, Any]) -> Optional[Tuple[int, str]]:
        """Resolve one batch_record to ``(y_index, source)`` or ``None``.

        Must stay semantically identical to LiveEvaluator's copy (TASK-05).
        """
        # 1. Explicit label from an independently labeled, trusted source.
        label = rec.get("ground_truth_label")
        if label in TARGET_CLASSES:
            return TARGET_CLASSES.index(label), "verified_label"

        # 2. LBL::<CLASS_NAME>:: flow_id tag (simulator ground truth)
        flow_id = str(rec.get("flow_id") or "")
        if flow_id.startswith("LBL::"):
            parts = flow_id.split("::")
            if len(parts) >= 2 and parts[1]:
                name = parts[1].replace("_", " ")
                if name in TARGET_CLASSES:
                    return TARGET_CLASSES.index(name), "flow_id_tag"
            # Tag present but class unresolvable — never trust the model label
            # on a simulator-tagged flow.
            return None

        # 3. Rule-override label — final post-override label is rule-derived.
        if rec.get("rule_override"):
            label = rec.get("label")
            if label in TARGET_CLASSES:
                return TARGET_CLASSES.index(label), "rule_override"
            idx = rec.get("label_index")
            if isinstance(idx, (int, np.integer)) and 0 <= int(idx) < len(TARGET_CLASSES):
                return int(idx), "rule_override"
            return None

        # Unlabeled — model predictions are not promoted to training labels.
        return None

    # ── Trigger helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _describe_drift_event(event: Dict[str, Any]) -> str:
        """Human-readable trigger label, e.g. 'ADWIN drift alert (attack_ratio)'."""
        if not isinstance(event, dict):
            return "Drift event"
        detector = event.get("detector") or "Drift"
        signal = event.get("signal") or "unknown_signal"
        return f"{detector} drift alert ({signal})"

    def _buffer_check_locked(self) -> Tuple[bool, str, int]:
        """Buffer sufficiency gate. Caller must hold ``self._lock``."""
        n = len(self._buffer)
        if n < self.min_buffer:
            return False, f"{n} labeled samples < min_buffer {self.min_buffer}", n
        classes = {item["y"] for item in self._buffer}
        if len(classes) < 2:
            return False, "fewer than 2 distinct classes in buffer", n
        non_normal = sum(1 for item in self._buffer if item["y"] != TARGET_CLASSES.index(NORMAL_CLASS))
        if non_normal < self.min_attack:
            return False, f"{non_normal} non-Normal samples < min_attack {self.min_attack}", n
        return True, "ok", n

    def _spawn_retrain(self, trigger_desc: str) -> None:
        thread = threading.Thread(
            target=self._retrain_and_gate,
            args=(trigger_desc,),
            daemon=True,
            name="live-adapter-retrain",
        )
        thread.start()

    def _set_last_event_locked(self, event_type: str, detail: str) -> None:
        self._last_event = {
            "type": event_type,
            "timestamp": _utc_now_iso(),
            "detail": detail,
        }

    # ── Retrain + gated promotion (daemon thread body) ───────────────────────

    def _retrain_and_gate(self, trigger_desc: str) -> None:
        """Snapshot buffer -> retrain candidate -> 4-gate eval -> promote/reject.

        All exceptions are contained: logged + recorded as a ``last_event`` of
        type ``error`` — they never propagate to the caller (the /predict path).
        """
        window_id = "live_retrain"
        try:
            # 0. Snapshot buffer under lock (deque may keep filling meanwhile).
            with self._lock:
                snapshot = list(self._buffer)
                self._retrain_count += 1
                retrain_id = self._retrain_count
            window_id = f"live_retrain_{retrain_id:03d}"

            X = pd.DataFrame(
                [item["x"] for item in snapshot], columns=list(LABROOMS_DEPLOYMENT_FEATURES)
            )
            y_str = pd.Series(
                [TARGET_CLASSES[item["y"]] for item in snapshot], name="label", dtype=str
            )

            # 1. Chronological split: train = first 75%, validation = last 25%
            #    (validation tail is NEVER seen by the candidate during fit).
            cut = int(len(X) * TRAIN_FRACTION)
            train_X, train_y = X.iloc[:cut], y_str.iloc[:cut]
            val_X, val_y = X.iloc[cut:], y_str.iloc[cut:]
            split_note = "chronological_75_25 (validation = newest 25%)"
            stratified = False

            if val_X.empty or train_y.nunique() < 2 or val_y.nunique() < 2:
                # Degenerate chronological split (e.g. attack campaign entirely
                # in the tail -> validation has a single class, which would
                # auto-fail the Normal-FPR gate). Fall back to a stratified
                # split when every class has >=2 members; else keep chrono and
                # let the report note it.
                counts = y_str.value_counts()
                if y_str.nunique() >= 2 and int(counts.min()) >= 2:
                    train_X, val_X, train_y, val_y = train_test_split(
                        X, y_str, test_size=1.0 - TRAIN_FRACTION,
                        random_state=42, stratify=y_str,
                    )
                    stratified = True
                    split_note = (
                        "stratified_75_25 fallback (chronological split left "
                        "<2 classes in train or validation)"
                    )
                else:
                    split_note = (
                        "chronological_75_25 (degenerate split — stratification "
                        "impossible, a class has <2 members)"
                    )

            # 2. Candidate: fresh preprocessor on the 8 Labrooms features + LGBM.
            cand_preproc = CICIDSDataPreprocessor(
                feature_cols=list(LABROOMS_DEPLOYMENT_FEATURES)
            )
            X_train_scaled, y_train_enc = cand_preproc.fit_transform(train_X, train_y)
            candidate = lgb.LGBMClassifier(
                n_estimators=60,
                max_depth=6,
                learning_rate=0.1,
                class_weight="balanced",
                random_state=42,
                verbose=-1,
            )
            candidate.fit(X_train_scaled, y_train_enc)

            # 3. Champion under evaluation (injected getter — may be unloaded).
            champ_model, champ_preproc = self._get_champion()
            if champ_model is None or champ_preproc is None:
                raise RuntimeError(
                    "get_champion() returned no model/preprocessor — "
                    "cannot evaluate candidate against champion"
                )

            X_val_champ, y_val_enc = self._transform_with_labels(champ_preproc, val_X, val_y)
            champ_pred = champ_model.predict(X_val_champ)
            champ_prob = (
                champ_model.predict_proba(X_val_champ)
                if hasattr(champ_model, "predict_proba")
                else None
            )
            champ_eval = evaluate_predictions(
                y_val_enc, champ_pred, champ_prob,
                model_name="Champion", split_name=window_id,
            )

            X_val_cand, _ = cand_preproc.transform(val_X, val_y)
            cand_pred = candidate.predict(X_val_cand)
            cand_prob = (
                candidate.predict_proba(X_val_cand)
                if hasattr(candidate, "predict_proba")
                else None
            )
            cand_eval = evaluate_predictions(
                y_val_enc, cand_pred, cand_prob,
                model_name="Candidate", split_name=window_id,
            )

            # 4. Gate criteria — identical semantics to adaptive_engine.py.
            macro_f1_diff = cand_eval["macro_f1"] - champ_eval["macro_f1"]
            bal_acc_diff = cand_eval["balanced_accuracy"] - champ_eval["balanced_accuracy"]

            emerged_class = self._emerged_class(snapshot)
            emerged_metrics = cand_eval["per_class_metrics"].get(emerged_class, {})
            emerged_support = emerged_metrics.get("support", 0)
            emerged_recall = emerged_metrics.get("recall", 0.0)

            normal_metrics = cand_eval["per_class_metrics"].get(NORMAL_CLASS, {})
            normal_fpr = round(1.0 - normal_metrics.get("precision", 1.0), 4)

            gate_macro_f1 = macro_f1_diff >= self.gate_config.min_macro_f1_delta
            gate_bal_acc = bal_acc_diff >= self.gate_config.min_balanced_acc_delta
            gate_emerged_recall = (
                emerged_recall >= self.gate_config.min_minority_recall
            ) if emerged_support > 0 else True
            gate_normal_fpr = normal_fpr <= self.gate_config.max_normal_fpr

            promoted = bool(
                gate_macro_f1 and gate_bal_acc and gate_emerged_recall and gate_normal_fpr
            )

            gate_report: Dict[str, Any] = {
                # ── engine-identical shape ──
                "window_id": window_id,
                "train_window_ids": [f"{window_id}_train_split"],
                "timestamp": _utc_now_iso(),
                "promoted": promoted,
                "champion_version_before": None,  # filled below
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
                # ── live extras (same file consumed by TASK-05 + UI) ──
                "trigger": trigger_desc,
                "buffer_size": len(snapshot),
                "train_size": int(len(train_X)),
                "validation_size": int(len(val_X)),
                "split": split_note,
                "stratified": stratified,
            }

            # 5. Promote or reject.
            with self._lock:
                old_version = self._version
            gate_report["champion_version_before"] = old_version

            if promoted:
                new_version = _bump_version(old_version)
                models_dir = self.state_dir.parent / "models"
                models_dir.mkdir(parents=True, exist_ok=True)
                model_path = models_dir / f"adaptive_champion_{new_version}.joblib"
                preproc_path = models_dir / f"adaptive_preprocessor_{new_version}.joblib"
                joblib.dump(candidate, model_path)
                cand_preproc.save(preproc_path)
                _write_json(
                    self.state_dir / "active_model.json",
                    {
                        "model_path": str(model_path),
                        "preprocessor_path": str(preproc_path),
                        "version": new_version,
                    },
                )
                # Hot-swap via injected callable — api.py reassigns its globals.
                self._set_champion(candidate, cand_preproc, new_version)
                with self._lock:
                    self._version = new_version
                    self._champion_since = _utc_now_iso()
                    gate_report["champion_version_after"] = new_version
                    self._set_last_event_locked(
                        "promotion",
                        f"Candidate promoted {old_version} -> {new_version} "
                        f"(macro_f1 {champ_eval['macro_f1']:.4f} -> "
                        f"{cand_eval['macro_f1']:.4f}, {emerged_class} recall "
                        f"{emerged_recall:.4f}) [{trigger_desc}]",
                    )
                logger.info(
                    f"PROMOTION SUCCESSFUL {old_version} -> {new_version} "
                    f"(trigger: {trigger_desc})"
                )
            else:
                with self._lock:
                    gate_report["champion_version_after"] = old_version
                    failed = [k for k, v in gate_report["gates_passed"].items() if not v]
                    self._set_last_event_locked(
                        "rejection",
                        f"Candidate rejected — gates failed: {', '.join(failed) or 'none'} "
                        f"(macro_f1_delta {gate_report['macro_f1_delta']:+.4f}, "
                        f"normal_fpr {normal_fpr:.4f}) [{trigger_desc}]",
                    )
                logger.warning(
                    f"PROMOTION REJECTED ({trigger_desc}) — champion stays {old_version}."
                )

            # 6. Always record the gate report (promoted AND rejected) and persist.
            with self._lock:
                self._history.append(gate_report)
                if len(self._history) > HISTORY_CAP:
                    self._history = self._history[-HISTORY_CAP:]
                self._persist_history_locked()
                self._persist_state_locked()

            # 7. Post-adaptation baseline shift for the drift monitor.
            try:
                self._reset_drift_reference()
            except Exception as exc:
                logger.warning(f"reset_drift_reference() raised: {exc}")

        except Exception as exc:  # contained — never propagate to /predict
            logger.exception(f"Retrain thread failed (window {window_id}): {exc}")
            try:
                with self._lock:
                    self._set_last_event_locked(
                        "error", f"retrain failed: {type(exc).__name__}: {exc}"
                    )
                    self._persist_state_locked()
            except Exception:
                pass
        finally:
            with self._lock:
                self._retrain_in_progress = False

    def _emerged_class(self, snapshot: List[Dict[str, Any]]) -> str:
        """Most frequent non-Normal pseudo-label in the buffer (fallback 'DoS')."""
        counts: Dict[int, int] = {}
        for item in snapshot:
            if item["y"] != TARGET_CLASSES.index(NORMAL_CLASS):
                counts[item["y"]] = counts.get(item["y"], 0) + 1
        if not counts:
            return "DoS"
        top_idx = max(counts, key=counts.get)
        return TARGET_CLASSES[top_idx]

    @staticmethod
    def _transform_with_labels(
        preproc: Any, X: pd.DataFrame, y: pd.Series
    ) -> Tuple[np.ndarray, np.ndarray]:
        """``preproc.transform(X, y)`` -> (X_scaled, y_encoded), tolerating
        transformers that only return X (y falls back to TARGET_CLASSES order)."""
        result = preproc.transform(X, y)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        y_enc = np.array(
            [TARGET_CLASSES.index(lbl) if lbl in TARGET_CLASSES else 0 for lbl in y.astype(str)],
            dtype=int,
        )
        return result, y_enc

    # ── Persistence (§5.2) ───────────────────────────────────────────────────

    def _persist_history_locked(self) -> None:
        """Write adaptation_history.json (gate-report list, cap 50). Caller holds lock."""
        try:
            _write_json(self.state_dir / "adaptation_history.json", self._history)
        except Exception as exc:
            logger.warning(f"Could not persist adaptation_history.json: {exc}")

    def _persist_state_locked(self) -> None:
        """Write adapter_state.json. Caller holds lock."""
        try:
            _write_json(
                self.state_dir / "adapter_state.json",
                {
                    "version": self._version,
                    "label_sources": dict(self._label_sources),
                    "last_event": self._last_event,
                    "pending_drift_event": self._pending_drift_event,
                },
            )
        except Exception as exc:
            logger.warning(f"Could not persist adapter_state.json: {exc}")

    def _persist_state(self) -> None:
        with self._lock:
            self._persist_state_locked()

    def _restore(self) -> None:
        """Boot-restore history + label_sources + version counter from state_dir.

        Buffer contents intentionally do not survive restarts. The version
        counter comes from adapter_state.json (authoritative) with a fallback
        to the last promoted entry in adaptation_history.json. Note: reading
        ``active_model.json`` to choose the boot *model* is api.py's job
        (TASK-09) — this module only writes that file.
        """
        hist = _read_json(self.state_dir / "adaptation_history.json")
        if isinstance(hist, list):
            self._history = [r for r in hist if isinstance(r, dict)][-HISTORY_CAP:]

        state = _read_json(self.state_dir / "adapter_state.json")
        restored_version = False
        if isinstance(state, dict):
            ls = state.get("label_sources")
            if isinstance(ls, dict):
                for k in self._label_sources:
                    if k in ls:
                        self._label_sources[k] = int(ls[k])
            v = state.get("version")
            if isinstance(v, str) and v:
                self._version = v
                restored_version = True
            le = state.get("last_event")
            if isinstance(le, dict):
                self._last_event = le
            pending = state.get("pending_drift_event")
            if isinstance(pending, dict):
                self._pending_drift_event = pending

        if not restored_version:
            promoted = [r for r in self._history if r.get("promoted")]
            if promoted:
                v = promoted[-1].get("champion_version_after")
                if isinstance(v, str) and v:
                    self._version = v

        if self._history or restored_version:
            logger.info(
                f"LiveAdapter restored: {len(self._history)} history entries, "
                f"version {self._version}, label_sources {self._label_sources}"
            )


# ── Module-level deliverable: adapt_model() ──────────────────────────────────
# Lazy singleton built on local no-op callables so this module stays importable
# and usable without api.py. TASK-09 should prefer constructor injection on its
# own api-owned instance; adapt_model() exists for the team deliverable name
# and standalone/notebook use.

_SINGLETON_LOCK = threading.Lock()
_DEFAULT_ADAPTER: Optional[LiveAdapter] = None
_SINGLETON_CHAMPION: Dict[str, Any] = {"model": None, "preprocessor": None}

# Local copy of api.py's feature-to-slot map (keeps the singleton self-contained
# without importing ml.api).
_LABROOMS_FEATURE_SLOT_MAP: Dict[str, int] = {
    "Flow Duration": 1,
    "Total Fwd Packets": 2,
    "Total Length of Fwd Packets": 4,
    "Fwd Packet Length Max": 6,
    "Fwd Packet Length Min": 7,
    "Bwd Packet Length Max": 5,
    "Bwd Packet Length Min": 5,
    "Flow Bytes/s": 14,
}


def _default_extract_features(
    raw_features: List[float],
    feature_schema: str = "labrooms-app-layer-v2",
) -> Dict[str, float]:
    slot_map = _LABROOMS_FEATURE_SLOT_MAP
    if feature_schema == "packet-flow-v1":
        slot_map = {
            **_LABROOMS_FEATURE_SLOT_MAP,
            "Bwd Packet Length Max": 10,
            "Bwd Packet Length Min": 11,
        }
    elif feature_schema != "labrooms-app-layer-v2":
        raise ValueError(f"Unsupported feature schema: {feature_schema}")
    return {
        name: _safe_float(raw_features[idx])
        for name, idx in slot_map.items()
    }


def _default_adapter() -> LiveAdapter:
    global _DEFAULT_ADAPTER
    with _SINGLETON_LOCK:
        if _DEFAULT_ADAPTER is None:
            default_state_dir = Path(__file__).resolve().parents[2] / "artifacts" / "state"
            _DEFAULT_ADAPTER = LiveAdapter(
                state_dir=default_state_dir,
                get_champion=lambda: (
                    _SINGLETON_CHAMPION["model"],
                    _SINGLETON_CHAMPION["preprocessor"],
                ),
                set_champion=lambda m, p, v: _SINGLETON_CHAMPION.update(
                    {"model": m, "preprocessor": p}
                ),
                extract_features=_default_extract_features,
                consume_drift_event=lambda: None,
                reset_drift_reference=lambda: None,
            )
    return _DEFAULT_ADAPTER


def adapt_model(reason: str = "manual") -> Dict[str, Any]:
    """Team deliverable name — wraps the lazy singleton's ``trigger``.

    For production wiring (TASK-09) prefer a constructor-injected, api-owned
    ``LiveAdapter`` instance; this helper keeps the v1-plan entry point working
    for standalone use.
    """
    return _default_adapter().trigger(reason)
