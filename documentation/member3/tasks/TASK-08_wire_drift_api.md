# TASK-08 — Wire Drift Monitor into `ml/api.py` (live `/concept-drift`)

| | |
|---|---|
| **Wave** | B — **sequential** (single writer on `ml/api.py`; runs alone after Wave A merge) |
| **Depends on** | T01 |
| **Input handoffs** | `handoffs/TASK-01_*.md` — shipped `LiveDriftMonitor` signatures |
| **Files you may touch** | `ml/api.py`, `.gitignore` (add `ml/artifacts/state/`) |
| **Files you must NOT touch** | `ml/src/*`, `server/`, `client/` |
| **Goal** | Instantiate the monitor, feed every `/predict` batch to it, replace static `/concept-drift` with live data |

---

## Read first

1. `documentation/member3/CONTEXT.md` — merged Wave-A facts/deviations
2. `handoffs/TASK-01_*.md` — actual shipped constructor/method names
3. `00_MASTER_PLAN.md` — §5.2 (state dir), §8 (`/concept-drift` contract), §9.1 (`batch_record`), §9.5 (wiring order)
4. `ml/api.py` — `predict()` (~185–282), `_detect_labrooms_app_layer_anomaly` (~148), static `concept_drift()` (~286), `_load_artifacts`

## Build

- `mkdir ml/artifacts/state/` (created implicitly by code — `Path.mkdir(parents=True, exist_ok=True)`); add `ml/artifacts/state/` to `.gitignore`.
- Instantiate `_drift_monitor = LiveDriftMonitor(STATE_DIR/"drift_state.json")`
  at module load, after `_load_artifacts`, per TASK-01's shipped signature.
- In `predict()`: while building `predictions`, collect the §9.1 `batch_record`
  per flow — `flow_id`, `raw_features`, final `label`/`label_index`,
  `confidence`, `rule_override` (did `app_anomaly` fire), `model_raw_label` +
  `model_raw_index` (pre-override). Store the raw model label — TASK-09's
  adapter and TASK-10's evaluator consume the same list.
- After the response is assembled (before `return`), call
  `_drift_monitor.process_batch(batch_records)` inside a try/except that logs
  and **never raises** — drift monitoring must never break `/predict`.
- Replace static `concept_drift()` body with
  `return jsonify(_drift_monitor.get_status())` — keep route path + no-auth
  access identical. Every §8 contract field must be present (field names are
  law — TASK-14 builds against them).

## Do NOT

- Don't change `/predict`'s response shape — Node depends on it.
- Don't touch adaptation/eval endpoints — TASK-09/10 own those.
- Don't add dependencies.

## Verification (Flask direct — Node optional)

```bash
# Flask up (:5001, MODEL_PATH+PREPROCESSOR_PATH set)
# 1. Baseline: POST /predict ×10 batches of ~50 normal-ish flows
#    (duration<1 s, bwd_bytes<50 k, slot44=200)
python -c "..."   # or reuse TASK-02 generator via full stack
# 2. GET /concept-drift → status active, drift_state stable, samples_processed
#    ≥500, all detector_algorithms.*.drift_signal false
# 3. Attack burst: ×5 batches, duration>30 s + slot44=504
#    (vector shapes per sensor/simulate_attacks.py::build_labrooms_flow)
# 4. GET /concept-drift → drift_state "drift", drift_events entry,
#    last_drift_timestamp set, slot-1 PSI likely spiked,
#    ADWIN_attack_ratio.drift_signal true (or already consumed)
# 5. Restart Flask → GET /concept-drift → samples_processed + drift_events
#    survived (state file worked)
# 6. /predict latency overhead <20 ms/batch; response shape unchanged
```

Keep a small reusable check script under `ml/scripts/check_drift_api.py` if
convenient — note it in the handoff.

## Finish protocol (sequential — you update shared files)

- `handoffs/TASK-08_wire-drift.md` from template.
- Append to `CONTEXT.md`: §C facts (e.g., "predict() emits batch_records",
  actual field names if deviated), §D deviations, §A verified env rows.
- Set your `TRACKER.md` row + Handoff Index row.

## Definition of done

- [ ] `/concept-drift` returns live §8-contract data
- [ ] Attack burst → drift event + `drift_state:"drift"`
- [ ] State survives Flask restart
- [ ] `/predict` shape unchanged, <20 ms/batch overhead
- [ ] `batch_records` built per §9.1 (TASK-09/10 reuse it)
- [ ] Handoff + CONTEXT.md + TRACKER.md updated
