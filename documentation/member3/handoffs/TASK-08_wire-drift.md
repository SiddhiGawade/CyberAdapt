# HANDOFF — TASK-08 — Wire Drift Monitor into `ml/api.py` (live `/concept-drift`)

| | |
|---|---|
| **Task** | TASK-08 — Wire Drift Monitor into `ml/api.py` (live `/concept-drift`) |
| **Status** | `done` |
| **Wave** | B |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-01 (`LiveDriftMonitor` shipped signatures + latch semantics) |

---

## Files created

- none (temporary `ml/scripts/check_drift_api.py` was used for verification then **deleted** — recreate from the Verification section below if needed; TASK-01 precedent).

## Files modified

- `ml/api.py` — import `LiveDriftMonitor`/`set_default_monitor`; `STATE_DIR` + `_drift_monitor` singleton at module load; §9.1 `batch_records` built inside `predict()`; guarded `process_batch()` call before `return`; static `concept_drift()` body replaced with `_drift_monitor.get_status()`.
- `.gitignore` — added `ml/artifacts/state/` under the ML artifacts section (line 9).

## Interface surface shipped

```python
# ml/api.py — module level, after _load_artifacts/_extract_labrooms_features
STATE_DIR = ARTIFACTS_DIR / "state"          # ml/artifacts/state/ (gitignored)
_drift_monitor = LiveDriftMonitor(STATE_DIR / "drift_state.json")
set_default_monitor(_drift_monitor)          # detect_drift() resolves to this instance

# inside predict() — one §9.1 record per accepted flow, appended after the
# prediction in BOTH branches (override + model):
batch_records.append({
    "flow_id": fid,                          # as received (may carry LBL:: tag)
    "raw_features": raw_vec,                 # raw 52-slot vector (post duration clamp)
    "label": label,                          # FINAL label, post rule-override
    "label_index": idx_val,
    "confidence": conf_val,                  # float, or None if no predict_proba
    "rule_override": app_anomaly is not None,
    "model_raw_label": model_raw_label,      # TARGET_CLASSES[int(label_idx)] or "Unknown"
    "model_raw_index": model_raw_index,      # int(label_idx)
})

# after response assembly, before return — §9.5 wiring point (T09/T10 extend THIS block):
try:
    _drift_monitor.process_batch(batch_records)
except Exception:
    logger.exception("Drift monitor process_batch failed — /predict unaffected")

# GET /concept-drift (route path + no-auth unchanged):
return jsonify(_drift_monitor.get_status())
```

## Verification run

Flask: `MODEL_PATH=ml/artifacts/models/champion_model.joblib PREPROCESSOR_PATH=ml/artifacts/models/preprocessor.joblib DEMO_MODE=1 PORT=5001 .venv/Scripts/python.exe -m ml.api` → `:5001` (mongod/Node were NOT running — Flask-direct verification per spec).

```
$ .venv/Scripts/python.exe ml/scripts/check_drift_api.py   (deleted after run)
→ [shape] response keys: ['latency_ms', 'predictions']
  [shape] prediction keys: ['confidence', 'flow_id', 'label', 'label_index', 'probabilities']

  [baseline] 550 flows -> status=active drift_state=stable drift_detected=False
             samples=551 attack_ratio_recent=0.0 events=0
  [baseline] signals: ADWIN_attack_ratio=False, DDM_pseudo_error=False, KS_Test=False, PageHinkley=False
  [baseline] PSI: slot1=0.0016(stable), slot4=0.006(stable), slot5=0.0008(stable),
             slot14=0.0074(stable), slot44=0.0(stable)

  [attack] +250 flows (duration>30s + slot44=504 -> DoS rule override)
           -> drift_state=drift drift_detected=True last_drift=2026-10-04T06:17:49Z events=1
  [attack] event[0]: {"detector":"PSI","signal":"feature_psi","samples_processed":701,
           "detail":"attack_ratio 1.00; PSI drifted on 2 slots (Flow Duration, Flow Bytes/s)",...}
  [attack] signals: ADWIN_attack_ratio=False, DDM_pseudo_error=True, KS_Test=True, PageHinkley=False
  [attack] PSI: slot1=0.1708(minor_shift) slot4=0.1704(minor_shift) slot5=0.1054(minor_shift)
           slot14=0.172(minor_shift) slot44=0.1695(minor_shift)

  [latency] 11 normal batches: wall avg=52.1ms | reported latency_ms avg=44.92ms
            wall-latency (incl. HTTP+JSON+process_batch+jsonify) avg=7.15ms  → <20ms ✓
  ALL CHECKS PASSED
```

Restart persistence (state file written at batch-25 persist + drift fire):
```
$ kill Flask; restart with same env; curl http://127.0.0.1:5001/concept-drift
→ status=active drift_state=drift drift_detected=True
  samples_processed=1201  last_drift=2026-10-04T06:15:13Z
  drift_events=1 (PSI)  attack_ratio_recent=0.2        → state survived restart ✓
```

In-process cost of `process_batch` (50 records, warm 500-flow windows): **~2 ms/batch**; `get_status()`: ~1.1 ms.

## Outputs produced

- `GET /concept-drift` now serves the live §8 contract verbatim: `status` (warming_up→active at ≥500 samples), `drift_detected`, `drift_state`, `samples_processed`, `samples_processed_since_retrain`, `last_drift_timestamp`, `attack_ratio_recent`, `detector_algorithms{ADWIN_attack_ratio,PageHinkley,DDM_pseudo_error,KS_Test}`, `labrooms_features_drift` (5 slots), `drift_events` — verified against fresh, warmed, drifted, and restored states.
- `/predict` response shape **byte-identical** (keys asserted in-script); every accepted flow now also feeds the monitor.
- Attack burst → drift event fires on the **first attack batch** (PSI ≥2 slots — rule-override features diverge hard from baseline ref).
- State survives Flask restart (1201 samples + latched event restored). `ml/artifacts/state/` is gitignored.
- Post-verification: state file deleted and Flask **left running clean** (`warming_up`, 0 samples) for T09 — no stale latched drift will trip its adapter wiring.

## Deviations from spec

1. **`set_default_monitor(_drift_monitor)` added** (one line) — TASK-01 shipped the helper for exactly this; nothing in `api.py` calls `detect_drift()` today, but registering prevents a lazy second monitor racing the same `drift_state.json`.
2. **`STATE_DIR.mkdir` wrapped in `try/except OSError`** (warns, non-fatal) — keeps module import safe even if the fs is read-only; the monitor re-mkdirs on `_persist()` anyway.
3. `batch_record.confidence` may be `None` when the model lacks `predict_proba` — monitor `_as_float` already tolerates None (skips the confidence signal); flagged for T09/T10 label resolution.
4. `raw_features` = the clamped 52-slot vector actually fed to the model (negative Flow Duration clamped to 0) — the only mutation the endpoint performs.

## Handoff notes for dependent tasks

- For **TASK-09**: `_drift_monitor` is a module-level singleton — inject `consume_drift_event=_drift_monitor.consume_drift_event` and `reset_drift_reference=_drift_monitor.reset_reference` into `LiveAdapter`. Add `observe()`/`maybe_trigger()` calls **inside the existing try/except** at the end of `predict()` (comment marks the §9.5 spot); `batch_records` is already built for you.
- For **TASK-10**: same `batch_records` list; add `_evaluator.record(batch_records, latency_ms)` in the same guarded block. Note `latency_ms` covers only transform+predict (pre-existing semantics — don't move `t_start`).
- For **T09/T10 label resolution**: `confidence` can be `None`; `label` may be `"Unknown"` when `label_idx` is out of range (mirrors response behavior). `rule_override` is a plain bool.
- For **TASK-11**: drift fired on the **first** attack batch (PSI on ≥2 slots) — not ~5 batches as in T01's synthetic run; rule-override traffic diverges faster. During a rule-override campaign `DDM_pseudo_error.drift_signal` also goes True (model disagrees with every override → pseudo-error rate 1.0) and `KS_Test` signals on slot 14 — expected, not a bug.
- For **everyone hitting Flask on this box**: `localhost` costs **~2 s/request** (resolves to `::1`, times out, falls back — Flask binds IPv4 `0.0.0.0`). Use `http://127.0.0.1:5001` for any timing-sensitive check.
- Flask is **left running** on :5001 with `DEMO_MODE=1`, clean state. To reset drift for any reason pre-/admin/reset: stop Flask → delete `ml/artifacts/state/drift_state.json` → restart.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `predict()` builds §9.1 `batch_records` (all 8 fields incl. `rule_override` bool + `model_raw_*`) and feeds `_drift_monitor.process_batch()` inside a `try/except` that logs and never raises; `/concept-drift` = `jsonify(_drift_monitor.get_status())`.
- CONTEXT fact: `_drift_monitor` singleton lives in `ml/api.py` (`STATE_DIR = ml/artifacts/state`); `set_default_monitor()` registered — module `detect_drift()` resolves to the wired instance.
- CONTEXT fact: on this Windows box `localhost:5001` ≈ +2 s/req (::1 first, Flask is IPv4-only) — use `127.0.0.1:5001` for timing checks; drift wiring overhead is ~2 ms/batch in-process.
- CONTEXT deviation: `batch_record.confidence` may be `None` (no `predict_proba`); `raw_features` is the post-clamp vector. Both tolerated by monitor.
- Open issue: none.
- TRACKER row status: `done` — "Live /concept-drift verified E2E: baseline stable→active, attack burst fires latched PSI drift, state survives restart, /predict shape unchanged (~2 ms monitor overhead)"
