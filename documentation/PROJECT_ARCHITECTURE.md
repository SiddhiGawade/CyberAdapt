# Project Architecture and Tech Stack

This document explains the software layers and the path of a request through CyberAdapt. For how a flow vector is captured or generated, see [Sensor and End-to-End Data Flow](SENSOR_AND_DATA_FLOW.md). For the model and drift logic, see [ML, Drift Detection, and Adaptation](ML_DRIFT_ADAPTATION.md).

## 1. System layout

```text
┌─────────────────────────────────┐
│ Edge input                      │
│ sensor/sensor.py (Scapy)        │
│ mock_sensor.py / generators     │
└────────────────┬────────────────┘
                 │ POST /api/telemetry/ingest
                 │ X-Sensor-Key, JSON batch
                 ▼
┌─────────────────────────────────┐       ┌──────────────────────┐
│ Node.js + Express :5000         │──────►│ MongoDB :27017       │
│ sensor auth, validation, routes │       │ Mongoose documents   │
└────────────────┬────────────────┘       └──────────┬───────────┘
                 │ async POST /predict                │ labels back-filled
                 ▼                                    │
┌─────────────────────────────────┐                    │
│ Python + Flask :5001            │────────────────────┘
│ model inference, drift monitor, │
│ adapter, live evaluator         │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│ React dashboard + Vite :3000    │── /api proxy ──► Node :5000
└─────────────────────────────────┘
```

The frontend does not normally call Flask directly. It calls `/api/...`; during local development, Vite proxies that prefix to the Node API. Node handles portal authentication and proxies dashboard ML requests to Flask.

## 2. Technology stack

| Layer | Technology in the repository | What it does |
|---|---|---|
| Dashboard | React 18, JavaScript/JSX, Vite 6 | Renders the portal and provides the local development server/build. |
| Dashboard routing | React Router 6 | Routes between Overview, Live Traffic, Sensor Setup, Concept Drift, Adaptation, Explainability, and Evaluation pages. |
| UI styling and icons | Tailwind CSS 3, PostCSS, Autoprefixer, lucide-react | Styling and interface icons. |
| Charts | Recharts | Dashboard charts and traffic visualizations. |
| Web/API server | Node.js (18+), Express 4 | Authentication, sensor ingestion, telemetry queries, and proxying to Flask. |
| Database layer | MongoDB, Mongoose 8 | Stores companies, sensor API-key metadata, and one telemetry document per flow. |
| Portal authentication | bcryptjs, JSON Web Token (`jsonwebtoken`) | Hashes portal passwords and issues/validates JWTs for dashboard routes. |
| Sensor authentication | Node `crypto` SHA-256 + random keys | Generates sensor API keys, stores their hashes, and authenticates `X-Sensor-Key`. |
| ML API | Python 3.10+, Flask 3, flask-cors | Serves health, model metadata, prediction, drift, adaptation, evaluation, and explain endpoints. |
| Data/model code | pandas, NumPy, scikit-learn | Tabular data, numeric transforms, baseline classifiers, and metrics. |
| Tree models | LightGBM and XGBoost | Candidate/benchmark tree models; live retraining currently uses LightGBM. |
| Stream/drift code | River | ADWIN and Page-Hinkley online detectors. |
| Statistical tests | SciPy | Two-sample Kolmogorov–Smirnov test used by the live monitor. |
| Serialization | Joblib | Loads/saves the champion, preprocessor, and promoted model artifacts. |
| Sensor | Python, Scapy, requests | Captures IP packets, builds flow records, and posts JSON batches. |
| Training and visualization | Jupyter, ipykernel, matplotlib, seaborn, pyarrow | Notebook experiments, plots, and data I/O. |
| Container support | Dockerfile under `sensor/` | Optional container for the Scapy sensor; it is not a full-stack Docker deployment. |

Dependency manifests: [`client/package.json`](../client/package.json), [`server/package.json`](../server/package.json), and [`ml/requirements.txt`](../ml/requirements.txt). MongoDB must be running separately for the Node service.

## 3. Services and responsibilities

### Dashboard — `client/`

- Vite serves the development UI on port 3000.
- `client/src/api.js` attaches the saved portal JWT to requests and calls the `/api` prefix.
- `client/vite.config.js` proxies `/api` to `http://localhost:5000` during development.
- The seven pages are described in the root README. Explainability currently displays static demonstration data; it is not a live SHAP/LIME integration.

### Node API — `server/`

- `server/server.js` loads environment configuration, enables JSON/CORS middleware, connects to MongoDB, and mounts `/api/auth` and `/api/telemetry`.
- `POST /api/telemetry/ingest` is sensor-authenticated. It validates the envelope and 52-slot arrays, inserts valid flows, updates the key's last-ingest time, and responds with HTTP 202.
- After that response, `classifyAndAnnotate()` sends the inserted batch to Flask `/predict`. The Node process later back-fills `threatLabel` and `threatConfidence` onto the same MongoDB documents.
- Portal endpoints use JWT authentication. Dashboard endpoints in `server/routes/telemetry.js` retrieve recent flows or proxy requests to Flask.

### Flask ML API — `ml/api.py`

- Loads the champion classifier and fitted preprocessor with Joblib.
- `/predict` maps the incoming 52-slot vector to the eight model inputs, predicts a class and probability, then applies the Labrooms app-layer rules where applicable.
- The same prediction batch is then sent to the live drift monitor, live adapter, and live evaluator. Those operations are guarded so an exception there does not fail the prediction response.
- A candidate retrain runs in a daemon thread; accepted candidates are saved and hot-swapped into the Flask process.

### MongoDB and file state

| State | Location | Purpose |
|---|---|---|
| Company account and domain state | MongoDB `Company` model | Login, domain verification, and company identity. |
| Sensor API-key hashes | MongoDB `ApiKey` model | Active/revoked sensor credentials; raw key is not stored by this model. |
| Flow records | MongoDB `TelemetryLog` model | Raw feature vector, company/sensor IDs, timestamp, and asynchronous threat annotation. |
| Initial champion/preprocessor | `ml/artifacts/models/*.joblib` | Offline-trained artifacts used at API boot when configured. |
| Promoted champion/preprocessor | `ml/artifacts/models/adaptive_*_vN.joblib` | Versioned candidate artifacts after a successful gate. |
| Live drift and adaptation state | `ml/artifacts/state/` | JSON/JSONL records for detector state, active model pointer, adaptation history, adapter status, and rolling evaluation data. |

The raw CICIDS2017 CSV is an input to the notebooks, not part of the visible artifact set; the root README documents where to place it when reproducing training. Pre-trained Joblib artifacts are present under `ml/artifacts/models/`.

## 4. Authentication and trust boundaries

1. **Portal:** registration stores a bcryptjs password hash. Login issues a JWT signed with `JWT_SECRET`; authenticated routes require `Authorization: Bearer ...`.
2. **Domain check:** the portal can verify a DNS TXT value before allowing the company to generate a sensor key.
3. **Sensor:** a generated `ca_live_...` value is returned once. The database stores its SHA-256 hash and a short display prefix. The sensor sends the raw key in `X-Sensor-Key`; middleware hashes it and looks up an active key.
4. **ML proxy:** the Node API forwards internal JSON to Flask. The current Flask endpoints are not independently authenticated in this repository, so deployment should keep that service on a trusted network and add appropriate production controls.

Do not put live keys, passwords, JWT secrets, or database credentials in this documentation or commit them in source. Use environment variables and generated credentials. The checked-in demo seed account and local HTTP setup are for development only.

## 5. Key HTTP endpoints

### Node service — port 5000

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | None | Node liveness. |
| `POST` | `/api/auth/register` | None | Create portal company and DNS verification token. |
| `POST` | `/api/auth/login` | None | Obtain portal JWT. |
| `POST` | `/api/auth/verify-dns` | JWT | Verify the company's TXT record. |
| `POST` | `/api/auth/generate-key` | JWT | Generate a sensor key after verification. |
| `GET` | `/api/auth/keys`, `/api/auth/me` | JWT | List key metadata or current company. |
| `POST` | `/api/telemetry/ingest` | `X-Sensor-Key` | Validate and store a flow batch; returns 202 before annotation. |
| `GET` | `/api/telemetry/recent-flows` | JWT | Return the latest 100 flows for the dashboard. |
| `GET` | `/api/telemetry/{ml-health,model-info,concept-drift,adaptation,explain,evaluation}` | JWT | Proxy read requests to Flask. |
| `POST` | `/api/telemetry/adaptation/trigger`, `/api/telemetry/admin/reset` | JWT | Proxy actions to Flask and pass through its status. |

### Flask service — port 5001

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health`, `/model-info` | Service/model readiness and active model metadata. |
| `POST` | `/predict` | Classify a batch of 52-slot flow vectors and feed the live processing path. |
| `GET` | `/concept-drift`, `/adaptation`, `/evaluation` | Return live monitoring, adaptation, and evaluation state. |
| `POST` | `/adaptation/trigger` | Request a candidate retrain; returns accepted, busy, or insufficient-buffer status. |
| `POST` | `/admin/reset` | Development/demo reset; enabled only with `DEMO_MODE=1`. |
| `GET` | `/explain` | Static placeholder response, not live explanation. |

The dashboard pages poll their data through Node; the current member-3 pages use a three-second polling cadence according to the project notes.

## 6. Local development sequence

The root README is the main command reference. At a high level, start services in this order:

1. MongoDB on 27017.
2. Node API from `server/` (`npm install`, then `npm run dev`). Configure `MONGO_URI`, `JWT_SECRET`, and `ML_API_URL` in a local, uncommitted `.env`.
3. From the repository root, create/activate a Python virtual environment and install `ml/requirements.txt`. Point `MODEL_PATH` and `PREPROCESSOR_PATH` at the artifacts under `ml/artifacts/models/`; run `python -m ml.api` on port 5001.
4. From `client/`, install npm dependencies and run `npm run dev` on port 3000.
5. Generate or capture telemetry with a sensor key supplied through an environment variable or command option. Use a mock/generator for local testing; use `sensor.py` only where authorized packet capture and the feature contract have been verified.

The exact Windows commands and development seed flow are in [`README.md`](../README.md). The ML README's old 6000-port quickstart should not override `ml/api.py`'s current 5001 default or the root README.

## 7. Verification commands and project checks

- The client package provides `npm run build` to verify the Vite production build.
- `ml/scripts/check_drift_api.py`, `check_adaptation_api.py`, and `check_evaluation_api.py` are live API audit/demo scripts. They need the corresponding services running and are not isolated unit tests.
- `pytest` is listed in the Python requirements, but no conventional `tests/` directory or `test_*.py` suite was found during this review. The Member 3 tracker/runbook records end-to-end rehearsal and contract checks.

## 8. Current scope and deployment limits

This is a research/demo system, not a hardened production IDS deployment. The repository's own README lists production sensor deployment, TLS, multi-tenant hardening, and live SHAP/LIME as unfinished. The default development services use local HTTP, and the demo dashboard credentials/seed script should not be reused as production credentials. Confirm the packet-to-feature schema before connecting a real sensor to the current Labrooms-trained model.
