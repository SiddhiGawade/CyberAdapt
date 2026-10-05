# End-to-End ML Pipeline: Dataset, Training, Drift Detection, and Retraining

This guide explains the implemented CyberAdapt workflow from the offline CICIDS2017 dataset through initial model training, streaming drift detection, live candidate retraining, evaluation, and model promotion. It separates the **labeled notebook experiment** from the **live API**, because they have different access to ground-truth labels.

## At a glance

```text
OFFLINE TRAINING
Cleaned CICIDS2017 CSV
  -> audit and repair data
  -> select the 8-feature Labrooms contract
  -> ordered train / validation / test split
  -> fit preprocessing and compare classifiers
  -> save champion model + fitted preprocessor

OFFLINE DRIFT EXPERIMENT (notebook 03)
Labeled CICIDS2017 replay windows
  -> predict and compare with known labels
  -> ADWIN monitors per-flow prediction errors
  -> train candidate when the error detector fires
  -> evaluate on post-trigger data and apply promotion gates

LIVE SERVICE
Sensor or synthetic generator
  -> Node API stores the 52-value flow and forwards it to Flask /predict
  -> model prediction + application-rule override
  -> live drift monitor + pseudo-label buffer + rolling evaluator
  -> eligible drift event starts candidate retraining
  -> evaluate candidate against current champion
  -> promote and hot-swap only if every gate passes; otherwise keep champion
```

The offline experiment can compare predictions with dataset labels. Ordinary live traffic does not arrive with verified labels, so live drift signals and live evaluation must be interpreted as proxies rather than proof of degraded or improved real-world accuracy.

## 1. Dataset and audit

The training notebooks use a cleaned **CICIDS2017** flow dataset. The expected target column is `Attack Type`; the cleaned file has **2,520,751 rows**, **52 numeric input columns**, and that one target column (53 columns total).

The notebooks first look for:

```text
ml/data/raw/cicids2017/cicids2017_cleaned.csv
```

They fall back to:

```text
ml/data/raw/cicids2017_cleaned.csv
```

The raw CSV is an input to the notebooks; the model artifacts and comparison report are separate files under `ml/artifacts/`.

[`01_dataset_audit.ipynb`](../ml/notebooks/01_dataset_audit.ipynb) checks dataset shape, labels, duplicates, missing/infinite values, feature statistics, and whether features are suitable for the intended sensor. Its saved run reports 161 duplicate rows, no missing values, and no positive or negative infinities. The training notebook also finds **107 negative `Flow Duration` values**. [`quantify_and_clean_negative_duration()`](../ml/src/features/feature_contract.py) clips those values to zero and preserves the rows instead of dropping them.

### Target classes and imbalance

The seven labels have a highly uneven distribution:

| Label | Rows | Approx. share |
|---|---:|---:|
| Normal Traffic | 2,095,057 | 83.11% |
| DoS | 193,745 | 7.69% |
| DDoS | 128,014 | 5.08% |
| Port Scanning | 90,694 | 3.60% |
| Brute Force | 9,150 | 0.36% |
| Web Attacks | 2,143 | 0.085% |
| Bots | 1,948 | 0.077% |

These class names and their order are fixed in [`feature_contract.py`](../ml/src/features/feature_contract.py). Because Normal Traffic dominates, the training code uses class/sample weighting in several models and reports macro-F1, balanced accuracy, and per-class results—not accuracy alone.

## 2. Feature contract: from 52 sensor slots to 8 model inputs

The live API accepts a **52-number vector**. The deployed model uses schema `labrooms-app-layer-v1` and selects only eight values. This is intended to avoid training on features that the Labrooms-shaped generators leave at zero.

| Zero-based input slot | CICIDS2017 model column | Meaning / caveat |
|---:|---|---|
| 1 | `Flow Duration` | Flow/request duration |
| 2 | `Total Fwd Packets` | Forward packet count |
| 3 | `Bwd Packet Length Max` | Proxy for backward packet count; not an exact equivalent |
| 4 | `Total Length of Fwd Packets` | Forward bytes / request size |
| 5 | `Bwd Packet Length Min` | Proxy for backward bytes; not an exact equivalent |
| 6 | `Fwd Packet Length Max` | Maximum forward packet length |
| 7 | `Fwd Packet Length Min` | Minimum forward packet length |
| 14 | `Flow Bytes/s` | Flow throughput |

Slot 0 is an identifier and is not learned. Slot 44 is omitted from the model because CICIDS2017 has no matching HTTP status feature; the live application rules and live PSI monitor nevertheless inspect slot 44.

**Important input-mode limitation:** the normal/attack demo generators create Labrooms-shaped application-flow vectors. The Scapy sensor produces packet-level features, and in its implementation slot 44 is a TCP SYN count—not an HTTP status code. It also does not parse HTTP status codes. The slot-3 and slot-5 feature mappings are proxies. Therefore, the real packet-capture sensor and the synthetic Labrooms input are not interchangeable without aligning their feature meanings. See [Sensor and End-to-End Data Flow](SENSOR_AND_DATA_FLOW.md).

## 3. Initial preprocessing, split, and model training

[`02_model_training.ipynb`](../ml/notebooks/02_model_training.ipynb) performs the initial benchmark:

1. Read the cleaned CSV and clip negative flow durations.
2. Select the eight `LABROOMS_DEPLOYMENT_FEATURES` and the `Attack Type` label.
3. Split rows in their existing order: **70% train, 15% validation, 15% test**. That is 1,764,525 training rows and 378,113 rows in each holdout. The dataset has no explicit timestamp column, so this is an `ordered_holdout_proxy`, not a verified time-based production split.
4. Fit [`CICIDSDataPreprocessor`](../ml/src/features/preprocessing.py) on the training partition only. It selects columns in contract order, replaces NaN/infinity with zero, fits a `StandardScaler`, and uses the fixed class order for label indices. The validation, test, and inference data use the already-fitted scaler.
5. Compare the following classifiers:

| Model | Implementation detail |
|---|---|
| Logistic Regression | Balanced class weighting; baseline |
| Linear SVM | Linear support-vector baseline |
| Random Forest | 50 trees, maximum depth 16, balanced-subsample weighting |
| XGBoost | 80 trees, depth 6, learning rate 0.1; balanced per-row sample weights |
| LightGBM | 80 trees, depth 6, learning rate 0.1; balanced class weights |
| Weighted soft-voting ensemble | A weighted average of LightGBM, XGBoost, and Random Forest probabilities (weights 0.45, 0.40, and 0.15); the highest weighted probability is the predicted class |

The notebook evaluates accuracy, balanced accuracy, macro/weighted F1, per-class precision/recall/F1, confusion matrices, and inference latency. The checked-in [`model_comparison.csv`](../ml/artifacts/reports/model_comparison.csv) records these ordered-holdout results:

| Model | Accuracy | Balanced accuracy | Macro-F1 |
|---|---:|---:|---:|
| Logistic Regression | 0.5204 | 0.3007 | 0.1049 |
| Linear SVM | 0.7526 | 0.4348 | 0.1257 |
| Random Forest | **0.8195** | **0.4734** | 0.1290 |
| XGBoost | 0.8041 | 0.4646 | 0.1281 |
| LightGBM | 0.8007 | 0.4626 | 0.1278 |
| Weighted soft-voting ensemble | 0.8054 | 0.4685 | **0.1519** |

Project artifacts use the weighted ensemble as the initial champion. Random Forest has the highest accuracy and balanced accuracy in this report; the ensemble has the highest macro-F1. **Do not interpret these numbers as strong seven-class validation:** the exported test partition has support only for Normal Traffic and DoS, and zero test examples for DDoS, Port Scanning, Brute Force, Web Attacks, and Bots. The CSV order and class imbalance constrain what this benchmark establishes.

The trained classifier and its fitted preprocessor are serialized with Joblib. The repository contains artifacts under `ml/artifacts/models/`, including `champion_model.joblib`, `preprocessor.joblib`, and versioned model files. The Flask API's built-in default paths point directly under `ml/artifacts/`; when using the files under `ml/artifacts/models/`, set `MODEL_PATH` and `PREPROCESSOR_PATH` as shown in the run instructions below.

## 4. Offline drift and retraining experiment

[`03_streaming_drift_adaptation.ipynb`](../ml/notebooks/03_streaming_drift_adaptation.ipynb) replays the **labeled** dataset in chronological windows of 50,000 rows (51 windows for this dataset). This is an experiment, not the same code path as live Flask monitoring.

For each replay window, the notebook:

1. Runs the current champion and computes metrics against the known `Attack Type` labels.
2. Sends each prediction error (`1` when prediction differs from the true label, otherwise `0`) to the River-based ADWIN detector (`delta=0.002`). The notebook's `process_window()` call supplies true and predicted labels; its optional feature signal is not supplied in that call.
3. When an ADWIN error-drift event fires, forms a candidate-training buffer from recent past windows plus the current window's pre-trigger prefix.
4. Uses data after the trigger for validation when enough of the current window remains; otherwise it tries the next replay window.
5. Fits a fresh candidate using [`AdaptiveModelManager`](../ml/src/models/adaptive_engine.py). In the current implementation this trainer creates a LightGBM classifier and fits a new preprocessor on the candidate-training data.
6. Compares candidate and champion on the validation data. It promotes the candidate only when all configured quality gates pass.

The intended validation is a post-trigger, unseen segment. At the final-window fallback, the notebook uses the full current window when there is no following window, so that terminal case should not be described as guaranteed disjoint if the training buffer includes a prefix of that same window.

This replay can monitor actual prediction errors because it has labels. That advantage does not carry over to unlabelled real-time traffic.

## 5. Live inference path

The live path is implemented in [`ml/api.py`](../ml/api.py), with Node ingestion and storage described in [Project Architecture](PROJECT_ARCHITECTURE.md):

1. A sensor or demo generator posts flow vectors to the Node API. Node validates and stores accepted flows in MongoDB, returns HTTP 202, then asynchronously forwards the batch to Flask `/predict`.
2. Flask validates the 52-value feature list and clamps a negative duration in slot 1 to zero.
3. The API maps the selected slots to the eight named CICIDS2017 columns, applies the saved preprocessor, and asks the current champion for a class and (when supported) probabilities.
4. It applies deterministic app-layer rules after model inference. Examples include duration over 30 seconds or HTTP 504 -> DoS; response bytes over 10 MB -> Web Attacks; HTTP 401/403 -> Brute Force; and selected HTTP error/large-request patterns -> Web Attacks. These are application-specific demo rules, not a general signature engine.
5. The final label, original model label, confidence, raw 52-slot vector, flow ID, and rule-override flag are passed to the live monitor, adapter, and evaluator. Node later writes the returned prediction onto the stored flow.

The serving sequence is therefore **model prediction -> optional rule override -> live monitoring/adaptation/evaluation**. An override can change the final class used for monitoring while the raw model class is retained for comparison.

## 6. Live drift detection: what each signal means

[`LiveDriftMonitor`](../ml/src/drift/live_monitor.py) receives prediction batches. Its main live signals are not verified model errors:

| Signal | What the implementation monitors | Role in live drift event? |
|---|---|---|
| ADWIN (`delta=0.002`) | One **attack ratio** per batch: fraction of final labels that are not `Normal Traffic` | Yes |
| Page-Hinkley | The same batch attack-ratio stream | Yes |
| PSI | Feature-distribution shift on raw slots 1, 4, 5, 14, and 44; 10 histogram bins; `log1p` for slots 1/4/5/14 and raw values for slot 44 | Yes, if at least two slots have PSI > 0.25 |
| Confidence ADWIN (`delta=0.01`) | Mean prediction confidence per batch | Warning/status only |
| DDM-style pseudo-error | On rule-overridden flows only, compares the final rule label with the model's raw label | Warning/status only |
| KS test | Two-sample comparison of raw slot 14 against reference/recent values; needs at least 10 samples per side and flags p < 0.05 | Diagnostic/status only |

PSI status is stable below 0.10, a minor shift from 0.10 through 0.25, and drifted above 0.25. PSI uses a reference set and a rolling recent window of up to 500 flows. The actual live event decision is:

```text
ADWIN(attack_ratio) OR Page-Hinkley(attack_ratio) OR at least 2 PSI slots above 0.25
```

A confidence warning, DDM signal, or KS result by itself does not trigger retraining. When an event fires, the monitor records it, latches drift to avoid repeated events, rotates its feature reference, and exposes one pending event for the adapter. It persists monitor state under `ml/artifacts/state/drift_state.json`.

The API reports `warming_up` until 500 samples have arrived since reset, but the current drift-decision code does **not** gate its event expression on that status. Treat `warming_up` as status text, not a guarantee that no event can fire.

### Live drift is not the same as measured accuracy loss

The live ADWIN input is the model's predicted attack fraction, not `y_true != y_pred`. A shift can reflect a change in traffic, a change in predictions, rule overrides, or model behavior; it does not establish that accuracy fell. The live DDM-style signal is also only a rule-override proxy and covers a small subset of flows. The offline labeled replay and the live service must therefore be described separately.

## 7. What happens after a live drift event

[`LiveAdapter`](../ml/src/adaptation/live_adapter.py) does not immediately replace the champion. It gathers eligible examples, trains a **candidate**, compares candidate and champion, and promotes only if all gates pass.

### 7.1 Build a labeled-example buffer

The adapter's ring buffer holds up to 5,000 examples. It resolves labels in this order:

1. `LBL::<CLASS_NAME>::...` in a demo flow ID (simulator label).
2. The final label from a deterministic app-layer rule override.
3. A `Normal Traffic` prediction with confidence at least 0.90 and no override.
4. Other records are excluded because they have no usable label.

Automatic retraining requires at least **200 labeled records**, at least **two classes**, and at least **30 non-Normal records**. Only one retrain can run at a time. Automatic drift triggers have a 60-second cooldown. The dashboard's manual trigger bypasses that cooldown but still requires a ready buffer and no active retrain.

If the adapter consumes a drift event before the buffer meets the minimums, it records a skipped event. The current monitor remains latched, so that same event is not automatically re-queued. Once the buffer is ready, the manual trigger can still request retraining; a demo reset instead starts a fresh monitoring cycle and clears the accumulated state.

### 7.2 Train and validate a candidate

When eligible, the adapter starts a background thread so candidate training does not block `/predict`:

- Snapshot the current pseudo-labeled buffer.
- Use the first 75% chronologically for training and newest 25% for validation. If the chronological split cannot put at least two classes in both sides and stratification is possible, use a stratified 75/25 fallback with random seed 42.
- Fit a fresh `StandardScaler` preprocessor on the candidate training subset only.
- Train a fresh LightGBM multiclass classifier with 60 estimators, max depth 6, learning rate 0.1, balanced class weights, and random seed 42.
- Evaluate the current champion and candidate on the same validation subset using accuracy-related metrics, macro-F1, balanced accuracy, and per-class metrics.

This live candidate is a LightGBM model even when the current champion is the offline weighted ensemble. It is a candidate, not an automatic replacement.

### 7.3 Four promotion gates

All four gates must pass:

| Gate | Required condition |
|---|---|
| Macro-F1 | Candidate is no worse than 0.01 below champion: `candidate - champion >= -0.01` |
| Balanced accuracy | Candidate is no worse than 0.01 below champion: `candidate - champion >= -0.01` |
| Emerged-class recall | Recall is at least 0.70 when that class has validation examples; the emerged class is the most frequent non-Normal class in the buffer |
| Normal guard | The code's `1 - precision(Normal Traffic)` value is at most 0.05 |

**Metric caveat:** the live field is called `normal_fpr`, but the implementation uses `1 - precision` for Normal Traffic. That is not the conventional false-positive-rate formula `FP / (FP + TN)`. Do not describe the current gate as a mathematically standard FPR check.

### 7.4 Promote or reject

- **All gates pass:** save versioned `adaptive_champion_vN.joblib` and `adaptive_preprocessor_vN.joblib` under `ml/artifacts/models/`, write the new paths/version to `ml/artifacts/state/active_model.json`, and hot-swap the serving model and preprocessor. On API restart, the active-model pointer is checked before the configured original paths.
- **Any gate fails:** record the report and rejection reason, keep the existing champion, and do not hot-swap the candidate.
- After a completed gate evaluation, the drift reference is reset for the next monitoring period. Candidate reports and adapter state are persisted under `ml/artifacts/state/`.

The relevant live endpoints are `GET /concept-drift`, `GET /adaptation`, `POST /adaptation/trigger`, and `GET /evaluation`. `POST /admin/reset` restores the configured original artifacts and clears live state only when `DEMO_MODE=1`.

## 8. Live evaluation and persisted state

[`LiveEvaluator`](../ml/src/evaluation/live_evaluator.py) keeps up to 500 pseudo-labeled examples and reports accuracy, macro/per-class precision/recall/F1, confusion matrix, and p95 latency. It returns `insufficient_data` until it has 30 labeled records and provides a pre/post-promotion comparison.

Because its labels come from simulator tags, rule overrides, or high-confidence Normal predictions, the live metrics are **pseudo-labeled metrics**, not independent production accuracy. The adapter and evaluator intentionally use similar label sources so their scores describe the same selected subset.

Important state/artifact paths:

| Path | Purpose |
|---|---|
| `ml/artifacts/models/champion_model.joblib` and `preprocessor.joblib` | Initial classifier and fitted preprocessing object |
| `ml/artifacts/models/adaptive_champion_vN.joblib` and `adaptive_preprocessor_vN.joblib` | Promoted live candidates |
| `ml/artifacts/state/drift_state.json` | Live detector counters, reference/recent values, latch, and event history |
| `ml/artifacts/state/adapter_state.json` | Adapter version and label-source/status counters; the in-memory sample buffer is not restored after restart |
| `ml/artifacts/state/adaptation_history.json` | Candidate metrics, gate results, and promotion/rejection history |
| `ml/artifacts/state/active_model.json` | Pointer to the most recently promoted serving model/preprocessor |
| `ml/artifacts/state/eval_window.jsonl` | Bounded rolling pseudo-labeled evaluation rows |

## 9. Main tools and libraries

| Tool/library | Use in this project |
|---|---|
| Python, Jupyter | Dataset audit, training, replay experiment, and ML service |
| pandas, NumPy | Tabular data, feature arrays, numerical cleanup, and drift statistics |
| scikit-learn | `StandardScaler`, baseline classifiers, data splits, class weights, and evaluation metrics |
| LightGBM, XGBoost | Offline benchmark models; LightGBM is also used for live candidate retraining |
| River | Streaming ADWIN and Page-Hinkley detectors |
| SciPy | Two-sample Kolmogorov-Smirnov test for feature-shift diagnostics |
| Joblib | Save/load classifier and fitted preprocessor artifacts |
| Flask | Python prediction, drift, adaptation, and evaluation endpoints |
| Node.js/Express and MongoDB | Sensor ingestion, flow storage, async call to Flask, and saved prediction annotations |
| Scapy / demo generators | Packet capture (Scapy) or synthetic Labrooms-shaped input |

SHAP/LIME explanations are not part of this training or drift pipeline; the repository's `/explain` endpoint currently returns demonstration data.

## 10. Reproduce the notebooks and run the API

From the repository root, install the Python requirements and provide the cleaned CSV at one of the paths in Section 1:

```powershell
pip install -r ml/requirements.txt
jupyter notebook ml/notebooks/
```

Run the notebooks in order:

1. `01_dataset_audit.ipynb`
2. `02_model_training.ipynb`
3. `03_streaming_drift_adaptation.ipynb` (optional labeled replay/drift experiment)

To run Flask with the artifacts under `ml/artifacts/models/` in PowerShell:

```powershell
$env:MODEL_PATH = "ml/artifacts/models/champion_model.joblib"
$env:PREPROCESSOR_PATH = "ml/artifacts/models/preprocessor.joblib"
python -m ml.api
```

The Flask API defaults to port 5001. For the full application, the Node API and MongoDB must also be running; the root [`README.md`](../README.md) documents the complete local setup.

## 11. Limitations to state clearly

1. The ordered train/validation/test split is only a sequence-preserving proxy; the cleaned CSV has no explicit timestamps.
2. The exported baseline test results contain no examples for five target classes, so they do not demonstrate performance across all seven classes.
3. The live monitor mostly detects shifts in predicted attack ratio and feature distributions, not verified concept drift or measured error-rate increase.
4. Live labels and metrics are partly synthetic or self-generated pseudo-labels; they are not a substitute for independently reviewed ground truth.
5. Labrooms slot mappings 3 and 5 are proxies, and slot 44 has different meanings for the synthetic generators and Scapy sensor. This can create training-serving skew.
6. A drift event starts an eligibility check, not guaranteed retraining or promotion. Candidates can be skipped for insufficient data or rejected by quality gates; the previous champion remains active unless promotion succeeds.
7. The system is a research/demo pipeline. Align and validate the feature contract, label quality, and operational controls before using it for production network detection.
