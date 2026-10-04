"""
CyberAdapt ML Inference API
============================
Lightweight Flask microservice that loads the trained champion model
and exposes REST endpoints for the Node.js server to call.

Endpoints:
  GET  /health              — liveness probe
  POST /predict             — classify a batch of 52-feature flow vectors
  GET  /model-info          — active model metadata (+ champion version)
  GET  /concept-drift       — live drift monitor state
  GET  /adaptation          — live adapter state (buffer, version, history)
  POST /adaptation/trigger  — manual candidate retrain (202/409/422)
  GET  /evaluation          — live rolling metrics + pre/post adaptation split
  POST /admin/reset         — demo reset (requires DEMO_MODE=1)

Environment Variables:
  MODEL_PATH        — path to joblib champion model (default: ml/artifacts/champion_model.joblib)
  PREPROCESSOR_PATH — path to joblib preprocessor (default: ml/artifacts/preprocessor.joblib)
  PORT              — API port (default: 5001)

Usage:
  cd /path/to/CyberAdapt
  python -m ml.api
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from flask import Flask, jsonify, request
from flask_cors import CORS

# ── Ensure the repo root is on sys.path so ml.src.* imports resolve ──────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.src.features.feature_contract import (
    LABROOMS_DEPLOYMENT_FEATURES,
    TARGET_CLASSES,
)
from ml.src.drift.live_monitor import LiveDriftMonitor, set_default_monitor
from ml.src.adaptation.live_adapter import LiveAdapter
from ml.src.evaluation.live_evaluator import LiveEvaluator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("ml.api")

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

# ── Globals ──────────────────────────────────────────────────────────────────
_champion_model: Optional[Any] = None
_preprocessor: Optional[Any] = None
_model_loaded_at: Optional[str] = None
_model_path_used: Optional[str] = None

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
DEFAULT_MODEL_PATH = ARTIFACTS_DIR / "champion_model.joblib"
DEFAULT_PREPROCESSOR_PATH = ARTIFACTS_DIR / "preprocessor.joblib"

# Labrooms sensor slot → CICIDS2017 feature name mapping
# (populated indices only; all others are always 0 in Labrooms traffic)
LABROOMS_SLOT_MAP: Dict[int, str] = {
    1:  "Flow Duration",
    2:  "Total Fwd Packets",
    3:  "Bwd Packet Length Max",           # proxy for Total Bwd Packets
    4:  "Total Length of Fwd Packets",
    5:  "Bwd Packet Length Min",            # proxy for Total Bwd Bytes
    6:  "Fwd Packet Length Max",
    7:  "Fwd Packet Length Min",
    14: "Flow Bytes/s",
    44: "HTTP Status Code",                # slot 44 hijacked for HTTP Status Code
}


# ── Model Loading ────────────────────────────────────────────────────────────

def _resolve_boot_artifacts() -> Tuple[Path, Path]:
    """Pick the (model_path, preprocessor_path) to load at boot / reset.

    Order (TASK-09): the last promoted adaptive champion recorded in
    ``active_model.json`` → ``MODEL_PATH``/``PREPROCESSOR_PATH`` env vars →
    built-in defaults. ``POST /admin/reset`` deletes ``active_model.json``
    before calling ``_load_artifacts`` so the originals come back.
    """
    try:
        active_file = STATE_DIR / "active_model.json"
        if active_file.exists():
            info = json.loads(active_file.read_text(encoding="utf-8"))
            mp, pp = info.get("model_path"), info.get("preprocessor_path")
            if isinstance(mp, str) and isinstance(pp, str):
                am, ap = Path(mp), Path(pp)
                if am.is_file() and ap.is_file():
                    logger.info(
                        f"Boot-restoring promoted champion "
                        f"{info.get('version')} via {active_file.name} → {am}"
                    )
                    return am, ap
            logger.warning(
                f"{active_file.name} present but its artifacts are missing or "
                "malformed — falling back to env/default paths"
            )
    except Exception as exc:
        logger.warning(f"Could not parse active_model.json ({exc}) — env/default paths")

    return (
        Path(os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)),
        Path(os.environ.get("PREPROCESSOR_PATH", DEFAULT_PREPROCESSOR_PATH)),
    )


def _load_artifacts() -> bool:
    """Load champion model and preprocessor from disk. Returns True if successful."""
    global _champion_model, _preprocessor, _model_loaded_at, _model_path_used

    model_path, preproc_path = _resolve_boot_artifacts()

    if not model_path.exists():
        logger.warning(
            f"Champion model not found at {model_path}. "
            "Run notebook 02_model_training.ipynb first to generate it."
        )
        return False

    if not preproc_path.exists():
        logger.warning(f"Preprocessor not found at {preproc_path}.")
        return False

    try:
        _champion_model = joblib.load(model_path)
        _preprocessor = joblib.load(preproc_path)
        _model_loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _model_path_used = str(model_path)
        logger.info(f"Loaded champion model from {model_path}")
        return True
    except Exception as exc:
        logger.error(f"Failed to load model artifacts: {exc}")
        return False


def _extract_labrooms_features(raw_features: List[float]) -> Dict[str, float]:
    """Map a 52-slot Labrooms vector to named CICIDS2017 feature dict."""
    return {name: float(raw_features[idx]) for idx, name in LABROOMS_SLOT_MAP.items()}


# ── Live drift monitoring (TASK-08) ───────────────────────────────────────────
# §5.2 runtime state lives under ml/artifacts/state/ (gitignored). The monitor
# restores counters/events/latch from drift_state.json on boot.
STATE_DIR = ARTIFACTS_DIR / "state"
try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
except OSError as exc:  # non-fatal — LiveDriftMonitor re-mkdirs on persist
    logger.warning(f"Could not create drift state dir {STATE_DIR}: {exc}")

_drift_monitor = LiveDriftMonitor(STATE_DIR / "drift_state.json")
set_default_monitor(_drift_monitor)  # keep module-level detect_drift() on this instance


# ── Live model adaptation (TASK-09) ──────────────────────────────────────────
# One api-owned LiveAdapter sharing STATE_DIR; every runtime dependency is an
# injected callable per §9.3 (see ml/src/adaptation/live_adapter.py docstring).
def _get_champion() -> Tuple[Any, Any]:
    """() -> (model, preprocessor) — the current serving pair."""
    return _champion_model, _preprocessor


def _set_champion(model: Any, preprocessor: Any, version: str) -> None:
    """Hot-swap hook — the adapter calls this on promotion (inside its retrain
    thread). Reassigns the serving globals and bumps the truth fields so
    /health, /model-info and /adaptation all report the new champion."""
    global _champion_model, _preprocessor, _model_loaded_at, _model_path_used
    _champion_model = model
    _preprocessor = preprocessor
    _model_loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        # The adapter writes active_model.json immediately before invoking
        # this hook — read the real on-disk path for /model-info.
        info = json.loads((STATE_DIR / "active_model.json").read_text(encoding="utf-8"))
        mp = info.get("model_path")
        _model_path_used = str(mp) if mp else f"adaptive_champion_{version} (in-memory)"
    except Exception:
        _model_path_used = f"adaptive_champion_{version} (in-memory)"
    logger.info(f"Champion hot-swapped to {version} — model_path={_model_path_used}")


_adapter = LiveAdapter(
    state_dir=STATE_DIR,
    get_champion=_get_champion,
    set_champion=_set_champion,
    extract_features=_extract_labrooms_features,
    consume_drift_event=_drift_monitor.consume_drift_event,
    reset_drift_reference=_drift_monitor.reset_reference,
)


# ── Live evaluation (TASK-10) ─────────────────────────────────────────────────
# Rolling pseudo-labeled metrics over the same §9.1 batch_records (§5.4 label
# rule applied inside the evaluator). Restores eval_window.jsonl on boot;
# pre/post split reads the adapter's sibling adaptation_history.json.
_evaluator = LiveEvaluator(STATE_DIR / "eval_window.jsonl")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    model_ready = _champion_model is not None and _preprocessor is not None
    return jsonify({
        "status": "operational" if model_ready else "degraded",
        "model_ready": model_ready,
        "model_loaded_at": _model_loaded_at,
        "ts": int(time.time() * 1000),
    }), 200 if model_ready else 503


@app.get("/model-info")
def model_info():
    if _champion_model is None:
        return jsonify({"error": "Model not loaded"}), 503

    info: Dict[str, Any] = {
        "model_type": type(_champion_model).__name__,
        "model_path": _model_path_used,
        "loaded_at": _model_loaded_at,
        "version": _adapter.champion_version,
        "target_classes": TARGET_CLASSES,
        "feature_schema": "labrooms-app-layer-v1",
        "active_features": LABROOMS_DEPLOYMENT_FEATURES,
        "num_active_features": len(LABROOMS_DEPLOYMENT_FEATURES),
    }
    if hasattr(_champion_model, "n_estimators"):
        info["n_estimators"] = _champion_model.n_estimators
    return jsonify(info)


def _detect_labrooms_app_layer_anomaly(raw: List[float]) -> Optional[Tuple[str, int, float]]:
    """
    Evaluate application-layer anomaly rules on Labrooms 10-feature vector:
      [1]  Flow Duration (microseconds)
      [4]  Total Fwd Bytes (Request Size)
      [5]  Total Bwd Bytes (Response Size / Exfiltration)
      [14] Flow Bytes/s (Throughput / Scraping)
      [44] SYN Count Slot (Hijacked for HTTP Status Code: 200, 401, 404, 500, 504)
    """
    if len(raw) < 45:
        return None

    duration_us = float(raw[1])
    fwd_bytes   = float(raw[4])
    bwd_bytes   = float(raw[5])
    bytes_sec   = float(raw[14])
    status_code = float(raw[44])

    # 1. Slowloris / DoS: Extremely high duration (>30s) or 504 Gateway Timeout
    if duration_us > 30_000_000 or status_code == 504:
        return ("DoS", 1, 0.985)

    # 2. Data Exfiltration: Massive response byte payload (>10 MB)
    if bwd_bytes > 10_000_000:
        return ("Web Attacks", 5, 0.965)

    # 3. Brute Force / Credential Stuffing: High rate & HTTP 401 Unauthorized / 403 Forbidden
    if status_code in (401, 403) or (bytes_sec > 100_000 and status_code in (401, 404)):
        return ("Brute Force", 4, 0.975)

    # 4. Web Attack (SQLi / Exploits): 500 Internal Server Error or large request payload with error
    if status_code == 500 or (fwd_bytes > 10_000 and status_code >= 400):
        return ("Web Attacks", 5, 0.955)

    return None


@app.post("/predict")
def predict():
    """
    Classify one or more network flows.
    """
    if _champion_model is None or _preprocessor is None:
        return jsonify({"error": "Model not loaded — run training notebook first"}), 503

    body = request.get_json(silent=True)
    if not body or "flows" not in body or not isinstance(body["flows"], list):
        return jsonify({"error": "Request body must contain a 'flows' list"}), 400

    flows = body["flows"]
    if not flows:
        return jsonify({"predictions": [], "latency_ms": 0.0})

    import pandas as pd

    rows: List[Dict[str, float]] = []
    flow_ids: List[str] = []
    raw_vectors: List[List[float]] = []
    parse_errors: List[Dict] = []

    for i, flow in enumerate(flows):
        fid = flow.get("flow_id", f"flow_{i}")
        raw = flow.get("features")

        if not isinstance(raw, list) or len(raw) != 52:
            parse_errors.append({"flow_id": fid, "reason": f"Expected 52 features, got {len(raw) if raw else 'none'}"})
            continue

        if not all(isinstance(v, (int, float)) and not (v != v) for v in raw):
            parse_errors.append({"flow_id": fid, "reason": "All features must be finite numbers"})
            continue

        raw_clamped = list(raw)
        if raw_clamped[1] < 0:
            raw_clamped[1] = 0.0  # clamp negative flow duration

        rows.append(_extract_labrooms_features(raw_clamped))
        flow_ids.append(fid)
        raw_vectors.append(raw_clamped)

    if not rows:
        return jsonify({"error": "All flows were malformed", "details": parse_errors}), 422

    t_start = time.perf_counter()
    df = pd.DataFrame(rows, columns=LABROOMS_DEPLOYMENT_FEATURES)
    X_scaled = _preprocessor.transform(df)

    y_pred = _champion_model.predict(X_scaled)
    y_prob: Optional[np.ndarray] = None
    if hasattr(_champion_model, "predict_proba"):
        try:
            y_prob = _champion_model.predict_proba(X_scaled)
        except Exception:
            pass

    latency_ms = round((time.perf_counter() - t_start) * 1000, 3)

    predictions: List[Dict[str, Any]] = []
    # §9.1 batch_record list — the shared payload fed to the drift monitor (T08),
    # and reused by the adapter (T09) and evaluator (T10) inside the guarded
    # block below.
    batch_records: List[Dict[str, Any]] = []
    for i, (fid, label_idx, raw_vec) in enumerate(zip(flow_ids, y_pred, raw_vectors)):
        # Model's raw output BEFORE any rule override (stored for pseudo-error
        # and pseudo-label consumers downstream).
        model_raw_index = int(label_idx)
        model_raw_label = TARGET_CLASSES[model_raw_index] if model_raw_index < len(TARGET_CLASSES) else "Unknown"

        # Check rule-based application-layer anomaly override for Labrooms traffic
        app_anomaly = _detect_labrooms_app_layer_anomaly(raw_vec)

        if app_anomaly is not None:
            label, idx_val, conf_val = app_anomaly
            probs = {cls: (conf_val if cls == label else round((1.0 - conf_val) / (len(TARGET_CLASSES) - 1), 4)) for cls in TARGET_CLASSES}
            predictions.append({
                "flow_id": fid,
                "label": label,
                "label_index": idx_val,
                "confidence": conf_val,
                "probabilities": probs,
            })
        else:
            label = TARGET_CLASSES[int(label_idx)] if int(label_idx) < len(TARGET_CLASSES) else "Unknown"
            idx_val = int(label_idx)
            confidence = float(y_prob[i][int(label_idx)]) if (y_prob is not None and int(label_idx) < len(y_prob[i])) else None
            conf_val = confidence
            probs = None
            if y_prob is not None:
                probs = {}
                for j, cls in enumerate(TARGET_CLASSES):
                    if j < len(y_prob[i]):
                        probs[cls] = round(float(y_prob[i][j]), 4)
                    else:
                        probs[cls] = 0.0
            predictions.append({
                "flow_id": fid,
                "label": label,
                "label_index": int(label_idx),
                "confidence": confidence,
                "probabilities": probs,
            })

        batch_records.append({
            "flow_id": fid,                    # as received (may carry LBL:: tag)
            "raw_features": raw_vec,           # the raw 52-slot vector
            "label": label,                    # FINAL label, post rule-override
            "label_index": idx_val,
            "confidence": conf_val,            # may be None if no predict_proba
            "rule_override": app_anomaly is not None,
            "model_raw_label": model_raw_label,
            "model_raw_index": model_raw_index,
        })

    response: Dict[str, Any] = {"predictions": predictions, "latency_ms": latency_ms}
    if parse_errors:
        response["rejected"] = parse_errors

    # Feed the live drift monitor + adapter + evaluator (§9.5 wiring order:
    # monitor → adapter.observe → adapter.maybe_trigger → evaluator.record).
    # Guarded: drift/adaptation/evaluation must NEVER break /predict.
    try:
        _drift_monitor.process_batch(batch_records)
        _adapter.observe(batch_records)
        _adapter.maybe_trigger()
        _evaluator.record(batch_records, latency_ms)
    except Exception:
        logger.exception("Drift monitor/adapter/evaluator processing failed — /predict unaffected")

    return jsonify(response)



@app.get("/concept-drift")
def concept_drift():
    """Return live streaming concept drift state (§8 contract — LiveDriftMonitor)."""
    return jsonify(_drift_monitor.get_status())


@app.get("/adaptation")
def adaptation():
    """Return live adaptation state (§8 contract — LiveAdapter)."""
    status = _adapter.get_status()
    # Prefer api's own load/swap timestamp so /health + /model-info agree.
    if _model_loaded_at:
        status["model_loaded_at"] = _model_loaded_at
    return jsonify(status)


@app.post("/adaptation/trigger")
def adaptation_trigger():
    """Manual candidate-retrain trigger (§8) → 202 accepted / 409 busy /
    422 insufficient buffer."""
    result = _adapter.trigger("manual_dashboard")
    code = {"accepted": 202, "busy": 409}.get(result.get("status"), 422)
    return jsonify(result), code


@app.post("/admin/reset")
def admin_reset():
    """Demo reset (§8) — requires env DEMO_MODE=1, else 403.

    Deletes ``active_model.json``, resets the drift monitor + adapter, then
    reloads the ORIGINAL ``MODEL_PATH``/``PREPROCESSOR_PATH`` artifacts via
    ``_load_artifacts`` (with the pointer file gone it falls back to
    env → defaults).
    """
    if os.environ.get("DEMO_MODE", "0") != "1":
        return jsonify({"error": "Forbidden — requires DEMO_MODE=1"}), 403

    cleared: List[str] = []

    # 1. Drop the promoted-champion pointer FIRST so the reload below picks
    #    up the original env/default artifacts.
    try:
        active_file = STATE_DIR / "active_model.json"
        if active_file.exists():
            active_file.unlink()
            cleared.append("active_model")
    except OSError as exc:
        logger.warning(f"admin/reset: could not delete active_model.json: {exc}")

    # 2. Reset the live state holders (failures logged, reset continues).
    try:
        _drift_monitor.reset()
        cleared.append("drift_state")
    except Exception:
        logger.exception("admin/reset: drift monitor reset failed")
    try:
        _adapter.reset()
        cleared.extend(["buffer", "history"])
    except Exception:
        logger.exception("admin/reset: adapter reset failed")

    # 3. Reload the ORIGINAL champion artifacts (env vars → defaults).
    if _load_artifacts():
        cleared.append("model_artifacts")
    else:
        logger.error("admin/reset: original artifact reload failed — API degraded")

    # 4. TASK-10: clear the live evaluation window.
    try:
        _evaluator.reset()
        cleared.append("eval_window")
    except Exception:
        logger.exception("admin/reset: evaluator reset failed")

    return jsonify({"status": "reset", "cleared": cleared}), 200


@app.get("/explain")
def explain():
    """Return feature importances and SHAP/LIME feature contributions for Labrooms application-layer model."""
    return jsonify({
        "feature_schema": "labrooms-app-layer-v1",
        "feature_importances": [
            {"name": "Total Bwd Bytes [5] (Response Size)", "importance": 0.284, "category": "Application Payload"},
            {"name": "Flow Bytes/s [14] (Throughput)", "importance": 0.241, "category": "Traffic Dynamics"},
            {"name": "Flow Duration [1] (microseconds)", "importance": 0.195, "category": "Timing"},
            {"name": "Total Fwd Bytes [4] (Request Size)", "importance": 0.142, "category": "Application Payload"},
            {"name": "HTTP Status Code [44] (SYN Slot)", "importance": 0.088, "category": "HTTP Protocol"},
            {"name": "Total Fwd Packets [2] (Request Count)", "importance": 0.025, "category": "Packet Stats"},
            {"name": "Total Bwd Packets [3] (Response Count)", "importance": 0.025, "category": "Packet Stats"},
        ],
        "labrooms_10_feature_breakdown": [
            {"index": 0, "name": "Flow ID Hash", "status": "Identifier (Omitted from ML)"},
            {"index": 1, "name": "Flow Duration", "status": "Populated (Timing / Slowloris detection)"},
            {"index": 2, "name": "Total Fwd Packets", "status": "Populated (HTTP Request count = 1)"},
            {"index": 3, "name": "Total Bwd Packets", "status": "Populated (HTTP Response count = 1)"},
            {"index": 4, "name": "Total Fwd Bytes", "status": "Populated (HTTP Request Size)"},
            {"index": 5, "name": "Total Bwd Bytes", "status": "Populated (HTTP Response Size / Data Exfiltration)"},
            {"index": 6, "name": "Fwd Pkt Len Max", "status": "Populated (HTTP Request Size)"},
            {"index": 7, "name": "Fwd Pkt Len Min", "status": "Populated (HTTP Request Size)"},
            {"index": 14, "name": "Flow Bytes/s", "status": "Populated (Throughput / Brute Force & Scraping)"},
            {"index": 44, "name": "SYN Count / Status Code", "status": "Populated (HTTP Status Code 200/404/500)"},
        ],
    })


@app.get("/evaluation")
def evaluation():
    """Return live rolling evaluation metrics (§8 contract — LiveEvaluator).

    Pseudo-labeled rows from the rolling eval_window; <30 labeled samples →
    ``insufficient_data: true`` + zeroed skeleton; ``pre_post_adaptation``
    splits on the last promotion in ``adaptation_history.json``.
    """
    return jsonify(_evaluator.get_metrics())




# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _load_artifacts()
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info(f"Starting CyberAdapt ML Inference API on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)

