# CyberAdapt Project Guide

This is the entry point for understanding the repository: what it does, which technologies it uses, how data moves through it, and how drift detection leads to a candidate model update. The companion documents go into the code-level details.

## Read in this order

1. [Project architecture and tech stack](PROJECT_ARCHITECTURE.md) — services, libraries, APIs, authentication, and how to run the stack.
2. [Sensor and end-to-end data flow](SENSOR_AND_DATA_FLOW.md) — what `sensor/sensor.py` actually captures, how it builds flows, and how those records reach MongoDB and the ML API.
3. [ML, drift detection, and adaptation](ML_DRIFT_ADAPTATION.md) — CICIDS2017 training, the feature contract, the detector comparison, model adaptation, and evaluation.

## The project in one paragraph

CyberAdapt is a demonstrator for an adaptive intrusion-detection platform. Python sensors or traffic generators send 52-number network-flow records to a Node/Express ingestion API. The API authenticates the sensor, stores each flow in MongoDB, and asynchronously asks a Flask ML service to classify the batch. The ML service returns a threat label and confidence, monitors the incoming prediction/feature stream for changes, and can train and gate a new model. A React dashboard displays recent flows, drift signals, adaptation history, and live evaluation metrics.

## Architecture at a glance

```text
Scapy sensor / mock or Labrooms-shaped generators
                 │  JSON + X-Sensor-Key
                 ▼
       Express API (:5000) ───────► MongoDB (:27017)
                 │                         ▲
                 │ async POST /predict     │ labels/confidence back-filled
                 ▼                         │
       Flask ML service (:5001) ───────────┘
       inference + drift + adaptation + evaluation

 React/Vite dashboard (:3000) ── /api proxy ──► Express API
```

`/predict` is the stateful ML path: after predictions are formed, it feeds the live drift monitor, adaptation buffer, and evaluator. The sensor receives an HTTP 202 from ingestion before ML annotation finishes; ML failures do not turn an accepted ingestion into a sensor-side failure.

## Important distinction: captured traffic versus demo traffic

There are two different ways data enters the project:

- [`sensor/sensor.py`](../sensor/sensor.py) is a passive Scapy packet sniffer. It captures IP packets visible on a chosen network interface and aggregates their headers, sizes, flags, and timings into flow vectors.
- [`sensor/normal_traffic.py`](../sensor/normal_traffic.py), [`sensor/attack_campaign.py`](../sensor/attack_campaign.py), [`sensor/simulate_attacks.py`](../sensor/simulate_attacks.py), and [`sensor/mock_sensor.py`](../sensor/mock_sensor.py) generate flow vectors in Python. They are useful for local demos and repeatable tests; those vectors are not packet captures from the Labrooms website.

The repository does not include the Labrooms website itself or a website-specific collector. In particular, the app-layer demo vectors assign HTTP status codes to slot 44, while `sensor.py` assigns TCP SYN counts to slot 44. This means the real Scapy sensor output is not semantically interchangeable with the demo stream expected by the current Labrooms ML rules. Read the sensor guide before describing a demo as real website traffic or deploying the packet sensor against the current model.

## Project development, from idea to demo

1. **Research concept:** use an existing application as a controlled environment; observe normal traffic, introduce authorized test traffic, detect changes, adapt, and compare performance. The website is the traffic environment, not the dashboard or the IDS itself. See [`Adaptive_Cyber_Threat_Intelligence_Team_Plan.md`](Adaptive_Cyber_Threat_Intelligence_Team_Plan.md).
2. **Data audit and contract:** inspect CICIDS2017, address invalid flow durations, and define feature and class order in [`ml/src/features/feature_contract.py`](../ml/src/features/feature_contract.py).
3. **Baseline modeling:** train and compare classifiers in notebook 02; export the model and preprocessor as Joblib artifacts. Notebook 01 audits the dataset; notebook 03 experiments with streaming drift and retraining.
4. **Application stack:** add edge ingestion, Node/Express authentication and persistence, Flask inference, and the Vite/React dashboard.
5. **Live behavior:** wire the live monitor, adaptation buffer, and evaluator into `/predict`; expose their state through Flask and Node proxy endpoints.
6. **Demo and verification:** use the normal-traffic and phased-attack generators, inspect the dashboard, and use the API check scripts under `ml/scripts/`. The Member 3 tracker records the live drift/adaptation/evaluation work as completed; its runbook also records demo-specific behavior and caveats.

The Markdown implementation plan and task records are in the [Member 3 documentation directory](member3/). They explain the decisions and rehearsals; for actual runtime behavior, use the Python/JavaScript source alongside those notes.

## What the main terms mean here

- **Flow:** a group of packets summarized as numeric measurements, rather than a saved copy of the full packet payload.
- **Feature vector:** the 52-number record sent for each flow. The current Labrooms model selects eight values for ML prediction; other values support identifiers, rules, or monitoring.
- **Concept drift:** a change over time in the relationship between traffic features and threat labels. With no ground-truth label on ordinary production traffic, the live monitor uses observable proxies and feature-distribution shifts; those signals are evidence of change, not a direct measurement of accuracy loss.
- **Drift detection versus adaptation:** a detector raises a drift event; the adapter separately collects eligible labels, retrains a candidate, evaluates it against the current champion, and promotes only if gates pass.
- **Champion/candidate:** the champion is the model serving predictions. A candidate is a newly trained model that must pass validation before it replaces the champion.
- **Pseudo-label:** a label inferred from a simulator tag, a deterministic rule override, or a high-confidence Normal prediction. Live evaluation and retraining use these labels, so they are not equivalent to an independently labeled test set.

## Source-of-truth notes

- Root [`README.md`](../README.md) is the current full-stack run guide and project summary.
- [`ml/README.md`](../ml/README.md) contains useful ML background but has older setup values in places: it says port 6000, whereas the current API and root README use 5001. The API's built-in artifact paths also point at `ml/artifacts/`, while the model files are under `ml/artifacts/models/`; set `MODEL_PATH` and `PREPROCESSOR_PATH` as the root README describes.
- The implementation and recorded plan disagree on some details. For example, the runbook describes a warm-up gate before drift can latch, but the current `LiveDriftMonitor.process_batch()` does not explicitly block its drift decision while its status is `warming_up`. The ML guide lists the other implementation differences that affect interpretation.
- The repository also lists academic/concept PDF and DOCX files in the root README. The text reader available here could not extract those binary files, so this guide is grounded in the readable Markdown, notebooks, manifests, and executable source; export those documents to text if their full contents need to be incorporated.

## Glossary

| Term | Plain-language meaning |
|---|---|
| CICIDS2017 | The offline labeled network-flow dataset used to train and benchmark the initial model. |
| Labrooms feature contract | The deployment mapping from the project's 52-slot flow record to eight selected model inputs, plus app-layer rules and monitoring signals. |
| ADWIN | An online adaptive-window change detector used on the live batch attack-ratio signal. |
| PSI / KS | Statistical comparisons of recent feature distributions with a reference set. |
| `LBL::` | A flow-ID prefix used by the simulator to carry a class label into the live demo pipeline. |
| Ingestion | Authenticated receipt, validation, and storage of sensor flow records by the Node API. |
| Hot-swap | Replacing the serving champion in the running Flask process after a candidate is accepted. |
