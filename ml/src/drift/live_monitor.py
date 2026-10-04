"""
Live concept-drift monitor for the /predict streaming path (master plan §5.3, §9.2).

One LiveDriftMonitor instance is owned by ml/api.py (TASK-08 wires it in).
Every /predict batch feeds process_batch() with the §9.1 batch_record list;
GET /concept-drift renders get_status() verbatim (the §8 contract — field
names are law, the UI builds against them).

Signals per batch / per flow:
  1. attack_ratio (fraction of batch labelled non-Normal, post rule-override)
       -> ADWIN(delta=0.002) AND PageHinkley. Batch-level, not per-flow: a
       binary burst would double-fire on a per-flow stream.
  2. mean_confidence -> ADWIN(delta=0.01). Warning-only, never fires drift.
  3. pseudo_error (per rule-override flow: 1 when final label != model's raw
       label) -> DDM-style running error-rate. Batches with zero overrides
       skip the update — no evidence to learn from.
  4. Per-slot PSI on slots [1, 4, 5, 14, 44]: reference = first `window`
       flows since reset, recent = rolling last `window` (10-bin histogram,
       log1p on byte/duration slots, raw on the HTTP-status slot).
  5. KS test on slot-14 raw values (reference vs recent deques).

Drift decision (§5.3): ADWIN(attack_ratio) OR PageHinkley OR >=2 slots drifted.
On drift: one event (cap 20, newest first), the fired detectors are reset,
reference histograms rotate to the recent window, and the event waits for the
adapter via consume_drift_event().

Wiring note for TASK-08: prefer constructor injection —
    _drift_monitor = LiveDriftMonitor(STATE_DIR / "drift_state.json")
If api.py also wants module-level helpers (detect_drift), call
set_default_monitor(_drift_monitor) once at startup; the helpers fall back to
a lazy default instance under ml/artifacts/state/ otherwise.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import warnings
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from river.drift import PageHinkley
from scipy.stats import ks_2samp

from ml.src.drift.detectors import ADWINDriftDetector

logger = logging.getLogger(__name__)

# --- Frozen contract constants ------------------------------------------------

NORMAL_LABEL = "Normal Traffic"
PSI_SLOTS = (1, 4, 5, 14, 44)
SLOT_NAMES = {
    1: "Flow Duration",
    4: "Total Fwd Bytes",
    5: "Total Bwd Bytes",
    14: "Flow Bytes/s",
    44: "HTTP Status Code",
}
LOG1P_SLOTS = (1, 4, 5, 14)  # slot 44 (HTTP status) is binned raw

PSI_BINS = 10
PSI_EPS = 1e-4
PSI_MINOR = 0.10
PSI_DRIFTED = 0.25
KS_ALPHA = 0.05
KS_MIN_SAMPLES = 10
MAX_DRIFT_EVENTS = 20
PERSIST_EVERY_N_BATCHES = 25

ATTACK_ADWIN_DELTA = 0.002
CONFIDENCE_ADWIN_DELTA = 0.01
# PageHinkley defaults (threshold=50, alpha=0.9999) per plan — detects the
# sustained jump in attack_ratio that defines a campaign.


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class LiveDriftMonitor:
    """Streaming drift monitor; owns all §5.2 drift_state.json persistence."""

    def __init__(self, state_path: Path, window: int = 500):
        self.state_path = Path(state_path)
        self.window = window
        self._lock = threading.Lock()

        # Counters
        self.samples_processed = 0
        self.samples_since_reset = 0  # == samples_processed_since_retrain in §8
        self.batches_processed = 0
        self.last_drift_timestamp: Optional[str] = None

        # Drift state
        self.drift_events: list[dict[str, Any]] = []
        self._pending_event: Optional[dict[str, Any]] = None
        self._drift_active = False  # latched until reset_reference()/reset()

        # Detectors (§5.3)
        self._attack_adwin = ADWINDriftDetector(delta=ATTACK_ADWIN_DELTA, signal_name="attack_ratio")
        self._confidence_adwin = ADWINDriftDetector(delta=CONFIDENCE_ADWIN_DELTA, signal_name="mean_confidence")
        self._ph = PageHinkley()
        self._init_ddm()

        # Last-update flags for status reporting
        self._last_adwin_signal = False
        self._last_ph_signal = False
        self._last_confidence_signal = False

        # Feature windows: reference = first `window` flows since reset,
        # recent = rolling last `window`. Same raw values feed PSI (log1p) and
        # the slot-14 KS test (raw).
        self._ref: dict[int, list[float]] = {s: [] for s in PSI_SLOTS}
        self._recent: dict[int, deque[float]] = {s: deque(maxlen=window) for s in PSI_SLOTS}
        self._last_psi: dict[int, float] = {s: 0.0 for s in PSI_SLOTS}
        self._last_ks: Optional[dict[str, Any]] = None

        # Recent attack flags — attack_ratio_recent in the contract
        self._attack_flags: deque[int] = deque(maxlen=window)

        self._restore()

    # ------------------------------------------------------------------
    # Public interface (§9.2 — do not rename; TASK-08 builds against this)
    # ------------------------------------------------------------------

    @property
    def drift_detected(self) -> bool:
        with self._lock:
            return self._drift_active

    def process_batch(self, records: list[dict]) -> dict:
        """Feed one /predict batch. Returns batch drift summary.

        Fires at most one drift event per batch.
        """
        with self._lock:
            if not records:
                return {"batch_size": 0, "drift_detected": False, "drift_state": self._drift_state(), "status": self._status()}

            batch_size = len(records)
            attack_count = 0
            confidence_sum = 0.0
            confidence_count = 0
            pseudo_errors: list[float] = []

            for r in records:
                label = str(r.get("label") or "")
                is_attack = bool(label) and label != NORMAL_LABEL
                attack_count += 1 if is_attack else 0
                self._attack_flags.append(1 if is_attack else 0)

                conf = _as_float(r.get("confidence"))
                if conf is not None:
                    confidence_sum += conf
                    confidence_count += 1

                # Pseudo-error evidence only exists where a rule fired.
                if r.get("rule_override"):
                    pseudo_errors.append(1.0 if label != str(r.get("model_raw_label") or "") else 0.0)

                raw = r.get("raw_features")
                if isinstance(raw, (list, tuple)) and len(raw) > max(PSI_SLOTS):
                    for slot in PSI_SLOTS:
                        v = _as_float(raw[slot])
                        if v is None:
                            continue
                        if len(self._ref[slot]) < self.window:
                            self._ref[slot].append(v)
                        self._recent[slot].append(v)

            attack_ratio = attack_count / batch_size
            mean_confidence = (confidence_sum / confidence_count) if confidence_count else 0.0

            self.samples_processed += batch_size
            self.samples_since_reset += batch_size
            self.batches_processed += 1

            # --- Detector updates -------------------------------------------
            adwin_drift, adwin_width, adwin_est = self._attack_adwin.update(attack_ratio)
            conf_drift, _, _ = self._confidence_adwin.update(mean_confidence)
            self._ph.update(attack_ratio)
            ph_drift = bool(self._ph.drift_detected)
            self._last_adwin_signal = bool(adwin_drift)
            self._last_ph_signal = ph_drift
            self._last_confidence_signal = bool(conf_drift)

            for err in pseudo_errors:
                self._ddm_update(err)

            # --- Feature signals --------------------------------------------
            slots_drifted = 0
            for slot in PSI_SLOTS:
                psi = self._psi(slot)
                self._last_psi[slot] = psi
                if psi > PSI_DRIFTED:
                    slots_drifted += 1
            self._update_ks()

            # --- Drift decision (§5.3) ---------------------------------------
            decision = adwin_drift or ph_drift or slots_drifted >= 2
            event = None
            if decision and not self._drift_active:
                event = self._fire_drift(
                    adwin_drift=adwin_drift,
                    ph_drift=ph_drift,
                    slots_drifted=slots_drifted,
                    attack_ratio=attack_ratio,
                    adwin_est=adwin_est,
                    adwin_width=adwin_width,
                )

            if self.batches_processed % PERSIST_EVERY_N_BATCHES == 0:
                self._persist()

            return {
                "batch_size": batch_size,
                "attack_ratio": round(attack_ratio, 4),
                "mean_confidence": round(mean_confidence, 4),
                "drift_detected": event is not None,
                "drift_state": self._drift_state(),
                "status": self._status(),
                "signals": {
                    "adwin_attack_ratio": bool(adwin_drift),
                    "page_hinkley": ph_drift,
                    "slots_drifted": slots_drifted,
                    "confidence_warning": bool(conf_drift),
                    "ddm_warning": self._ddm_warning,
                    "ddm_drift": self._ddm_drift,
                },
                "event": event,
            }

    def get_status(self) -> dict:
        """Exact §8 /concept-drift contract."""
        with self._lock:
            features = [
                {
                    "slot": slot,
                    "name": SLOT_NAMES[slot],
                    "drift": round(psi, 4),
                    "status": self._psi_status(psi),
                }
                for slot in PSI_SLOTS
                for psi in (self._psi(slot),)
            ]
            return {
                "status": self._status(),
                "drift_detected": self._drift_active,
                "drift_state": self._drift_state(),
                "samples_processed": self.samples_processed,
                "samples_processed_since_retrain": self.samples_since_reset,
                "last_drift_timestamp": self.last_drift_timestamp,
                "attack_ratio_recent": round(self._recent_attack_ratio(), 4),
                "detector_algorithms": {
                    "ADWIN_attack_ratio": {
                        "status": "drift" if self._last_adwin_signal else "stable",
                        "estimation": round(float(self._attack_adwin.adwin.estimation), 4),
                        "width": int(self._attack_adwin.adwin.width),
                        "drift_signal": self._last_adwin_signal,
                    },
                    "PageHinkley": {
                        "status": "drift" if self._last_ph_signal else "nominal",
                        "sum_val": round(self._ph_stat(), 4),
                        "threshold": float(self._ph.threshold),
                        "drift_signal": self._last_ph_signal,
                    },
                    "DDM_pseudo_error": {
                        "status": "drift" if self._ddm_drift else ("warning" if self._ddm_warning else "stable"),
                        "error_rate": round(self._ddm_p, 4),
                        "warning_level": round(self._ddm_p_min + 2 * self._ddm_s_min, 4)
                        if math.isfinite(self._ddm_p_min)
                        else None,
                        "drift_signal": self._ddm_drift,
                    },
                    "KS_Test": {
                        "status": "drift" if (self._last_ks and self._last_ks["drift_signal"]) else "stable",
                        "stat": self._last_ks["stat"] if self._last_ks else None,
                        "p_value": self._last_ks["p_value"] if self._last_ks else None,
                        "drift_signal": bool(self._last_ks and self._last_ks["drift_signal"]),
                    },
                },
                "labrooms_features_drift": features,
                "drift_events": list(self.drift_events),
            }

    def consume_drift_event(self) -> Optional[dict]:
        """Pop the pending drift trigger (for the adapter). None if none."""
        with self._lock:
            event = self._pending_event
            self._pending_event = None
            return event

    def reset_reference(self) -> None:
        """Rotate reference<-recent baselines (call after every promotion)."""
        with self._lock:
            self._rotate_reference()
            # The rotated window becomes the new retrain baseline.
            self.samples_since_reset = max((len(v) for v in self._ref.values()), default=0)
            self._drift_active = False
            # DDM only updates on override batches, so its warning/drift flags
            # would otherwise stay stale after the world heals.
            self._init_ddm()
            self._persist()

    def reset(self) -> None:
        """Full reset — demo reset / fresh baseline."""
        with self._lock:
            self.samples_processed = 0
            self.samples_since_reset = 0
            self.batches_processed = 0
            self.last_drift_timestamp = None
            self.drift_events = []
            self._pending_event = None
            self._drift_active = False
            self._attack_adwin.reset()
            self._confidence_adwin.reset()
            self._ph = PageHinkley()
            self._init_ddm()
            self._last_adwin_signal = self._last_ph_signal = self._last_confidence_signal = False
            self._ref = {s: [] for s in PSI_SLOTS}
            self._recent = {s: deque(maxlen=self.window) for s in PSI_SLOTS}
            self._last_psi = {s: 0.0 for s in PSI_SLOTS}
            self._last_ks = None
            self._attack_flags.clear()
            self._persist()

    # ------------------------------------------------------------------
    # Drift event
    # ------------------------------------------------------------------

    def _fire_drift(
        self,
        *,
        adwin_drift: bool,
        ph_drift: bool,
        slots_drifted: int,
        attack_ratio: float,
        adwin_est: float,
        adwin_width: int,
    ) -> dict:
        ts = _utc_now()
        reasons: list[str] = []
        if adwin_drift:
            reasons.append(f"ADWIN attack_ratio estimation jumped to {adwin_est:.2f} (width {adwin_width})")
        if ph_drift:
            reasons.append(f"PageHinkley cumulative sum {self._ph_stat():.1f} >= threshold {self._ph.threshold:.0f}")
        if slots_drifted:
            drifted = [SLOT_NAMES[s] for s in PSI_SLOTS if self._last_psi[s] > PSI_DRIFTED]
            reasons.append(f"PSI drifted on {slots_drifted} slots ({', '.join(drifted)})")

        detector = "ADWIN" if adwin_drift else ("PageHinkley" if ph_drift else "PSI")
        event = {
            "timestamp": ts,
            "signal": "attack_ratio" if (adwin_drift or ph_drift) else "feature_psi",
            "detector": detector,
            "samples_processed": self.samples_processed,
            "detail": f"attack_ratio {attack_ratio:.2f}; " + "; ".join(reasons),
        }

        self.drift_events.insert(0, event)
        del self.drift_events[MAX_DRIFT_EVENTS:]
        self.last_drift_timestamp = ts
        self._pending_event = event
        self._drift_active = True

        # A fired detector would re-alert on every following batch — reset the
        # ones that fired and roll the feature baseline to the new world.
        if adwin_drift:
            self._attack_adwin.reset()
            self._last_adwin_signal = False
        if ph_drift:
            self._ph = PageHinkley()
            self._last_ph_signal = False
        self._rotate_reference()
        self._persist()
        logger.info("drift event fired (%s): %s", detector, event["detail"])
        return event

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _psi(self, slot: int) -> float:
        ref = self._ref[slot]
        recent = list(self._recent[slot])
        if not ref or not recent:
            return 0.0
        transform = (lambda v: math.log1p(max(v, 0.0))) if slot in LOG1P_SLOTS else (lambda v: v)
        r = np.array([transform(v) for v in ref], dtype=float)
        c = np.array([transform(v) for v in recent], dtype=float)

        lo, hi = float(r.min()), float(r.max())
        if hi == lo:
            edges = np.array([-np.inf, lo, np.inf])
        else:
            edges = np.linspace(lo, hi, PSI_BINS + 1)
            edges[0] = -np.inf
            edges[-1] = np.inf

        ref_counts, _ = np.histogram(r, bins=edges)
        rec_counts, _ = np.histogram(c, bins=edges)
        ref_pct = np.clip(ref_counts / len(r), PSI_EPS, None)
        rec_pct = np.clip(rec_counts / len(c), PSI_EPS, None)
        return float(np.sum((ref_pct - rec_pct) * np.log(ref_pct / rec_pct)))

    @staticmethod
    def _psi_status(psi: float) -> str:
        if psi > PSI_DRIFTED:
            return "drifted"
        if psi >= PSI_MINOR:
            return "minor_shift"
        return "stable"

    def _update_ks(self) -> None:
        ref = self._ref[14]
        recent = list(self._recent[14])
        if len(ref) < KS_MIN_SAMPLES or len(recent) < KS_MIN_SAMPLES:
            self._last_ks = None
            return
        with warnings.catch_warnings():
            # Identical/degenerate samples make exact p-value calc fail loudly;
            # scipy falls back to asymptotic which is fine here.
            warnings.simplefilter("ignore", RuntimeWarning)
            stat, p_value = ks_2samp(ref, recent)
        self._last_ks = {
            "stat": round(float(stat), 4),
            "p_value": round(float(p_value), 4),
            "drift_signal": bool(p_value < KS_ALPHA),
        }

    # DDM-style running error-rate tracker (classic DDM thresholds:
    # warning at p_min + 2*s_min, drift at p_min + 3*s_min).
    def _init_ddm(self) -> None:
        self._ddm_n = 0
        self._ddm_p = 0.0
        self._ddm_p_min = math.inf
        self._ddm_s_min = math.inf
        self._ddm_warning = False
        self._ddm_drift = False

    def _ddm_update(self, err: float) -> None:
        self._ddm_n += 1
        self._ddm_p += (err - self._ddm_p) / self._ddm_n
        s = math.sqrt(self._ddm_p * (1.0 - self._ddm_p) / self._ddm_n) if self._ddm_n > 0 else 0.0
        level = self._ddm_p + s
        if level <= self._ddm_p_min + self._ddm_s_min:
            self._ddm_p_min = self._ddm_p
            self._ddm_s_min = s
        self._ddm_warning = level >= self._ddm_p_min + 2 * self._ddm_s_min
        self._ddm_drift = level >= self._ddm_p_min + 3 * self._ddm_s_min

    def _ph_stat(self) -> float:
        # Live PH test statistic: distance of the cumulative sum from its
        # running extreme, either direction (mode="both").
        inc = getattr(self._ph, "_sum_increase", 0.0) - getattr(self._ph, "_min_increase", 0.0)
        dec = getattr(self._ph, "_max_decrease", 0.0) - getattr(self._ph, "_sum_decrease", 0.0)
        return float(max(inc, dec, 0.0))

    def _recent_attack_ratio(self) -> float:
        if not self._attack_flags:
            return 0.0
        return sum(self._attack_flags) / len(self._attack_flags)

    def _status(self) -> str:
        return "warming_up" if self.samples_since_reset < self.window else "active"

    def _drift_state(self) -> str:
        if self._drift_active:
            return "drift"
        one_slot = sum(1 for s in PSI_SLOTS if self._last_psi[s] > PSI_DRIFTED)
        if self._last_confidence_signal or self._ddm_warning or self._ddm_drift or one_slot == 1:
            return "warning"
        return "stable"

    def _rotate_reference(self) -> None:
        for slot in PSI_SLOTS:
            # len(ref) < window keeps filling — the rotated snapshot heads the
            # new reference period.
            self._ref[slot] = list(self._recent[slot])

    # ------------------------------------------------------------------
    # Persistence (§5.2 — drift_state.json)
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Write drift_state.json. Detector internals can't round-trip (River
        objects), so estimations/widths are stored for the record plus all
        restorable counters, windows, and event state."""
        state = {
            "version": 1,
            "samples_processed": self.samples_processed,
            "samples_since_reset": self.samples_since_reset,
            "batches_processed": self.batches_processed,
            "last_drift_timestamp": self.last_drift_timestamp,
            "drift_events": self.drift_events,
            "pending_event": self._pending_event,
            "drift_active": self._drift_active,
            "attack_flags": list(self._attack_flags),
            "last_signals": {
                "adwin": self._last_adwin_signal,
                "page_hinkley": self._last_ph_signal,
                "confidence": self._last_confidence_signal,
            },
            "detectors": {
                "attack_adwin": {
                    "delta": ATTACK_ADWIN_DELTA,
                    "estimation": float(self._attack_adwin.adwin.estimation),
                    "width": int(self._attack_adwin.adwin.width),
                },
                "confidence_adwin": {
                    "delta": CONFIDENCE_ADWIN_DELTA,
                    "estimation": float(self._confidence_adwin.adwin.estimation),
                    "width": int(self._confidence_adwin.adwin.width),
                },
                "page_hinkley": {
                    "threshold": float(self._ph.threshold),
                    "x_mean_n": float(getattr(self._ph._x_mean, "n", 0.0)),
                    "x_mean": float(getattr(self._ph._x_mean, "mean", 0.0)),
                    "sum_increase": float(getattr(self._ph, "_sum_increase", 0.0)),
                    "min_increase": float(getattr(self._ph, "_min_increase", 0.0)),
                    "sum_decrease": float(getattr(self._ph, "_sum_decrease", 0.0)),
                    "max_decrease": float(getattr(self._ph, "_max_decrease", 0.0)),
                },
                "ddm_pseudo_error": {
                    "n": self._ddm_n,
                    "error_rate": self._ddm_p,
                    "p_min": self._ddm_p_min if math.isfinite(self._ddm_p_min) else None,
                    "s_min": self._ddm_s_min if math.isfinite(self._ddm_s_min) else None,
                    "warning": self._ddm_warning,
                    "drift": self._ddm_drift,
                },
            },
            "ref_values": {str(s): self._ref[s] for s in PSI_SLOTS},
            "recent_values": {str(s): list(self._recent[s]) for s in PSI_SLOTS},
            "last_psi": {str(s): self._last_psi[s] for s in PSI_SLOTS},
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(self.state_path)
        except OSError as exc:
            logger.warning("drift_state persist failed: %s", exc)

    def _restore(self) -> None:
        """Restore drift_state.json; missing/corrupt -> fresh start."""
        if not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text())
            self.samples_processed = int(state.get("samples_processed", 0))
            self.samples_since_reset = int(state.get("samples_since_reset", 0))
            self.batches_processed = int(state.get("batches_processed", 0))
            self.last_drift_timestamp = state.get("last_drift_timestamp")
            self.drift_events = list(state.get("drift_events") or [])[:MAX_DRIFT_EVENTS]
            self._pending_event = state.get("pending_event")
            self._drift_active = bool(state.get("drift_active"))
            self._attack_flags = deque(state.get("attack_flags") or [], maxlen=self.window)

            signals = state.get("last_signals") or {}
            self._last_adwin_signal = bool(signals.get("adwin"))
            self._last_ph_signal = bool(signals.get("page_hinkley"))
            self._last_confidence_signal = bool(signals.get("confidence"))

            detectors = state.get("detectors") or {}
            ph = detectors.get("page_hinkley") or {}
            if ph:
                try:
                    self._ph._x_mean.n = float(ph.get("x_mean_n", 0.0))
                    self._ph._x_mean._mean = float(ph.get("x_mean", 0.0))
                    self._ph._sum_increase = float(ph.get("sum_increase", 0.0))
                    self._ph._min_increase = float(ph.get("min_increase", 0.0))
                    self._ph._sum_decrease = float(ph.get("sum_decrease", 0.0))
                    self._ph._max_decrease = float(ph.get("max_decrease", 0.0))
                except (TypeError, AttributeError) as exc:
                    logger.warning("PageHinkley state restore skipped: %s", exc)

            ddm = detectors.get("ddm_pseudo_error") or {}
            if ddm:
                self._ddm_n = int(ddm.get("n", 0))
                self._ddm_p = float(ddm.get("error_rate", 0.0))
                self._ddm_p_min = float(ddm["p_min"]) if ddm.get("p_min") is not None else math.inf
                self._ddm_s_min = float(ddm["s_min"]) if ddm.get("s_min") is not None else math.inf
                self._ddm_warning = bool(ddm.get("warning"))
                self._ddm_drift = bool(ddm.get("drift"))

            ref_values = state.get("ref_values") or {}
            recent_values = state.get("recent_values") or {}
            for slot in PSI_SLOTS:
                self._ref[slot] = [float(v) for v in (ref_values.get(str(slot)) or [])][: self.window]
                self._recent[slot] = deque(
                    [float(v) for v in (recent_values.get(str(slot)) or [])], maxlen=self.window
                )
            last_psi = state.get("last_psi") or {}
            for slot in PSI_SLOTS:
                self._last_psi[slot] = float(last_psi.get(str(slot), 0.0))
            self._update_ks()
            logger.info(
                "drift state restored: %s samples, %s events, active=%s",
                self.samples_processed,
                len(self.drift_events),
                self._drift_active,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("drift_state.json unreadable (%s) — starting fresh", exc)
            self._init_fresh()

    def _init_fresh(self) -> None:
        """Reset to constructor defaults without re-reading the state file."""
        self.samples_processed = 0
        self.samples_since_reset = 0
        self.batches_processed = 0
        self.last_drift_timestamp = None
        self.drift_events = []
        self._pending_event = None
        self._drift_active = False
        self._attack_adwin = ADWINDriftDetector(delta=ATTACK_ADWIN_DELTA, signal_name="attack_ratio")
        self._confidence_adwin = ADWINDriftDetector(delta=CONFIDENCE_ADWIN_DELTA, signal_name="mean_confidence")
        self._ph = PageHinkley()
        self._init_ddm()
        self._last_adwin_signal = self._last_ph_signal = self._last_confidence_signal = False
        self._ref = {s: [] for s in PSI_SLOTS}
        self._recent = {s: deque(maxlen=self.window) for s in PSI_SLOTS}
        self._last_psi = {s: 0.0 for s in PSI_SLOTS}
        self._last_ks = None
        self._attack_flags = deque(maxlen=self.window)


# ---------------------------------------------------------------------------
# Module-level singleton helpers — api.py isn't wired yet, so TASK-08 should
# construct LiveDriftMonitor itself and register it with set_default_monitor().
# ---------------------------------------------------------------------------

_default_monitor: Optional[LiveDriftMonitor] = None


def _default_state_path() -> Path:
    return Path(__file__).resolve().parents[2] / "artifacts" / "state" / "drift_state.json"


def set_default_monitor(monitor: Optional[LiveDriftMonitor]) -> None:
    """Register the app-owned instance (call once from api.py startup)."""
    global _default_monitor
    _default_monitor = monitor


def get_default_monitor() -> LiveDriftMonitor:
    """Lazy singleton under ml/artifacts/state/ when nothing was injected."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = LiveDriftMonitor(_default_state_path())
    return _default_monitor


def detect_drift() -> bool:
    """True while a drift event is active (latched until reset_reference())."""
    return get_default_monitor().drift_detected
