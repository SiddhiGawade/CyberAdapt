# CyberAdapt — ML Module

Adaptive Cyber Threat Intelligence using CICIDS2017 + ADWIN concept-drift detection.

---

## Overview

The `ml/` directory contains everything needed to **train, evaluate, and serve** the machine-learning models that power CyberAdapt's real-time threat classification.

| Component | Description |
|---|---|
| `notebooks/` | Step-by-step Jupyter notebooks (audit → train → stream adaptation) |
| `src/` | Production Python modules (preprocessing, models, drift, evaluation) |
| `api.py` | Flask inference microservice consumed by the Node.js server |
| `artifacts/` | Output directory for trained model `.joblib` files (git-ignored) |
| `requirements.txt` | Python dependencies |

---

## Architecture

```
Sensor (Python) ──► Node.js server ──► MongoDB
                          │
                     (fire & forget)
                          │
                          ▼
                  Flask ML API (ml/api.py)
                  ┌──────────────────────┐
                  │  preprocessor.joblib │
                  │  champion_model.joblib│
                  └──────────────────────┘
                          │
                  back-fills threatLabel
                  onto TelemetryLog docs
```

The Node.js ingestion endpoint accepts raw 52-feature flow vectors from the edge sensor, stores them immediately (no added latency to the sensor), then asynchronously forwards each batch to the Python Flask API for classification. Predicted labels are written back to MongoDB.

---

## Quickstart

### 1 — Install Python dependencies

```bash
cd CyberAdapt
python -m venv .venv
source .venv/bin/activate
pip install -r ml/requirements.txt
```

### 2 — Obtain the CICIDS2017 dataset

Place the cleaned CSV (or Parquet) file at:

```
ml/data/raw/cicids2017_cleaned.csv
```

> The CICIDS2017 dataset is available at https://www.unb.ca/cic/datasets/ids-2017.html

### 3 — Run the training notebooks in order

```bash
jupyter notebook ml/notebooks/
```

| Notebook | Purpose |
|---|---|
| `01_dataset_audit.ipynb` | Data quality audit, feature analysis, negative-duration remediation |
| `02_model_training.ipynb` | Train LightGBM / XGBoost / Ensemble; export `champion_model.joblib` and `preprocessor.joblib` |
| `03_streaming_drift_adaptation.ipynb` | ADWIN drift simulation, adaptive retraining, champion promotion gating |

Notebooks write artifacts to `ml/artifacts/`.

### 4 — Start the ML inference API

```bash
# From the repo root
python -m ml.api
# Listening on http://localhost:6000
```

Environment variables:
| Variable | Default | Description |
|---|---|---|
| `PORT` | `6000` | Flask server port |
| `MODEL_PATH` | `ml/artifacts/champion_model.joblib` | Path to champion model |
| `PREPROCESSOR_PATH` | `ml/artifacts/preprocessor.joblib` | Path to preprocessor |

### 5 — Start the Node.js server

```bash
cd server
cp .env.example .env   # fill in MONGO_URI, JWT_SECRET
npm install
npm run dev
```

Make sure `ML_API_URL=http://localhost:6000` is set in `server/.env`.

---

## API Endpoints (Flask)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | none | Liveness + model-ready probe |
| `GET` | `/model-info` | none | Active model metadata |
| `POST` | `/predict` | none | Classify a batch of 52-feature flow vectors |

### `POST /predict` example

```json
{
  "flows": [
    {
      "flow_id": "abc123",
      "features": [0, 150000, 5, 3, 1400, 800, 512, 128, 0, 0, 0, 0, 0, 0,
                   9333.3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                   0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                   0, 0, 0, 0]
    }
  ]
}
```

Response:
```json
{
  "predictions": [
    {
      "flow_id": "abc123",
      "label": "Normal Traffic",
      "label_index": 0,
      "confidence": 0.97,
      "probabilities": {
        "Normal Traffic": 0.97,
        "DoS": 0.01,
        "DDoS": 0.005,
        "Port Scanning": 0.005,
        "Brute Force": 0.003,
        "Web Attacks": 0.002,
        "Bots": 0.005
      }
    }
  ],
  "latency_ms": 2.4
}
```

---

## Feature Schema

The model uses eight named CICIDS2017 inputs with two accepted 52-slot sensor
schemas. `labrooms-app-layer-v2` maps response-byte total at slot 5 to both
backward packet-length inputs as a transaction proxy. `packet-flow-v1` uses
actual backward packet-length max/min at slots 10 and 11. Both schemas map
duration, forward packets/bytes/lengths, and throughput into the same named
model inputs. HTTP-status rule overrides run only for the Labrooms schema.

| Sensor Slot | CICIDS2017 Feature |
|---|---|
| [1] | Flow Duration |
| [2] | Total Fwd Packets |
| [4] | Total Length of Fwd Packets |
| [5] | Bwd Packet Length Max and Min *(transaction response-byte proxy)* |
| [6] | Fwd Packet Length Max |
| [7] | Fwd Packet Length Min |
| [14] | Flow Bytes/s |

Slot [3] is the response count and is not used as a packet-length feature.
Slot [44] is the HTTP status code used by rules, not by the classifier.

See [`ml/src/features/feature_contract.py`](ml/src/features/feature_contract.py) for the full contract definition.

---

## Target Classes

| Index | Class |
|---|---|
| 0 | Normal Traffic |
| 1 | DoS |
| 2 | DDoS |
| 3 | Port Scanning |
| 4 | Brute Force |
| 5 | Web Attacks |
| 6 | Bots |

---

## Module Structure

```
ml/
├── api.py                         # Flask inference microservice
├── requirements.txt               # Python dependencies
├── notebooks/
│   ├── 01_dataset_audit.ipynb
│   ├── 02_model_training.ipynb
│   └── 03_streaming_drift_adaptation.ipynb
├── src/
│   ├── features/
│   │   ├── feature_contract.py    # Feature lists, class schema, JSON export
│   │   └── preprocessing.py      # CICIDSDataPreprocessor (zero-leakage scaling)
│   ├── models/
│   │   ├── adaptive_engine.py     # Champion/Candidate lifecycle & promotion gating
│   │   ├── ensemble.py            # Weighted soft-voting ensemble
│   │   └── weighting.py           # Class imbalance sample weighting
│   ├── drift/
│   │   └── detectors.py           # ADWIN drift detection wrappers
│   ├── evaluation/
│   │   ├── metrics.py             # Macro F1, balanced accuracy, per-class metrics
│   │   ├── plotting.py            # Confusion matrices, model comparison charts
│   │   └── streaming_plotting.py  # Streaming F1 trajectory & drift timeline plots
│   └── data/
│       ├── audit.py               # Dataset quality audit utilities
│       └── stream_loader.py       # Streaming window data loader
├── artifacts/                     # Generated model files (git-ignored)
│   └── .gitkeep
└── data/                          # Raw / processed datasets (git-ignored)
    ├── raw/
    ├── processed/
    └── streams/
```
