# PHASE 04 — Live Evaluation Endpoint

| | |
|---|---|
| **Goal** | Replace the static `/evaluation` placeholder with metrics computed from the **actual live stream** — rolling window metrics + pre/post-adaptation comparison |
| **Depends on** | Phase 01 (batch labels in `predict()`), Phase 03 (`_adapter` pseudo-labels + `adaptation_history` + promotion timestamps) |
| **Enables** | Phase 05 (Evaluation page wiring), Phase 06 (demo proof slide) |
| **Est. scope** | 1 new module + `api.py` edits |

---

## Read first

1. `documentation/member3/00_MASTER_PLAN.md` — §5.2 (`eval_window.jsonl`), §8 (`/evaluation` contract)
2. `documentation/member3/TRACKER.md` — Phase 01 + 03 entries (field names as actually shipped)
3. `ml/src/evaluation/metrics.py` — `evaluate_predictions()` returns everything needed (accuracy, macro/weighted F1, balanced acc, per-class, confusion matrix)
4. `ml/src/adaptation/live_adapter.py` (Phase 03 output) — pseudo-label logic; reuse the same resolution so eval and training see identical labels
5. `ml/api.py` — the static `evaluation()` to replace

## What "live evaluation" means here

No ground truth exists in production — so we evaluate the champion against the
**same pseudo-labels** that feed adaptation (rule overrides, `LBL::` tags,
high-confidence Normals). This measures *agreement with our best available
labels* and, crucially for the demo, shows the champion degrading during drift
and recovering after adaptation.

## Build

### 1. New module: `ml/src/evaluation/live_evaluator.py`

```python
class LiveEvaluator:
    def __init__(self, state_path: Path, window: int = 500): ...
    def record(self, batch_records: list[dict]) -> None:
        """Append pseudo-labeled predictions (same rule as adapter labels).
        Each row: {ts, y_true_idx (pseudo), y_pred_idx, confidence,
                   champion_version}. Unlabeled flows are NOT recorded
        (they'd pollute metrics)."""
    def get_metrics(self) -> dict:
        """Exact /evaluation contract (§8) — or adds
        insufficient_data: true when <30 labeled samples in window."""
    def reset(self) -> None: ...
```

**Internals:**
- Ring buffer `deque(maxlen=window)` of `{ts, y_true, y_pred, conf, version}` —
  indices into `TARGET_CLASSES`, not names (matches `evaluate_predictions`).
- `get_metrics()`: run `evaluate_predictions(y_true, y_pred,
  class_names=TARGET_CLASSES)` over the window → map its output into the
  contract (`overall_metrics.accuracy/precision_macro/recall_macro/f1_macro`,
  `per_class_metrics`, `confusion_matrix` as nested lists — verify key names
  against metrics.py's real return dict before writing; adapt names if needed).
- `latency_p95_ms`: keep a `deque(maxlen=500)` of `/predict` `latency_ms`
  values (api.py already computes it — pass it in `record()`).
- **pre/post split**: read the last `promoted:true` timestamp from
  `adaptation_history.json` (Phase 03 writes it) → split the window at that ts →
  compute `f1_macro` + `samples` for each side → `pre_post_adaptation` block.
  If never promoted: `"last_adaptation": null`, sides computed as pre=window,
  post=null.
- Persist buffer + latency deque to `ml/artifacts/state/eval_window.jsonl`
  (append per batch, truncate to last `window` lines on write; restore on
  boot, tolerate corruption).
- Thread-lock all mutation (same pattern as monitor/adapter).

### 2. `ml/api.py` edits

- Instantiate `LiveEvaluator` beside monitor/adapter.
- In `predict()`: after predictions built → `_evaluator.record(batch_records,
  latency_ms)` inside the same guarded block (one try/except around
  monitor+adapter+evaluator calls is fine — log which subsystem failed).
- `GET /evaluation` → `_evaluator.get_metrics()` (replaces static body; keep
  route + `dataset` string = `"Live Labrooms stream (pseudo-labeled)"`).
- `POST /admin/reset` (Phase 03) must also call `_evaluator.reset()` — update
  it there.

## Do NOT

- Don't evaluate on flows with no pseudo-label — unlabeled traffic is not
  evidence of model error.
- Don't compute ROC-AUC unless `evaluate_predictions` already gives it cheaply
  with ≥2 classes present — else omit it from `overall_metrics` (UI tolerates
  missing keys; contract marks it optional).
- Don't regress `/predict` latency — `record()` is O(1) amortized.

## Verification

```bash
# 1. send ~200 normal flows → GET /evaluation:
#    accuracy ≈ 1.0 area, confusion matrix mostly diagonal on row 0,
#    window.size grows

# 2. send ~100 attack flows (rule-triggering):
#    per_class_metrics shows DoS/Web Attacks rows; if champion missed some
#    before rules fired, you may see pre-adaptation f1 dip — that's the story

# 3. trigger an adaptation (Phase 03) → next GET /evaluation shows
#    pre_post_adaptation.last_adaptation set and both sides populated

# 4. restart Flask → metrics survive (eval_window.jsonl restored)

# 5. fresh reset with <30 samples → "insufficient_data": true present
```

## Definition of done

- [ ] `/evaluation` returns contract-shaped live metrics that change with traffic
- [ ] `pre_post_adaptation` populates after a real promotion
- [ ] State survives restart; reset works via `/admin/reset`
- [ ] `/predict` latency impact still <20 ms/batch
- [ ] TRACKER.md updated
