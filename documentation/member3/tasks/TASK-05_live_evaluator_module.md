# TASK-05 — Live Evaluator Module (`ml/src/evaluation/live_evaluator.py`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T01–T07) |
| **Depends on** | none — code against the frozen §9.4 interface |
| **Input handoffs** | none |
| **Files you may touch** | `ml/src/evaluation/live_evaluator.py` (new) only |
| **Files you must NOT touch** | `ml/api.py`, `ml/src/evaluation/metrics.py`, everything else — wiring is TASK-10 |
| **Goal** | Self-contained `LiveEvaluator`: rolling-window pseudo-labeled metrics + pre/post-adaptation split, per the §8 `/evaluation` contract |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `00_MASTER_PLAN.md` — §5.2 (`eval_window.jsonl`), §5.4 (pseudo-label rule — implement IDENTICALLY to the adapter), §8 (`/evaluation` contract), §9.1/§9.4
3. `ml/src/evaluation/metrics.py` — `evaluate_predictions()` real return dict (verify key names before mapping into the contract)
4. `ml/src/features/feature_contract.py` — `TARGET_CLASSES`

## What "live evaluation" means

No ground truth in production → evaluate the champion against the **same
pseudo-labels** that feed adaptation (§5.4: `LBL::` tag → rule-override →
high-confidence Normal → else excluded). This measures *agreement with our
best available labels* and shows the champion degrading during drift and
recovering after adaptation.

## Build — `ml/src/evaluation/live_evaluator.py`

`LiveEvaluator` per §9.4 exactly.

- `record(records, latency_ms)`: apply the §5.4 rule per record; append
  `{ts, y_true (int idx), y_pred = record's label_index, conf, version}` to a
  `deque(maxlen=window)`. **Unlabeled flows are NOT recorded** — they pollute
  metrics. Keep a `deque(maxlen=500)` of `latency_ms` for p95.
- `get_metrics()`: run `evaluate_predictions(y_true, y_pred,
  class_names=TARGET_CLASSES)` over the window → map its real output keys into
  the §8 contract (`overall_metrics.accuracy/precision_macro/recall_macro/
  f1_macro`, `per_class_metrics`, `confusion_matrix` nested lists,
  `class_names`, `latency_p95_ms` from the latency deque,
  `window.size`/`window.since`).
  - <30 labeled samples → `"insufficient_data": true` + zeros.
  - **pre/post split:** read last `promoted:true` timestamp from
    `ml/artifacts/state/adaptation_history.json` (written by TASK-04's adapter —
    tolerate the file not existing yet) → split window at that ts →
    `f1_macro` + `samples` each side → `pre_post_adaptation` block. Never
    promoted → `last_adaptation: null`, pre=window, post=null.
- Persist to `ml/artifacts/state/eval_window.jsonl`: append per batch;
  truncate to last `window` lines on write; restore on boot; tolerate corruption.
- `threading.Lock` on all mutation; `record()` is O(1) amortized.

## Do NOT

- Don't evaluate flows with no pseudo-label.
- Don't compute ROC-AUC unless `evaluate_predictions` provides it cheaply with
  ≥2 classes — else omit (UI tolerates missing keys).
- Don't touch api.py or metrics.py.

## Verification (in-process)

```bash
.venv\Scripts\activate
python -c "
# LiveEvaluator on tmp state path: feed 40 synthetic records where y_pred
# matches pseudo-label → get_metrics(): accuracy≈1.0, window.size=40,
# insufficient_data absent. Feed 10 → insufficient_data:true.
# Simulate adaptation_history.json with a promoted timestamp mid-window →
# pre_post_adaptation splits correctly.
# Re-instantiate on same path → rows restored."
```

## Finish protocol

- `handoffs/TASK-05_live-evaluator.md` from template — shipped signatures.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] `LiveEvaluator` matches §9.4; pseudo-label rule identical to §5.4
- [ ] `get_metrics()` returns every §8 contract field + `insufficient_data` path
- [ ] pre/post split works off `adaptation_history.json` (and tolerates its absence)
- [ ] `eval_window.jsonl` round-trips across re-instantiation
- [ ] Handoff written with interface surface + verification output
