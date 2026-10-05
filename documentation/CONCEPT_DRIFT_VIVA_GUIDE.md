# Concept Drift and Model Adaptation — Viva Guide

This guide explains the concept-drift part of the project in simple language. It focuses on the **live Flask system** unless a section explicitly says “offline replay.”

## The one-minute overview

Our network-traffic classifier watches for changes in incoming traffic. Four named methods appear on the drift dashboard: **ADWIN, Page-Hinkley, a custom DDM-style monitor, and the Kolmogorov–Smirnov (KS) test**. The live system also calculates **PSI** as an extra feature-shift signal.

A detector does not update the model by itself. When the live event rule fires, the adapter collects usable labeled examples, trains a new LightGBM candidate, checks it against the current model, and promotes it only if it passes quality checks. The live system has limited verified labels, so some of its training labels are pseudo-labels.

## 1. What is concept drift?

A machine-learning model learns patterns from earlier data. **Concept drift** means that the patterns connecting inputs to their labels change over time. For example, network traffic may change because a new attack campaign begins or a familiar attack starts producing different flow patterns.

A related term is **data or feature drift**: the distribution of input features changes. Feature drift can be a clue that the environment has changed, but it does not necessarily mean that the model is now making more mistakes.

In this project, most live detectors observe model outputs or feature distributions. They are useful warning signals, but they do not prove that live accuracy has dropped because ordinary live traffic does not come with independently verified labels.

## 2. The four named drift detectors

### ADWIN — compares recent and older averages

**ADWIN** means *Adaptive Windowing*. It keeps a window of recent values and adjusts the window size as data arrives. It checks whether an older portion and a newer portion of that window have meaningfully different averages. If they do, it signals drift.

- **Live input:** one attack-ratio value per prediction batch. The attack ratio is the fraction of the batch labeled as something other than `Normal Traffic`.
- **Project setting:** the attack-ratio detector uses `delta=0.002`. A second ADWIN monitors mean confidence with `delta=0.01`; that one is warning-only.
- **Easy way to say it:** “ADWIN compares the recent traffic signal with its recent history, and changes its window automatically when the signal shifts.”
- **Important limitation:** live attack ratio is based on predictions, not verified ground-truth errors.

In the offline replay experiment, true labels are available, so ADWIN can instead receive a `0` for a correct prediction and a `1` for an incorrect prediction.

### Page-Hinkley — accumulates sustained changes

**Page-Hinkley** tracks deviations from the usual level and accumulates them over time. A persistent change can eventually cross its detection threshold; a single unusual value is less informative than a sustained shift.

- **Live input:** the same batch attack ratio used by ADWIN.
- **Project role:** it is a second, independent live trigger alongside ADWIN.
- **Easy way to say it:** “Page-Hinkley adds up small changes; if the change continues, the accumulated evidence raises an alert.”
- **Important limitation:** it detects change in the monitored number, not the cause of the change or a proven loss of accuracy.

### DDM-style monitor — watches a limited error proxy

**DDM** stands for *Drift Detection Method*. In general, DDM tracks an error rate and its statistical variation. It compares the current error level with the best (lowest) level seen so far. In the classic-style thresholds used here, it reports a warning around `p_min + 2*s_min` and drift around `p_min + 3*s_min`, where `p` is the running error rate and `s` is its estimated standard deviation.

- **Live input:** only flows where an application rule overrode the model. The monitor records a pseudo-error of `1` if the final rule label differs from the model’s raw label, otherwise `0`.
- **Project role:** warning/status telemetry only. DDM-style status alone does **not** fire a live drift event.
- **Easy way to say it:** “DDM checks whether the observed error proxy has risen well above its earlier low point.”
- **Important limitation:** this is a small custom DDM-style implementation, not River’s built-in DDM. It sees only rule-overridden flows, not verified outcomes for all traffic.

### KS Test — compares two feature distributions

The **Kolmogorov–Smirnov two-sample test** compares the distributions of two groups of values. Here, it compares a reference group with a recent group for the `Flow Bytes/s` feature (slot 14). It needs at least 10 values in each group and reports a signal when `p < 0.05`.

- **Easy way to say it:** “KS checks whether recent flow-throughput values look statistically different from the reference values.”
- **Project role:** diagnostic/status information only. KS alone does **not** trigger a live drift event.
- **Important limitation:** a changed feature distribution is not the same as proving that attack classification accuracy has fallen.

## 3. PSI: an additional live feature-shift signal

**Population Stability Index (PSI)** is an additional feature-distribution check; it is not one of the four named detector cards. It compares a reference window with a rolling recent window for five slots:

- Flow Duration (slot 1)
- Total Fwd Bytes (slot 4)
- Total Bwd Bytes (slot 5)
- Flow Bytes/s (slot 14)
- HTTP Status Code (slot 44)

The live monitor uses 10 histogram bins. It applies `log1p` to slots 1, 4, 5, and 14, and uses the raw value for HTTP status. Its interpretation is:

| PSI value | Meaning in this project |
|---:|---|
| Below `0.10` | Stable |
| `0.10` to `0.25` | Minor shift |
| Above `0.25` | Drifted feature |

The default reference/recent window size is 500. **At least two PSI slots above `0.25` can trigger a live drift event.**

## 4. What creates a live drift event?

The live event rule is:

```text
ADWIN(attack_ratio)
OR Page-Hinkley(attack_ratio)
OR at least 2 PSI slots above 0.25
```

So ADWIN or Page-Hinkley can trigger an event independently. PSI can trigger one when at least two monitored features pass its threshold. A confidence warning, DDM-style signal, or KS signal alone is not enough.

After an event, the monitor latches the drift state to avoid repeatedly creating events for the same shift. The adapter consumes the pending event and, after a completed retraining attempt, resets the drift reference so future traffic can be compared with a newer baseline.

**Warm-up nuance:** the status is `warming_up` until 500 samples have arrived since the last reset. However, the drift decision is not explicitly gated on the status being `active`, so do not claim that the code guarantees no drift event during warm-up.

## 5. How the model adapts after an alert

The model is **not** changed immediately when drift is detected. The live adapter follows these steps:

### Step 1: Collect examples that have usable labels

The adapter resolves a label in this order:

1. A simulator-provided class in a `LBL::<CLASS_NAME>::...` flow ID.
2. The final label from a deterministic application-rule override.
3. `Normal Traffic` when the model predicts Normal with confidence of at least `0.90` and no rule override applies.
4. Otherwise, the flow is excluded from adaptation training.

This means a drift alert alone does not tell the model what a new attack is. To learn a particular attack, the buffer needs examples with a usable label for that attack.

### Step 2: Wait for enough buffered data

The adapter stores eligible examples in a ring buffer of up to 5,000 samples. Automatic retraining requires:

- At least 200 labeled samples.
- At least two different classes.
- At least 30 non-Normal samples.
- No other retraining job already running.
- The 60-second automatic-trigger cooldown to have elapsed.

If a drift event arrives before the buffer is ready, the attempt is recorded as skipped. The drift latch remains active until a completed retrain resets it or an administrator performs a demo reset. This is why a demo should generate or prime labeled attack traffic before expecting automatic retraining.

### Step 3: Train a new candidate

The adapter trains a **fresh multiclass LightGBM model** on the eight Labrooms deployment features:

`Flow Duration`, `Total Fwd Packets`, `Total Length of Fwd Packets`, `Fwd Packet Length Max`, `Fwd Packet Length Min`, `Bwd Packet Length Max`, `Bwd Packet Length Min`, and `Flow Bytes/s`.

The candidate uses balanced class weights, `n_estimators=60`, `max_depth=6`, and `learning_rate=0.1`. The adapter fits a new preprocessor as well. This is **batch retraining from the buffer**, not a one-row-at-a-time update to the existing model.

The usual split is chronological: the first 75% is used for training and the newest 25% for validation. If this leaves too few classes in the train or validation part, the adapter attempts a stratified split when possible.

### Step 4: Check whether it is safe to replace the champion

The candidate and current champion are evaluated on the same validation set. The candidate must pass all four gates:

| Gate | Requirement |
|---|---|
| Macro F1 | Candidate is no more than `0.01` below the champion. |
| Balanced accuracy | Candidate is no more than `0.01` below the champion. |
| Emerged-class recall | At least `0.70`, when that class appears in validation data. |
| Normal-class guard | At most `0.05` according to the current implementation. |

The “emerged class” is selected as the most frequent non-Normal pseudo-labeled class in the buffer. Training still uses all eligible classes in the buffer; this class receives a specific recall check.

**Metric caveat for viva:** although the code calls the last gate a Normal false-positive-rate guard, it currently calculates it as `1 - precision(Normal Traffic)`. That is not the textbook false-positive-rate formula. Describe it as the project’s current Normal-class guard/proxy, not as a verified textbook FPR.

### Step 5: Promote or keep the current model

- **All gates pass:** save the new model and preprocessor as a new version, then hot-swap it into the API as the champion.
- **Any gate fails:** reject the candidate and keep the current champion active.

The system records the result either way. After a completed candidate evaluation, it resets the drift reference for the next monitoring period.

## 6. Live system versus offline replay

These are two different paths in the project:

| Path | What ADWIN can monitor | Labels available? |
|---|---|---|
| Offline streaming notebook | Per-flow `0/1` prediction errors from true labels (and an optional numeric feature signal in the reusable monitor). | Yes, the replay dataset is labeled. |
| Live Flask API | Batch attack ratio; confidence is also monitored separately. | No independently verified label for ordinary traffic; adaptation uses the eligible pseudo-label sources described above. |

For the viva, do not say that live ADWIN measures the real production error rate. In the live service it measures a change in the **predicted attack fraction**. The offline replay can measure actual prediction errors because it has true labels.

## 7. Ready-to-say viva answer

> “Concept drift means that network traffic patterns or the relationship between traffic features and attack labels can change over time. In our live system, ADWIN and Page-Hinkley monitor the batch attack ratio. A custom DDM-style monitor watches a limited error proxy from rule overrides, while the KS test compares old and recent Flow Bytes per second distributions. We also use PSI to monitor several feature distributions; an event is triggered by ADWIN, Page-Hinkley, or at least two PSI features crossing the threshold. The alert does not directly change the model. The adapter collects examples with usable labels, trains a new LightGBM candidate, and compares it with the current champion. The candidate replaces the champion only if it passes the validation gates. Because ordinary live traffic has no verified labels, we describe this live process as pseudo-labeled adaptation, not proof of production accuracy improvement.”

## 8. Common viva questions

**Q: Does detecting drift mean the model is definitely inaccurate?**

No. It means a monitored signal changed. In the live API, the main ADWIN signal is predicted attack ratio, not verified prediction error.

**Q: Which detectors directly trigger model adaptation?**

ADWIN on attack ratio, Page-Hinkley on attack ratio, or PSI drift in at least two feature slots. DDM-style and KS signals alone do not trigger an event.

**Q: Does the existing model learn continuously after every flow?**

No. The adapter buffers eligible examples and trains a separate candidate model in a batch. It promotes that candidate only after validation gates pass.

**Q: How can the model learn a new attack?**

The training buffer needs examples labeled as that attack, such as simulator-tagged or covered by a deterministic rule. Unlabeled attack traffic is not automatically converted into a trusted attack label.

**Q: Why compare the candidate with the champion?**

To avoid replacing the current model with a candidate that performs worse overall or misses the emerged class. Failed candidates are rejected.

**Q: What is the main limitation of the live adaptation demo?**

Most live traffic has no independently verified labels. Rule-based labels cover only known patterns, and high-confidence Normal labels are self-generated, so reported live metrics are pseudo-labeled.

## Implementation references

- [Full technical drift and adaptation notes](ML_DRIFT_ADAPTATION.md)
- [Live drift monitor](../ml/src/drift/live_monitor.py)
- [Offline streaming detector](../ml/src/drift/detectors.py)
- [Live adaptation module](../ml/src/adaptation/live_adapter.py)
- [Feature contract](../ml/src/features/feature_contract.py)
- [API wiring](../ml/api.py)
