# ML, Concept Drift, and Model Adaptation

This document explains the model lifecycle from offline CICIDS2017 training through live prediction, drift monitoring, candidate retraining, and evaluation. The source code is linked throughout; for the sensor's 52-slot schema and the difference between captured and generated traffic, see [Sensor and End-to-End Data Flow](SENSOR_AND_DATA_FLOW.md).

## 1. Offline dataset and feature contract

The offline training notebooks expect a cleaned CICIDS2017 CSV with 2,520,751 rows and 53 columns (52 numeric features plus `Attack Type`). The notebook audit reports 107 negative Flow Duration values; `quantify_and_clean_negative_duration()` clips these to zero rather than discarding rows.

The training labels are fixed in [`feature_contract.py`](../ml/src/features/feature_contract.py):

1. Normal Traffic
2. DoS
3. DDoS
4. Port Scanning
5. Brute Force
6. Web Attacks
7. Bots

The class distribution is highly imbalanced: the executed training notebook reports about 83.1% Normal Traffic, 7.7% DoS, 5.1% DDoS, 3.6% Port Scanning, and under 0.4% each for Brute Force, Web Attacks, and Bots. The pipeline uses class/sample weighting and reports macro metrics so minority classes are not hidden by overall accuracy.

### Eight model inputs

The Labrooms deployment schema is named `labrooms-app-layer-v1`. The model does not use every slot of the incoming 52-value vector. The Flask API selects the following eight CICIDS2017 input columns:

| Incoming slot | Labrooms description | CICIDS2017 model column |
|---:|---|---|
| 1 | Flow duration in microseconds | `Flow Duration` |
| 2 | Forward packet count | `Total Fwd Packets` |
| 3 | Backward packet count | `Bwd Packet Length Max` (declared proxy) |
| 4 | Forward byte total / request size | `Total Length of Fwd Packets` |
| 5 | Backward byte total / response size | `Bwd Packet Length Min` (declared proxy) |
| 6 | Maximum forward packet length | `Fwd Packet Length Max` |
| 7 | Minimum forward packet length | `Fwd Packet Length Min` |
| 14 | Flow throughput | `Flow Bytes/s` |

Slot 0 is an identifier and is not used for learning. Slot 44 is excluded from the eight model columns because CICIDS2017 has no HTTP status equivalent; it is nevertheless read by the app-layer rule overrides and live feature monitor. The slot 3/5 mappings are explicitly approximate proxies, not exact feature equivalences. This matters when interpreting metrics and when connecting a real sensor.

### Preprocessing and validation

[`CICIDSDataPreprocessor`](../ml/src/features/preprocessing.py) selects columns in the contract order, replaces infinities/NaNs with zero, fits `StandardScaler` on training data, and applies the fitted transform later. Class labels use the fixed target-class order. The offline notebook uses an ordered 70% train / 15% validation / 15% test split called `ordered_holdout_proxy`, because the cleaned CSV has no explicit timestamps. It is sequence-preserving, but it is not a timestamp-verified production time split.

The notebooks are:

- [`01_dataset_audit.ipynb`](../ml/notebooks/01_dataset_audit.ipynb): dataset quality and feature feasibility.
- [`02_model_training.ipynb`](../ml/notebooks/02_model_training.ipynb): feature contract, preprocessing, classifier comparison, and artifact export.
- [`03_streaming_drift_adaptation.ipynb`](../ml/notebooks/03_streaming_drift_adaptation.ipynb): a chronological replay experiment using 50,000-record windows, ADWIN, and candidate promotion gates.

The raw dataset is an external training input. The cleaned CSV was not visible in the accessible file listing during this review (local data may be omitted or ignored); to reproduce training, provide the dataset at the path described by the root README/notebooks. The pre-trained model/preprocessor artifacts are under `ml/artifacts/models/`.

## 2. Initial classifier and benchmark

The project compares Logistic Regression, Linear SVM, Random Forest, XGBoost, LightGBM, and a weighted soft-voting ensemble. `model_comparison.csv` contains a 378,113-record ordered holdout result:

| Classifier | Accuracy | Balanced accuracy | Macro F1 |
|---|---:|---:|---:|
| Logistic Regression | 0.5204 | 0.3007 | 0.1049 |
| Linear SVM | 0.7526 | 0.4348 | 0.1257 |
| Random Forest | **0.8195** | **0.4734** | 0.1290 |
| XGBoost | 0.8041 | 0.4646 | 0.1281 |
| LightGBM | 0.8007 | 0.4626 | 0.1278 |
| Weighted Soft Voting Ensemble | 0.8054 | 0.4685 | **0.1519** |

In that exported report, the weighted ensemble has the highest macro F1; Random Forest has the highest accuracy and balanced accuracy. The project docs identify the ensemble as the initial champion. Do not read the table as strong evidence of performance on all seven attacks: the test portion shown in the CSV has support only for Normal Traffic and DoS, with zero test examples for DDoS, Port Scanning, Brute Force, Web Attacks, and Bots. The high overall accuracy is also influenced by class imbalance. The table is a reproducible baseline result, not proof of production accuracy.

The exported files include the initial champion, base models, ensemble, and preprocessing artifacts under [`ml/artifacts/models/`](../ml/artifacts/models/). The API uses Joblib to load the champion and its preprocessor.

## 3. Live classification and rule overrides

For each `/predict` batch, `ml/api.py` builds a DataFrame from the selected eight features, scales it with the saved preprocessor, and calls the active model's `predict()` (and `predict_proba()` when supported). It then checks app-layer rules in this order; the first matching rule supplies the final label:

| Rule | Condition | Override label |
|---|---|---|
| Slowloris / timeout | Duration over 30,000,000 microseconds **or** HTTP status 504 | DoS |
| Large response | Backward bytes over 10,000,000 | Web Attacks |
| Login/error burst | HTTP 401 or 403, **or** throughput over 100,000 bytes/s with status 401 or 404 | Brute Force |
| Server/application error | HTTP 500, **or** forward bytes over 10,000 with an error status (400+) | Web Attacks |

The final label is returned to Node, while the raw model label and the rule-override flag are also retained internally for drift, adaptation, and evaluation. These are deterministic demo/application rules, not a substitute for a complete attack signature system.

## 4. What the live drift monitor actually observes

There are two drift paths in the repository and they should not be described as the same experiment:

- **Notebook/offline path:** notebook 03 uses `StreamDriftMonitor` from `ml/src/drift/detectors.py`. It can compare true labels (`y_true`) with predictions (`y_pred`) and feed per-flow 0/1 prediction errors to ADWIN. This is possible because the replay dataset is labeled.
- **Live Flask path:** `LiveDriftMonitor` is called from `/predict` and does not receive independently verified labels for ordinary traffic. Its primary signal is the per-batch **attack ratio**: the fraction of final post-override labels that are not `Normal Traffic`. It also monitors confidence, rule-override pseudo-errors, and feature distributions.

Thus live ADWIN is not currently measuring a verified production error rate. It is measuring a change in the batch's predicted attack fraction. A shift in that signal is useful for this demo, but it does not by itself prove that classifier accuracy has fallen.

### The four named detector cards: ADWIN and three alternatives

The `/concept-drift` status contract names ADWIN, Page-Hinkley, DDM-style pseudo-error, and KS Test. Their roles are different:

| Method | What it tests in this project | Strength / why use it | Limitation in this project | Current live role |
|---|---|---|---|---|
| **ADWIN** | River ADWIN receives one attack-ratio value per prediction batch (`delta=0.002`). A second ADWIN on mean confidence uses `delta=0.01`. | Maintains an adaptive window rather than requiring one fixed window size; can react to changing numeric stream means with bounded online state. Useful for a streaming service where the baseline may change. | It only knows the signal supplied to it. On the live path, attack ratio/confidence are model outputs, not ground-truth error. Sensitivity depends on `delta`, batch size, and traffic pattern. | Attack-ratio ADWIN can trigger drift. Confidence ADWIN is warning-only. |
| **Page-Hinkley** | River Page-Hinkley receives the same batch attack-ratio stream. | Cumulative-sum style change detector; complements ADWIN as a second sequential signal on the main live indicator. | Requires threshold/forgetting choices; it detects a change in the monitored statistic, not the cause or real label accuracy. | Can trigger drift, independently of ADWIN. |
| **DDM-style error monitor** | A small custom implementation updates on rule-override flows only: error is 1 when the final rule label differs from the model's raw label, otherwise 0. Warning/drift thresholds follow `p + s` relative to its historical minimum. | Error-rate-based methods are conceptually useful when reliable online labels show whether predictions are wrong. | It is not River's built-in DDM class; live evidence is sparse and biased toward the handful of rule patterns. It has no ground-truth labels for ordinary traffic. | Status/warning telemetry only; it is not part of the live drift-event decision expression. |
| **Kolmogorov–Smirnov (KS) test** | SciPy `ks_2samp` compares reference and recent raw values for slot 14 (`Flow Bytes/s`); it requires at least 10 samples in each group and reports a signal for `p < 0.05`. | Non-parametric two-sample test for a distribution difference; does not require class labels. | Tests feature-distribution shift, not a change in the feature-to-label relationship. A p-value is sensitive to sample size and is not a measure of operational impact. | Diagnostic status only; KS is not in the live event decision expression. |

### Additional feature-shift signal: PSI

The monitor also computes Population Stability Index (PSI) for slots `[1, 4, 5, 14, 44]` using a reference set and a rolling recent set (default window 500). It uses 10 histogram bins, applies `log1p` to duration/byte/rate slots, and uses the raw value for slot 44. Scores under 0.10 are stable, 0.10–0.25 are a minor shift, and above 0.25 are marked drifted.

The current event rule in `live_monitor.py` is:

```text
ADWIN(attack_ratio) OR Page-Hinkley(attack_ratio) OR at least 2 PSI slots above 0.25
```

A confidence warning, DDM signal, or KS signal alone does not create a drift event. PSI is not one of the four named `detector_algorithms` entries, but it is a genuine part of the event decision and the feature-shift table.

### Which one is best?

There is no universal winner, and this repository does not contain a controlled head-to-head benchmark of all the live detectors under identical streams, false-alarm constraints, and ground-truth labels.

- **Best primary online detector for the current live design:** ADWIN is a reasonable choice because it is designed for streaming values, adjusts its comparison window, is already provided by River, and can monitor the batch attack-ratio signal without requiring live labels.
- **Best signal for the rehearsed synthetic feature-shift demo:** the [demo runbook](member3/DEMO_RUNBOOK.md) and [shared context](member3/CONTEXT.md) report PSI latching first in the rehearsals. That is a property of those generated distributions and PSI thresholds, not evidence that PSI is always superior.
- **Best when trusted labels are available:** an error-rate detector such as DDM becomes more meaningful because it can monitor actual mistakes. The current live DDM-style input is only a rule-override proxy.
- **Best for feature-distribution diagnostics:** PSI and KS answer that question; neither alone proves classifier concept drift.

The project’s [shared implementation notes](member3/CONTEXT.md) report scenario-specific timings: PSI fired in about five batches when feature distributions differed; ADWIN fired in about 65 batches and Page-Hinkley in about 126 batches on a pure label-flip scenario. These are different signals/scenarios, not a controlled head-to-head benchmark, so they should not be treated as comparable speed rankings.

The actual design is therefore hybrid: ADWIN is the principal online change detector, Page-Hinkley is a complementary alarm on the same signal, and PSI supplies a separate feature-distribution trigger. The live event log's detector name reflects the first trigger by code priority (ADWIN, then Page-Hinkley, then PSI), not a tournament winner.

## 5. Drift event lifecycle

`LiveDriftMonitor` is created by `ml/api.py` and persists state in `ml/artifacts/state/drift_state.json`.

1. `/predict` forms the batch's final labels, confidence values, raw vectors, model label, and rule-override flags.
2. `process_batch()` calculates attack ratio and mean confidence; updates ADWIN and Page-Hinkley; updates the DDM-style tracker for rule-override records; computes PSI and KS.
3. If the event expression is true and no drift is already latched, the monitor records one event, caps history at 20 entries, rotates the feature reference, and makes the event available to the adapter.
4. A drift latch suppresses repeated event creation until `reset_reference()` or a full reset. The adapter consumes the pending event once.
5. The monitor reports `warming_up` until 500 samples since reset, but the current `process_batch()` code does not wrap the drift decision in an explicit `status == active` check. Some runbook/context wording says drift is gated until active; the implementation and recorded PSI-during-warmup notes do not support that as a code guarantee.

The older `StreamDriftMonitor` in `detectors.py` is a simpler ADWIN wrapper used by the offline streaming experiment. The live Flask path uses `LiveDriftMonitor` in `live_monitor.py`.

## 6. Adaptation: from drift event to new champion

Drift detection does not directly mutate the model. `LiveAdapter` collects eligible examples and starts a candidate retrain only if its conditions are met.

### Pseudo-label selection

The live stream has no general ground-truth label. The adapter and live evaluator resolve labels in this order:

1. `LBL::<CLASS_NAME>::...` in `flow_id` — simulator-provided ground truth.
2. A deterministic app-layer rule override — treated as a label for the covered pattern.
3. A `Normal Traffic` prediction with confidence at least 0.90 and no override.
4. All remaining records are excluded from the adaptation/evaluation labels.

This allows an automatic demo, but rule-derived labels cover only known rules and high-confidence Normal labels are self-generated. Live metrics therefore must be described as **pseudo-labeled metrics**, not as independent production accuracy.

### Buffer and eligibility

- A ring buffer holds up to 5,000 labeled samples.
- Auto retraining needs at least 200 labeled records, two distinct classes, and 30 non-Normal records.
- Only one retrain may run at once. Automatic triggers have a 60-second cooldown; manual dashboard triggers bypass that cooldown but still obey the buffer and busy checks.
- If the adapter consumes a drift event before the buffer is ready, it records a skipped event. The drift latch remains active until a later completed retrain resets the reference, or an administrator performs the demo reset. That is why the demo runbook primes non-Normal labels before expecting an automatic promotion.

### Candidate training and promotion gates

The live candidate is a fresh LightGBM multiclass classifier trained on the eight Labrooms features with balanced class weights (`n_estimators=60`, `max_depth=6`, `learning_rate=0.1`, `random_state=42`). The adapter uses the first 75% of the buffer for fitting and newest 25% for validation. If the chronological split cannot support multiple classes in both sets, it attempts a stratified fallback when possible.

The candidate is compared with the current champion on the validation set. It is promoted only if all four gates pass:

| Gate | Default condition |
|---|---|
| Macro F1 | Candidate delta versus champion is at least -0.01. |
| Balanced accuracy | Candidate delta versus champion is at least -0.01. |
| Emerged-class recall | At least 0.70 when that class has validation support. |
| Normal false-positive guard | At most 0.05 according to the implementation's `gate_normal_fpr` calculation. |

**Metric caveat:** despite its name, the live code computes the Normal guard as `1 - precision(Normal Traffic)`. That is not the textbook false-positive rate `FP / (FP + TN)`; treat it as the code's current proxy until the metric is corrected and re-verified.

On promotion, the adapter writes versioned model/preprocessor files and `active_model.json`, then calls the Flask hot-swap hook. On rejection, the existing champion remains active and a gate report is still recorded. Both completed outcomes reset the drift reference. The manual endpoint returns 202 when accepted, 409 while busy, and 422 when buffer requirements are not met.

## 7. Live evaluation

`LiveEvaluator` keeps a rolling window of up to 500 labeled records in `eval_window.jsonl`. It reports accuracy, macro precision/recall/F1, per-class metrics, confusion matrix, latency p95, and a pre/post-promotion split. Fewer than 30 labeled records returns `insufficient_data`.

The pre/post split is based on the last successful promotion timestamp. It is useful for observing changes during a controlled demo, but interpret the values with the pseudo-label caveat above. The latency deque is in memory, so latency p95 can reset after a Flask restart until new batches arrive.

## 8. Model/drift state files

| File | Purpose |
|---|---|
| `ml/artifacts/state/drift_state.json` | Sample/batch counters, latch, recent events, detector summaries, reference/recent feature values. |
| `ml/artifacts/state/adapter_state.json` | Persists label-source counters, version, and last event; the labeled ring-buffer contents intentionally do not survive Flask restarts. |
| `ml/artifacts/state/adaptation_history.json` | Candidate evaluation reports and promotion/rejection history. |
| `ml/artifacts/state/active_model.json` | Paths and version of the latest promoted champion, used to restore it on boot. |
| `ml/artifacts/state/eval_window.jsonl` | Bounded rolling pseudo-labeled evaluation rows. |
| `ml/artifacts/models/adaptive_*_vN.joblib` | Versioned promoted candidate and preprocessor. |

`POST /admin/reset` is a demo operation guarded by `DEMO_MODE=1`. It clears live drift/adapter/evaluation state, removes the active-model pointer, and reloads the original configured champion artifacts.

## 9. Limitations to keep in the project explanation

1. **Synthetic input versus real capture:** the primary live demo generators synthesize Labrooms-shaped vectors. The Scapy sensor has a different slot-44 meaning and different populated feature profile; see [Sensor and End-to-End Data Flow](SENSOR_AND_DATA_FLOW.md).
2. **No independently labeled live stream:** live attack ratio, confidence, pseudo-errors, and pseudo-labeled evaluation are proxies. They do not establish real-world error reduction.
3. **Benchmark coverage:** the exported baseline test result contains no examples of five of the seven classes, so it cannot validate those classes.
4. **Feature mapping:** the backward-count/byte-to-packet-length mappings are declared proxies and can introduce training-serving skew.
5. **Warm-up documentation mismatch:** `warming_up` is reported as a status; current code does not explicitly prevent drift decisions during that state.
6. **False-positive gate naming:** the candidate Normal guard uses `1 - precision`, not standard FPR.
7. **Explainability:** `/explain` currently returns hardcoded demonstration values; live SHAP/LIME is not implemented.
8. **Not production hardened:** TLS, production sensor deployment, and multi-tenant hardening remain out of scope according to the root README.

## 10. Source files to study

- [`ml/api.py`](../ml/api.py) — prediction, feature extraction, rules, monitor/adaptation/evaluation wiring, endpoints.
- [`ml/src/drift/live_monitor.py`](../ml/src/drift/live_monitor.py) — live ADWIN/Page-Hinkley/DDM/PSI/KS behavior and persistence.
- [`ml/src/drift/detectors.py`](../ml/src/drift/detectors.py) — ADWIN wrapper and earlier window-based monitor.
- [`ml/src/adaptation/live_adapter.py`](../ml/src/adaptation/live_adapter.py) — pseudo-labeling, buffer, retraining, gates, promotion.
- [`ml/src/evaluation/live_evaluator.py`](../ml/src/evaluation/live_evaluator.py) — rolling pseudo-labeled evaluation.
- [`ml/src/models/adaptive_engine.py`](../ml/src/models/adaptive_engine.py) — original reusable champion/candidate gate semantics.
- [`ml/src/evaluation/metrics.py`](../ml/src/evaluation/metrics.py) — classification metrics.
- [`ml/artifacts/reports/model_comparison.csv`](../ml/artifacts/reports/model_comparison.csv) — saved offline benchmark values.
