# CyberAdapt — Adaptive Cyber Threat Intelligence under Concept Drift

> Advanced Machine Learning (AML) Mini-Project — VIT, 3rd Year B.Tech (7th Semester)

CyberAdapt is a SaaS-style threat-intelligence platform. Edge sensors capture
network flows and stream 52-feature vectors to a cloud API; each flow is stored
in MongoDB and asynchronously classified by an ML microservice trained on
CICIDS2017. A React dashboard shows live traffic, threat labels, concept-drift
monitoring, model adaptation, explainability and evaluation.

**Core research problem** (see `documentation/Adaptive_Cyber_Threat_Intelligence_Concept.pdf`):
keep ML detection reliable as network behaviour changes over time — concept-drift
detection, model monitoring, adaptive retraining, and interpretable predictions.

---

## Architecture

```
┌──────────────────┐   X-Sensor-Key    ┌───────────────────────────┐
│  sensor/ (Python)│ ────────────────▶ │  server/ (Node + Express) │
│  Scapy / Mock /  │  POST /ingest     │  :5000                    │
│  Attack simulator│                   │  • JWT auth (portal)      │
└──────────────────┘                   │  • API-key auth (sensors) │
                                       │  • MongoDB (Mongoose)     │
                                       └───────────┬───────────────┘
                                                   │ fire-and-forget
                                                   ▼
                                       ┌───────────────────────────┐
┌──────────────────┐   /api proxy      │  ml/api.py (Flask)        │
│  client/         │ ◀──────────────── │  :5001                    │
│  React + Vite    │   JWT-protected   │  champion_model.joblib    │
│  Tailwind :3000  │   routes          │  + preprocessor.joblib    │
└──────────────────┘                   │  → back-fills threatLabel │
                                       └───────────────────────────┘
```

Flow: Sensor → `POST /api/telemetry/ingest` (202 Accepted, stored instantly) →
batch forwarded to Flask `/predict` → predicted `threatLabel` + `threatConfidence`
written back onto the stored `TelemetryLog` documents → dashboard polls
`GET /api/telemetry/recent-flows`.

---

## Repository Layout

| Directory | Stack | Purpose |
|---|---|---|
| `client/` | React 18, Vite, Tailwind, Recharts | Web dashboard (port 3000) |
| `server/` | Node.js, Express, Mongoose | Ingestion + auth API (port 5000) |
| `ml/` | Python, Flask, scikit-learn/LightGBM/XGBoost, River | Training notebooks + inference API (port 5001) |
| `sensor/` | Python, Scapy | Real edge sniffer, mock sensor, attack simulator |
| `documentation/` | PDF / DOCX / PNG | Concept note, topic options, assignment template, syllabus |

---

## What Is Implemented So Far

### ✅ Working end-to-end

- **Company onboarding & auth** — register, login (bcrypt + JWT, 24 h expiry),
  `GET /api/auth/me`.
- **Domain verification** — real DNS TXT-record check (`cyberadapt-verify=…`)
  via `POST /api/auth/verify-dns`; sensor keys are locked until the domain is verified.
- **Sensor API keys** — `ca_live_…` keys, SHA-256-hashed at rest, listable via
  `GET /api/auth/keys`; raw key shown once at generation.
- **Telemetry ingestion** — `POST /api/telemetry/ingest` validates the
  sensor_id/timestamp/flows envelope, enforces the exact 52-feature schema,
  clamps negative flow duration, bulk-inserts into MongoDB, updates
  `lastIngestAt`, and returns `202` immediately.
- **Async ML annotation** — after ingest, flows are forwarded to the Flask API
  (fire-and-forget, 5 s timeout) and `threatLabel` / `threatConfidence` are
  back-filled onto the stored documents.
- **Edge sensor (`sensor/sensor.py`)** — Scapy-based live packet capture,
  bidirectional 5-tuple flow aggregation, computes all 52 CICIDS-style features,
  micro-batches (default 100 flows / 2 s) with retry + exponential backoff.
  Dockerfile provided.
- **Mock sensor (`sensor/mock_sensor.py`)** — generates plausible random flows
  for local testing without root/libpcap.
- **Attack simulator (`sensor/simulate_attacks.py`)** — sends 4 attack flows
  + 1 normal flow matching the Labrooms app-layer contract (Slowloris/DoS,
  data exfiltration, brute force, SQLi/web attack) and prints live predictions.
- **ML training pipeline (3 Jupyter notebooks, executed copies included)**
  1. `01_dataset_audit.ipynb` — data-quality audit, negative-duration fix.
  2. `02_model_training.ipynb` — trains & compares **Logistic Regression
     (baseline), Linear SVM, Random Forest, XGBoost, LightGBM, and a weighted
     soft-voting ensemble**; exports `champion_model.joblib` +
     `preprocessor.joblib`. Comparison report in
     `ml/artifacts/reports/model_comparison.csv`.
  3. `03_streaming_drift_adaptation.ipynb` — streaming simulation with ADWIN
     drift detection and champion/candidate adaptive retraining
     (`ml/src/models/adaptive_engine.py`, `ml/src/drift/detectors.py`);
     figures in `ml/artifacts/figures/`.
- **Flask inference API (`ml/api.py`)** — `GET /health`, `GET /model-info`,
  `POST /predict` (batch, 52-feature vectors). Includes rule-based
  application-layer overrides on top of the model (Slowloris >30 s / HTTP 504 →
  DoS, >10 MB response → exfiltration/Web Attack, HTTP 401/403 bursts → Brute
  Force, HTTP 500/large payload → Web Attack).
- **Live concept-drift monitoring** — every `/predict` batch feeds a
  River-based monitor on the ingest stream (ADWIN / Page-Hinkley / DDM on
  pseudo-labels, PSI + KS on feature slots); `GET /concept-drift` serves live
  detector state, per-slot PSI and drift-event history.
- **Drift-triggered adaptation** — a latched drift event auto-triggers a gated
  champion/candidate retrain and hot-swaps the promoted model
  (`adaptive_champion_vN.joblib` + `active_model.json`, restored on boot).
  `POST /adaptation/trigger` forces a retrain (202/409/422); `POST
  /admin/reset` (requires `DEMO_MODE=1`) restores v1 and clears state.
- **Rolling pseudo-labeled evaluation** — `GET /evaluation` computes live
  metrics over a rolling labeled window: accuracy, per-class metrics,
  confusion matrix, and a pre/post-adaptation comparison at the last promotion.
- **Feature contract** — `labrooms-app-layer-v1`: only 8 populated slots of the
  52-feature vector are used (slots 1,2,3,4,5,6,7,14 → duration, packet counts,
  byte counts, bytes/s). Documented in `ml/artifacts/reports/labrooms_feature_contract.json`.
- **Dashboard (7 pages)** — dark cyber theme, JWT-protected routes:
  | Page | Route | Shows |
  |---|---|---|
  | Overview | `/` | KPIs (domain status, sensors, flows, last ingest) + live table + attack alert banner |
  | Live Traffic | `/live-traffic` | Streaming flow table with predicted threat labels (3 s polling) |
  | Sensor Setup | `/sensor-setup` | 3-step wizard: DNS verify → generate key → Docker/run instructions |
  | Concept Drift | `/concept-drift` | Live detector status: drift state, per-detector flags, per-slot PSI, event history (3 s polling) |
  | Adaptation | `/adaptation` | Live champion version, buffer + gate results, retrain history, FORCE RETRAIN button |
  | Explainability | `/explain` | Feature-importance breakdown (static placeholder) |
  | Evaluation | `/evaluation` | Live metrics + confusion matrix + pre/post-adaptation split |

### ⚠️ Implemented as a placeholder (wired but static)

Only `/explain` and the Explainability page still return **hardcoded
demonstration data** — real SHAP/LIME explainability is not yet active. The
other three endpoints now serve live computation from the ingest stream.

### ⬜ Not yet implemented

- Live SHAP/LIME explanations per prediction.
- Production sensor deployment (service/daemon, TLS, multi-tenant hardening).

---

## Prerequisites

- **Node.js ≥ 18** (server uses global `fetch` and `node --watch`)
- **Python ≥ 3.10**
- **MongoDB** running locally (`mongodb://localhost:27017`) or an Atlas URI
- (Optional) Docker — only for the containerized real sensor
- (Optional, real sensor on Windows) Npcap + Administrator shell

---

## How to Run (full stack, ~5 terminals)

First time? Follow every step below in order. After that, each dev session is:

1. **MongoDB** — start `mongod` (step 0), leave that terminal open
2. **Backend** — `cd server && npm run dev` → API on :5000
3. **ML API** — `.venv\Scripts\activate`, set the two model-path vars, `python -m ml.api` → :5001
4. **Frontend** — `cd client && npm run dev` → http://localhost:3000
5. **Telemetry** — `python sensor/simulate_attacks.py --key ca_live_…` for a demo, or `mock_sensor.py` for continuous flows

### 0. Start MongoDB

The backend expects `mongodb://localhost:27017/cyberadapt`. `mongod` is
installed (`C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe`) but **not**
registered as a Windows service, so it must be started manually — keep this
terminal open for the whole session.

**Windows (PowerShell):**

```powershell
# First time only — use a data dir inside your profile.
# The default C:\Program Files\...\data fails with "Access is denied" without admin.
mkdir "$env:USERPROFILE\mongodb-data"

# Every session — mongod runs in the foreground here
& "C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe" `
    --dbpath "$env:USERPROFILE\mongodb-data" --bind_ip localhost --port 27017
```

**Linux/Mac:** `sudo systemctl start mongod` (or `mongod --dbpath <dir>`).

> **Optional — install MongoDB as a Windows service once** (admin PowerShell),
> so it auto-starts and you can skip this step:
> ```powershell
> & "C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe" --install `
>     --serviceName MongoDB --dbpath "$env:USERPROFILE\mongodb-data" `
>     --logpath "$env:USERPROFILE\mongodb-data\mongod.log"
> net start MongoDB
> ```
> …or set `MONGO_URI` in `server/.env` to a free MongoDB Atlas URI and skip
> local mongod entirely.

### 1. Backend API — `server/` (port 5000)

```bash
cd server
npm install
copy .env.example .env        # Windows  (Linux/Mac: cp .env.example .env)
```

Edit `.env`:

```env
PORT=5000
MONGO_URI=mongodb://localhost:27017/cyberadapt
JWT_SECRET=change_me_to_a_strong_random_secret
JWT_EXPIRES_IN=24h
ML_API_URL=http://localhost:5001
```

> `ML_API_URL` must match the Flask API's port — **5001** (step 2).

```bash
npm run dev        # node --watch, auto-restarts on edits
# → ⚡ CyberAdapt API listening on port 5000
```

### 2. ML inference API — `ml/api.py` (port 5001)

```bash
# from the repo root
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r ml/requirements.txt
```

The trained artifacts are committed under `ml/artifacts/models/`, but the API
looks in `ml/artifacts/` by default — either set env vars:

```powershell
# PowerShell
$env:MODEL_PATH="ml/artifacts/models/champion_model.joblib"
$env:PREPROCESSOR_PATH="ml/artifacts/models/preprocessor.joblib"
python -m ml.api
```

```bash
# cmd:        set MODEL_PATH=ml/artifacts/models/champion_model.joblib
# bash:       export MODEL_PATH=ml/artifacts/models/champion_model.joblib
# (same for PREPROCESSOR_PATH)
```

…or copy the two files up one level into `ml/artifacts/`.

```bash
python -m ml.api
# → Starting CyberAdapt ML Inference API on port 5001
```

Check it: `GET http://localhost:5001/health` → `{"status":"operational","model_ready":true}`.

### 3. Frontend — `client/` (port 3000)

```bash
cd client
npm install
npm run dev
# → http://localhost:3000   (Vite proxies /api → http://localhost:5000)
```

### 4. Seed a dev account + sensor key

```bash
cd server
node scripts/seed-dev.js
```

This creates an **auto-verified** test company and prints:

- **Login** — `admin@acme-test.local` / `Test@1234` at `http://localhost:3000`
- **Sensor API key** — `ca_live_…` (copy it; needed below)

### 5. Send telemetry — pick one

**Mock sensor (recommended, no root needed):**

```bash
pip install requests
python sensor/mock_sensor.py --key "ca_live_YOUR_KEY" --url http://localhost:5000/api/telemetry/ingest
```

**Attack demo (best for screenshots — produces visible threat labels):**

```bash
python sensor/simulate_attacks.py --key "ca_live_YOUR_KEY"
# sends 4 attacks + 1 normal flow, then prints the ML predictions
```

**Normal traffic generator (baseline for the drift demo):**

```bash
python sensor/normal_traffic.py --key "ca_live_YOUR_KEY" --interval 2 --batch-size 8 --duration 140
# streams plausible normal flows; ~500 flows warms the drift monitor to `active`
```

**Attack campaign (multi-phase labeled attacks — drives live drift + adaptation):**

```bash
python sensor/attack_campaign.py --key "ca_live_YOUR_KEY" --scenario mixed --rate 12 --batch-size 6
# 6-phase campaign (warmup/dos/bruteforce/sqli/exfil/cooldown), LBL-tagged flows
```

**Real packet capture (needs libpcap/Npcap + admin):**

```bash
pip install scapy requests
set SENSOR_KEY=ca_live_YOUR_KEY
set INGEST_URL=http://localhost:5000/api/telemetry/ingest
set INTERFACE=eth0            # your interface name
python sensor/sensor.py
```

…or via Docker: `docker build -t cyberadapt-sensor sensor/ && docker run --net=host -e SENSOR_KEY=… -e INGEST_URL=… cyberadapt-sensor`

### 6. View it

Open `http://localhost:3000` → log in with the seed credentials →
watch **Live Traffic** populate with flows and ML threat labels; check
**Overview**, **Concept Drift**, **Adaptation**, **Explainability**,
**Evaluation** in the sidebar. After running `simulate_attacks.py` you'll see
DoS / Brute Force / Web Attacks labels appear within a couple of seconds.

---

## Retraining the Models (optional)

Only needed to reproduce/regenerate artifacts — the trained `.joblib` files are
already committed.

```bash
pip install -r ml/requirements.txt
# place CICIDS2017 cleaned CSV at  ml/data/raw/cicids2017_cleaned.csv
#   (dataset: https://www.unb.ca/cic/datasets/ids-2017.html)
jupyter notebook ml/notebooks/
# run 01 → 02 → 03 in order; artifacts land in ml/artifacts/
```

---

## API Reference (summary)

**Node server — `http://localhost:5000`**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health` | — | Liveness |
| POST | `/api/auth/register` | — | Register company → returns DNS token |
| POST | `/api/auth/login` | — | Login → JWT |
| POST | `/api/auth/verify-dns` | JWT | Check TXT record, mark verified |
| POST | `/api/auth/generate-key` | JWT | Mint `ca_live_…` sensor key |
| GET | `/api/auth/keys` | JWT | List key prefixes/status |
| GET | `/api/auth/me` | JWT | Current company |
| POST | `/api/telemetry/ingest` | `X-Sensor-Key` | Store flow batch → 202 |
| GET | `/api/telemetry/recent-flows` | JWT | Last 100 flows for dashboard |
| GET | `/api/telemetry/{ml-health,model-info,concept-drift,adaptation,explain,evaluation}` | JWT | Proxies to Flask API |
| POST | `/api/telemetry/{adaptation/trigger,admin/reset}` | JWT | Proxies to Flask API (literal status passthrough) |

**Flask ML API — `http://localhost:5001`**

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + `model_ready` |
| GET | `/model-info` | Model type, feature schema, classes |
| POST | `/predict` | `{flows:[{flow_id, features[52]}]}` → labels + probabilities |
| GET | `/concept-drift` `/adaptation` `/evaluation` | Live drift / adaptation / evaluation data |
| GET | `/explain` | Static placeholder |
| POST | `/adaptation/trigger` | Force a gated retrain → 202/409/422 |
| POST | `/admin/reset` | Reset to v1 + clear state (requires `DEMO_MODE=1`) |

Target classes: `Normal Traffic, DoS, DDoS, Port Scanning, Brute Force, Web Attacks, Bots`.

---

## Ports

| Service | Port | Env override |
|---|---|---|
| Client (Vite) | 3000 | `client/vite.config.js` |
| Node API | 5000 | `PORT` in `server/.env` |
| Flask ML API | 5001 | `PORT` env var |
| MongoDB | 27017 | `MONGO_URI` in `server/.env` |

---

## Troubleshooting

- **`ML classification never appears`** → ML API not running, wrong
  `ML_API_URL`, or model files not found. Check
  `GET /api/telemetry/ml-health` while logged in; verify `MODEL_PATH` /
  `PREPROCESSOR_PATH` (artifacts live in `ml/artifacts/models/`).
- **`401/403 from mock_sensor`** → bad/expired key, or company not verified —
  re-run `node scripts/seed-dev.js` for a fresh auto-verified key.
- **`MongoDB connection failed` / `ECONNREFUSED 127.0.0.1:27017`** → `mongod`
  isn't running — start it (step 0) and keep that terminal open. If `mongod`
  exits with `Access is denied` on the journal/data directory, you're pointing
  at `C:\Program Files\…` — use a `--dbpath` in your user profile instead.
- **`node --watch` says "Waiting for file changes" after a crash** → it does
  not auto-retry; just re-run `npm run dev`.
- **CORS/`/api` errors in browser** → the client must run through Vite on
  :3000 (it proxies `/api` → :5000); don't open `index.html` directly.
- **`node --watch` missing** → upgrade to Node ≥ 18 (or use `npm start`).

---

## Documentation

| File | Contents |
|---|---|
| `documentation/Adaptive_Cyber_Threat_Intelligence_Concept.pdf` | Project concept: pipeline, model set, drift/adaptation plan |
| `documentation/Advanced_ML_Mini_Project_Topic_Options.docx` | Original topic shortlist & selection rationale |
| `documentation/Assignment 2&3.docx` | Paper-review assignment template |
| `ml/README.md` | Deep dive on the ML module (notebooks, feature schema, endpoints) |
