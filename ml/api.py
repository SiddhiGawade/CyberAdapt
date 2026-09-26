"""
CyberAdapt ML Inference API
============================
Lightweight Flask microservice that loads the trained champion model
and exposes REST endpoints for the Node.js server to call.

Endpoints:
  GET  /health          — liveness probe
  POST /predict         — classify a batch of 52-feature flow vectors
  GET  /model-info      — active model metadata

Environment Variables:
  MODEL_PATH        — path to joblib champion model (default: ml/artifacts/champion_model.joblib)
  PREPROCESSOR_PATH — path to joblib preprocessor (default: ml/artifacts/preprocessor.joblib)
  PORT              — API port (default: 6000)

Usage:
  cd /path/to/CyberAdapt
  python -m ml.api
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
}


# ── Model Loading ────────────────────────────────────────────────────────────

def _load_artifacts() -> bool:
    """Load champion model and preprocessor from disk. Returns True if successful."""
    global _champion_model, _preprocessor, _model_loaded_at, _model_path_used

    model_path = Path(os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH))
    preproc_path = Path(os.environ.get("PREPROCESSOR_PATH", DEFAULT_PREPROCESSOR_PATH))

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
        "target_classes": TARGET_CLASSES,
        "feature_schema": "labrooms-app-layer-v1",
        "active_features": LABROOMS_DEPLOYMENT_FEATURES,
        "num_active_features": len(LABROOMS_DEPLOYMENT_FEATURES),
    }
    if hasattr(_champion_model, "n_estimators"):
        info["n_estimators"] = _champion_model.n_estimators
    return jsonify(info)


@app.post("/predict")
def predict():
    """
    Classify one or more network flows.

    Request body:
      { "flows": [{ "flow_id": "abc", "features": [<52 floats>] }, ...] }

    Response:
      {
        "predictions": [
          { "flow_id": "abc", "label": "Normal Traffic",
            "label_index": 0, "confidence": 0.97,
            "probabilities": { "Normal Traffic": 0.97, ... } }
        ],
        "latency_ms": 3.2
      }
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
    for i, (fid, label_idx) in enumerate(zip(flow_ids, y_pred)):
        label = TARGET_CLASSES[int(label_idx)] if int(label_idx) < len(TARGET_CLASSES) else "Unknown"
        confidence = float(y_prob[i][int(label_idx)]) if y_prob is not None else None
        probs = (
            {cls: round(float(y_prob[i][j]), 4) for j, cls in enumerate(TARGET_CLASSES)}
            if y_prob is not None else None
        )
        predictions.append({
            "flow_id": fid,
            "label": label,
            "label_index": int(label_idx),
            "confidence": confidence,
            "probabilities": probs,
        })

    response: Dict[str, Any] = {"predictions": predictions, "latency_ms": latency_ms}
    if parse_errors:
        response["rejected"] = parse_errors
    return jsonify(response)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _load_artifacts()
    port = int(os.environ.get("PORT", 6000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info(f"Starting CyberAdapt ML Inference API on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
