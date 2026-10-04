# PHASE 03 — Model Adaptation Backend

| | |
|---|---|
| **Goal** | Drift-triggered candidate retraining with gated promotion, hot-swap into `/predict`, persistent state — plus real `/adaptation` and a manual `POST /adaptation/trigger` |
| **Depends on** | Phase 01 (`LiveDriftMonitor` + `consume_drift_event()` + batch labels in `predict()`) |
| **Enables** | Phase 04 (pre/post metrics), Phase 05 (UI), Phase 06 (demo) |
| **Est. scope** | 1 new module + `api.py` edits + `telemetry.js` proxy route |

---

## Read first

1. `documentation/member3/00_MASTER_PLAN.md` — §5.2 (state files), §5.4 (pseudo-labels), §5.5 (adaptation flow), §8 (contracts)
2. `documentation/member3/TRACKER.md` — Phase 01 entry: monitor API names, batch payload fields, any deviations
3. `ml/src/models/adaptive_engine.py` — `AdaptiveModelManager.retrain_candidate()` + `evaluate_and_promote_candidate()`; reuse via composition
4. `ml/src/drift/live_monitor.py` (Phase 01 output) — its batch dict shape is your label source
5. `ml/src/features/preprocessing.py` — `CICIDSDataPreprocessor.fit_transform/transform`
6. `ml/api.py` — globals `_champion_model`, `_preprocessor`, `_load_artifacts`

## Key reality check before coding

`AdaptiveModelManager` was written for notebook 03 (52-feature CICIDS frames).
Our live buffer rows are the **8-name Labrooms dicts** (`_extract_labrooms_features`
output) + pseudo-labels. Two clean options — **pick (a)** unless Phase-01 log
says otherwise:

- **(a)** Don't reuse `AdaptiveModelManager` for training; replicate its *gate
  logic* (`PromotionGateConfig`, 4 gates, promotion report shape) in the new
  live adapter operating on `LABROOMS_DEPLOYMENT_FEATURES` frames. Reuse
  `evaluate_predictions()` for both sides.
- (b) Subclass/patch the manager to accept custom `feature_cols`. Only if it
  stays readable.

Either way the **gate semantics and the `adaptation_history.json` report shape
stay identical to `adaptive_engine.py`** (fields `window_id`, `promoted`,
`champion_*`, `candidate_*`, `gates_passed`, timestamps) — Phase 05's UI and
the grading rubric both read that shape.

## Build

### 1. New module: `ml/src/adaptation/live_adapter.py`

(create `ml/src/adaptation/__init__.py` too — mirror `ml/src/drift/__init__.py`)

```python
class LiveAdapter:
    def __init__(self, state_dir: Path,
                 get_champion, set_champion,            # callables into api.py globals
                 extract_features,                      # _extract_labrooms_features
                 capacity=5000, min_buffer=200, min_attack=30,
                 cooldown_sec=60): ...
    def observe(self, batch_records: list[dict]) -> None:
        """Per /predict batch: append pseudo-labeled samples to ring buffer.
        record = {features(52 raw), label, confidence, rule_override,
                  model_raw_label, flow_id, ts}"""
    def maybe_trigger(self) -> None:
        """Called after observe(): if monitor drift event pending + cooldown ok
        + buffer sufficient → start retrain thread."""
    def trigger(self, reason: str) -> dict:
        """Manual trigger (POST /adaptation/trigger). Returns
        {status: accepted|busy|insufficient, ...}."""
    def get_status(self) -> dict:
        """Exact /adaptation contract shape (master plan §8)."""
    def _retrain_and_gate(self, trigger_desc: str) -> None:
        """daemon thread target: build buffer DF → train LGBM candidate →
        holdout eval → 4 gates → promote+hot-swap or reject → persist."""
```

Module-level `adapt_model()` wrapping `trigger("manual")` — the team plan lists
`adapt_model()` as a Member 3 deliverable; keep the name.

**Pseudo-label resolution** (per §5.4, in `observe`):
1. `LBL::<Class>::` prefix in flow_id → that class (underscores→spaces).
2. `rule_override` true → the override `label`.
3. label == "Normal Traffic" and confidence ≥ 0.90 → Normal.
4. else → not buffered. Track `label_sources` counts for the status payload.

**Buffer**: `collections.deque(maxlen=capacity)` of
`{x: dict[8 features], y: int_label, ts, source}`.

**Retrain** (`_retrain_and_gate`):
- Snapshot buffer under lock → `pd.DataFrame` of the 8 features + `y`.
- Stratified split: train = first 75%, **validation = last 25% (chronological
  tail — never seen by candidate)**; if stratification impossible, still keep
  the chronological split and note it in the report.
- Candidate: `lgb.LGBMClassifier(n_estimators=60, max_depth=6,
  learning_rate=0.1, class_weight="balanced", random_state=42, verbose=-1)`
  fitted on a fresh `CICIDSDataPreprocessor(feature_cols=LABROOMS_DEPLOYMENT_FEATURES)`.
- Evaluate champion (current `_champion_model`+`_preprocessor`) vs candidate on
  the validation tail → `evaluate_predictions` both.
- Apply the 4 `PromotionGateConfig` gates; `emerged_class` = the most frequent
  non-Normal pseudo-label in buffer (fallback "DoS").
- **On promote**: `joblib.dump` candidate → `ml/artifacts/models/adaptive_champion_vN.joblib`,
  preprocessor → `adaptive_preprocessor_vN.joblib`; write
  `ml/artifacts/state/active_model.json`; call `set_champion(candidate,
  cand_preproc, version)` → api.py swaps globals; `model_version` increments
  v1→v2→…
- **Always** append the gate report to `adaptation_history.json` (promoted AND
  rejected — rejections are part of the story) + in-memory `history` (cap 50).
- On finish: reset the drift monitor's reference windows via its public method
  (post-adaptation baseline shift) — call whatever Phase 01 exposed; if it
  didn't expose one, add `_drift_monitor.reset_reference()` there and note it.

**Threading**: one daemon thread per trigger; `_lock` guards buffer + state;
`adaptation_in_progress` flag visible in status. All exceptions inside the
thread → log + record `last_event {type:"error"}`; never propagate.

**Boot restore**: on init, read `active_model.json` — if present and files
exist, api.py loads *those* as champion instead of the env-var paths (keep
`_load_artifacts` fallback order: `active_model.json` → env vars → defaults).
Also restore `adaptation_history.json` and buffer counts (buffer contents need
not survive restart; history must).

### 2. `ml/api.py` edits

- Instantiate `LiveAdapter` next to `_drift_monitor`.
- In `predict()`: after building `predictions`, pass the batch records (same
  dicts Phase 01 collected + `flow_id`) to `_adapter.observe()` then
  `_adapter.maybe_trigger()` — both wrapped try/except, never break inference.
- `GET /adaptation` → `_adapter.get_status()` (replaces static).
- `POST /adaptation/trigger` → `_adapter.trigger("manual_dashboard")`, 202/409/422 per §8.
- `POST /admin/reset` → if `DEMO_MODE=1` env: reset monitor + adapter + reload
  original `MODEL_PATH`/`PREPROCESSOR_PATH` artifacts via `_load_artifacts`
  (reset `active_model.json` pointer first), return contract payload; else 403.
- `GET /model-info` → add `"version": _adapter.champion_version`.
- `set_champion` must also update `_model_loaded_at`/`_model_path_used` so
  `/health` + `/model-info` tell the truth.

### 3. `server/routes/telemetry.js` — 2 new proxy routes

Mirror the existing GET-proxy pattern exactly (`AbortController`, 3 s timeout,
auth middleware) but `router.post(...)` forwarding to Flask `POST
/adaptation/trigger` and `/admin/reset`. No body needed. Match status codes
through (`res.status(resp.status).json(data)`).

## Do NOT

- Don't retrain on unlabeled flows or drop the confidence threshold — garbage labels = garbage candidate.
- Don't block `/predict` on retraining — thread or don't do it.
- Don't auto-promote without all 4 gates — that's the paper's point.
- Don't touch the ingest route or Mongo models.

## Verification

```bash
# fastest path: bypass Node, hit Flask :5001 directly
# 1. POST ~300 normal flows (Phase 02 generator at --duration or a loop of
#    predict calls) → GET /adaptation: buffer.current_size grows,
#    label_sources.high_confidence > 0

# 2. POST ~100 attack flows (LBL:: or rule-triggering shapes)
#    → buffer labeled_breakdown grows; attack_ratio ADWIN fires (P01)

# 3. GET /adaptation → adaptation_in_progress may flash true, then
#    retraining_history has a v2 entry; champion_version "v2";
#    ml/artifacts/models/adaptive_champion_v2.joblib exists;
#    ml/artifacts/state/active_model.json written;
#    adaptation_history.json contains gate report with promoted:true

# 4. GET /model-info → version "v2", model_path = adaptive_... file

# 5. POST /predict attack vector → still classified correctly by new champion

# 6. POST /adaptation/trigger twice quickly → second returns 409 busy

# 7. restart Flask → GET /adaptation still shows v2 + history (restored)

# 8. DEMO_MODE=1 restart → POST /admin/reset → version back to v1,
#    buffer empty, drift events cleared
```

If candidate gets rejected by gates on your synthetic data, that's acceptable
behavior (log it) — but tune buffer composition in verification so you see at
least one successful promotion before marking done.

## Definition of done

- [ ] Drift event auto-triggers retrain (visible in `last_event` + history)
- [ ] `POST /adaptation/trigger` works via Flask **and** via Node proxy with JWT
- [ ] Promotion persists artifacts + `active_model.json`; restart keeps v2
- [ ] `/adaptation` matches §8 contract; `/predict` never breaks (force an
      exception in the retrain path once to prove containment)
- [ ] Gates enforced: craft a deliberately-weak candidate scenario (tiny
      buffer) → rejection recorded, champion unchanged
- [ ] `adapt_model()` exists in `ml/src/adaptation/live_adapter.py`
- [ ] TRACKER.md updated
