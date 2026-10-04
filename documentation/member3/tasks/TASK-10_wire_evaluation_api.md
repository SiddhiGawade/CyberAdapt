# TASK-10 — Wire Evaluation into `ml/api.py` (live `/evaluation`)

| | |
|---|---|
| **Wave** | B — **sequential** (single writer on `ml/api.py`; runs after T09) |
| **Depends on** | T05, T09 |
| **Input handoffs** | `handoffs/TASK-05_*.md` (shipped `LiveEvaluator` signature), `handoffs/TASK-09_*.md` (predict() layout as left by T09, reset wiring) |
| **Files you may touch** | `ml/api.py` only |
| **Files you must NOT touch** | `ml/src/*`, `server/`, `client/` |
| **Goal** | Instantiate the evaluator, record every batch, replace static `/evaluation`, extend `/admin/reset` |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `handoffs/TASK-05_*.md` + `handoffs/TASK-09_*.md`
3. `00_MASTER_PLAN.md` — §5.2 (`eval_window.jsonl`), §8 (`/evaluation` contract), §9.4–9.5
4. `ml/api.py` — `predict()` (monitor+adapter calls as left by T09), static `evaluation()`, `/admin/reset` from T09

## Build

- Instantiate `_evaluator = LiveEvaluator(STATE_DIR/"eval_window.jsonl")` per
  TASK-05's shipped signature, beside monitor/adapter.
- In `predict()`'s guarded block (per §9.5): `_evaluator.record(batch_records,
  latency_ms)` — `latency_ms` already computed for the response.
- `GET /evaluation` → `return jsonify(_evaluator.get_metrics())` — keep route
  + `dataset` string `"Live Labrooms stream (pseudo-labeled)"`.
- Extend `POST /admin/reset` (from T09) to also `_evaluator.reset()` and clear
  `eval_window.jsonl` (add `"eval_window"` to the cleared list — verify it's
  already in the contract payload).

## Do NOT

- Don't record unlabeled flows (evaluator's job to filter — but don't bypass it).
- Don't regress `/predict` latency (still <20 ms/batch total overhead).
- Don't touch metrics.py or the evaluator module.

## Verification (Flask direct)

```bash
# 1. ~200 normal flows → GET /evaluation: accuracy≈1.0, confusion matrix
#    mostly diagonal row 0, window.size grows
# 2. ~100 attack flows → per_class_metrics shows attack rows
# 3. After a real promotion (rerun T09 flow or wait for drift): next
#    GET /evaluation → pre_post_adaptation.last_adaptation set, both sides populated
# 4. Restart Flask → metrics survive (eval_window.jsonl restored)
# 5. DEMO_MODE reset → <30 samples → "insufficient_data": true
# 6. /predict latency still <20 ms/batch overhead
```

## Finish protocol (sequential — update shared files)

- `handoffs/TASK-10_wire-evaluation.md` from template.
- Append `CONTEXT.md` §C/§D; set TRACKER.md rows.

## Definition of done

- [ ] `/evaluation` returns live §8-contract metrics that change with traffic
- [ ] `pre_post_adaptation` populates after a real promotion
- [ ] State survives restart; `/admin/reset` clears it
- [ ] `/predict` overhead still <20 ms/batch
- [ ] Handoff + CONTEXT.md + TRACKER.md updated
