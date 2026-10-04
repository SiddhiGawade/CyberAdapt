# HANDOFF — TASK-09 — Wire Adaptation into `ml/api.py` (live `/adaptation`, trigger, reset, hot-swap boot)

> Copy this template to `handoffs/TASK-NN_<slug>.md` (same slug as your task
> file). Fill EVERY field — this file is the only thing dependent agents know
> about your work. Replace TASK-NN everywhere.

| | |
|---|---|
| **Task** | TASK-09 — Wire Adaptation into `ml/api.py` (live `/adaptation`, trigger, reset, hot-swap boot) |
| **Status** | `done` |
| **Wave** | B — sequential |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-04 (`LiveAdapter` signature + trigger/status map + state files), TASK-08 (`_drift_monitor` instance, `batch_records`, §9.5 block location) |

---

## Files created

- none (temporary `ml/scripts/check_adaptation_inproc.py` + `check_adaptation_api.py` were used for verification then **deleted** — recreate from the Verification section below if needed; T08 precedent).

## Files modified

- `ml/api.py` — `import json` + `LiveAdapter` import; `_resolve_boot_artifacts()` helper (active_model.json → env → defaults) called by `_load_artifacts()`; `_get_champion`/`_set_champion` hooks + module-level `_adapter` singleton next to `_drift_monitor`; `predict()` guarded block extended with `observe()` + `maybe_trigger()`; static `adaptation()` body replaced with `_adapter.get_status()`; new `POST /adaptation/trigger` (202/409/422) + `POST /admin/reset` (DEMO_MODE=1 gate); `model_info()` gains `"version"`; module docstring endpoint list updated.

## Interface surface shipped

```python
# ml/api.py — module level, after _drift_monitor
def _get_champion() -> Tuple[Any, Any]:            # () -> (_champion_model, _preprocessor)
def _set_champion(model, preprocessor, version):   # reassigns globals + bumps
                                                   # _model_loaded_at/_model_path_used
                                                   # (path read back from active_model.json)
_adapter = LiveAdapter(
    state_dir=STATE_DIR,
    get_champion=_get_champion,
    set_champion=_set_champion,
    extract_features=_extract_labrooms_features,
    consume_drift_event=_drift_monitor.consume_drift_event,
    reset_drift_reference=_drift_monitor.reset_reference,
)

# inside predict() — same guarded try/except as the monitor (§9.5):
_drift_monitor.process_batch(batch_records)
_adapter.observe(batch_records)
_adapter.maybe_trigger()

# GET /adaptation  → jsonify(_adapter.get_status()) with model_loaded_at
#                    overwritten by api's own _model_loaded_at (T04-sanctioned)
# POST /adaptation/trigger → _adapter.trigger("manual_dashboard") →
#                    {accepted:202, busy:409, else:422}
# POST /admin/reset → 403 unless env DEMO_MODE=1; then deletes
#                    STATE_DIR/"active_model.json", _drift_monitor.reset(),
#                    _adapter.reset(), _load_artifacts() →
#                    {"status":"reset","cleared":[...]}
# GET /model-info  → adds "version": _adapter.champion_version

# Boot load order (_resolve_boot_artifacts, called by _load_artifacts):
#   STATE_DIR/"active_model.json" (if both files exist on disk)
#   → MODEL_PATH/PREPROCESSOR_PATH env vars → built-in defaults
```

## Verification run

Flask: `MODEL_PATH=ml/artifacts/models/champion_model.joblib PREPROCESSOR_PATH=ml/artifacts/models/preprocessor.joblib DEMO_MODE=1 PORT=5001 .venv/Scripts/python.exe -m ml.api` → `:5001`. mongod/Node NOT running — Flask-direct per spec. All requests to `http://127.0.0.1:5001` (never `localhost` — see CONTEXT §C).

**In-process (temp script, test_client + temp-state-dir adapters):**
```
$ .venv/Scripts/python.exe ml/scripts/check_adaptation_inproc.py   (deleted after)
[reset-gate] POST /admin/reset (DEMO_MODE unset) -> 403 {'error': 'Forbidden — requires DEMO_MODE=1'}
[predict] baseline -> 200 label=Normal Traffic conf=0.9997
[guard] /predict with observe() raising -> 200 (predict unaffected)
[error-path] trigger -> accepted (buffer=240)
[error-path] last_event = {'type': 'error', 'detail': 'retrain failed: RuntimeError:
             get_champion() returned no model/preprocessor — cannot evaluate candidate against champion'}
[guard] /predict after retrain error -> 200
[insufficient] empty-buffer trigger -> {'status': 'insufficient',
             'detail': '0 labeled samples < min_buffer 200', 'buffer_size': 0}
[busy] trigger#1 -> accepted | trigger#2 (immediate) -> busy candidate retrain already in progress
[rejection] last_event = {'type': 'rejection', 'detail': 'Candidate rejected — gates failed:
             gate_macro_f1, gate_bal_acc, gate_emerged_recall, gate_normal_fpr
             (macro_f1_delta -0.3584, normal_fpr 0.0930) [Manual trigger (rejection_test)]'}
[rejection] report: promoted=False f1=0.6416 gates={all False}
[rejection] champion_version still v1
ALL IN-PROCESS CHECKS PASSED
```

**Live run — phase1 (baseline → drift → AUTO retrain → promotion → trigger×2):**
```
$ .venv/Scripts/python.exe ml/scripts/check_adaptation_api.py phase1   (deleted after)
[baseline] version=v1 in_progress=False buffer=0/5000 label_sources all-0 history=0
[after-550-normal] buffer=550/5000 (11.0%) label_sources={'high_confidence': 550}
[baseline-drift] status=active drift_state=stable samples=550
[attack batch 1] drift_state=warning events=0 buffer=600 version=v1
[attack batch 2] drift_state=drift events=1 in_progress=True buffer=650 version=v1
  drift event: {'detector':'PSI','signal':'feature_psi','samples_processed':650,
    'detail':'attack_ratio 1.00; PSI drifted on 2 slots (Total Bwd Bytes, Flow Bytes/s)'}
[attack batch 3] drift_state=drift in_progress=True buffer=700 version=v1
[post-burst] version=v2 last_event={'type':'promotion','detail':'Candidate promoted
  v1 -> v2 (macro_f1 0.4585 -> 1.0000, DoS recall 1.0000) [PSI drift alert (feature_psi)]'}
[post-burst] history[-1]: version=v2 promoted=True f1=1.0
  trigger='PSI drift alert (feature_psi)' gates={all True}
[disk] active_model.json = {model_path: ...\adaptive_champion_v2.joblib,
       preprocessor_path: ...\adaptive_preprocessor_v2.joblib, version: 'v2'}
[disk] adaptation_history.json + adapter_state.json written;
       adaptive_champion_v2.joblib (40,244 B) + adaptive_preprocessor_v2.joblib on disk
[triggerx2] #1 -> 202 accepted | #2 -> 409 busy 'candidate retrain already in progress'
[post-trigger] version=v3 last_event=promotion        (manual retrain promoted v2→v3)
[model-info] version=v3 model_type=LGBMClassifier path=...\adaptive_champion_v3.joblib
[predict-v3] attack->DoS normal->Normal Traffic
PHASE1 OK
```

**Live run — phase2 (restart → boot restore → admin reset):**
```
$ kill Flask; restart with same env; .venv/Scripts/python.exe ml/scripts/check_adaptation_api.py phase2
(boot log) LiveAdapter restored: 2 history entries, version v3,
           label_sources {'high_confidence': 551, 'flow_id_tag': 151}
(boot log) Boot-restoring promoted champion v3 via active_model.json → adaptive_champion_v3.joblib
[post-restart] version=v3 buffer=0 label_sources restored history=2
[model-info] version=v3 path=...\adaptive_champion_v3.joblib
[reset] POST /admin/reset -> 200 {'cleared': ['active_model','drift_state',
        'buffer','history','model_artifacts'], 'status': 'reset'}
[post-reset] version=v1 buffer=0 label_sources all-0 history=0
[post-reset] drift: samples=0 state=stable events=0
[post-reset] model-info version=v1 path=ml\artifacts\models\champion_model.joblib
PHASE2 OK
```

## Outputs produced

- **Drift → auto-retrain → promotion verified live:** PSI drift alert (`feature_psi`) fired on attack batch 2 (550-flow baseline), `maybe_trigger()` consumed the event inside the same `/predict` call, retrain ran in the daemon thread while predictions continued, candidate promoted **v1→v2** (champion macro-F1 0.4585 → candidate 1.0000, DoS recall 1.0, all 4 gates true). Second (manual) retrain promoted v2→v3.
- **`POST /adaptation/trigger`:** 202 `{"status":"accepted","job":"candidate_retrain",...}`, immediate second → 409 `{"status":"busy",...}`, in-process empty-buffer → `insufficient` (→422 mapping).
- **Boot restore:** after restart, `GET /adaptation` → v3 + 2 history entries + restored label_sources; `GET /model-info` → `version=v3`, path=`adaptive_champion_v3.joblib`. Boot log shows `active_model.json` took precedence over env vars.
- **`POST /admin/reset`:** 200 `{"status":"reset","cleared":["active_model","drift_state","buffer","history","model_artifacts"]}` → v1, buffer 0, drift counters 0, original `champion_model.joblib` reloaded. Without `DEMO_MODE=1` → 403.
- **Robustness:** forced `observe()` exception → `/predict` still 200; forced retrain `get_champion→(None,None)` → contained, `last_event.type="error"`; gated rejection vs perfect champion → `last_event.type="rejection"`, report `promoted:false`, champion unchanged.

## Deviations from spec

1. **`/adaptation` overwrites `model_loaded_at` with api's own `_model_loaded_at`** — explicitly sanctioned by T04's handoff ("api may overwrite this key at render time"); keeps `/health` + `/model-info` + `/adaptation` consistent (adapter's own value = "current-champion-since").
2. **`/admin/reset` `cleared` list reports actual actions** — `["active_model","drift_state","buffer","history","model_artifacts"]`, not §8's example list. `"eval_window"` is commented for TASK-10 to add when it wires `_evaluator.reset()` (no evaluator exists in api.py yet).
3. **`_set_champion` reads `active_model.json` for `_model_path_used`** — the adapter writes the pointer file immediately before invoking the hook, so the real on-disk path is recoverable; falls back to `adaptive_champion_vN (in-memory)` if unreadable.
4. **Reset while a retrain is in-flight is not guarded** — `LiveAdapter.reset()` doesn't check `_retrain_in_progress`; a finishing retrain could re-promote after reset. Accepted race (demo resets happen at narrative start); noted for T12/T17.
5. First live attempt showed manual trigger can race ahead of the auto path when the monitor is still `warming_up` — not a code deviation, but see note below on the ≥500-sample baseline requirement.

## Handoff notes for dependent tasks

- For **TASK-10**: `batch_records` is built for you; add `_evaluator.record(batch_records, latency_ms)` **inside the same try/except** after `_adapter.maybe_trigger()` (comment marks §9.5 order). Add `_evaluator.reset()` + `"eval_window"` to `/admin/reset`'s `cleared` (marked `# TASK-10:`).
- For **TASK-12/T17 (demo choreography)**: the drift detector needs **≥500 baseline samples** (exit `warming_up`) before attack traffic will latch `drift` — a ~300-flow baseline only reached `warning` and the auto path never fired. Also the drift event is consumed by `maybe_trigger()` inside the SAME `/predict` call that fires it — promotion lands within ~1 s of the batch. Manual `POST /adaptation/trigger` on a well-labeled buffer reliably produces *another* promotion (v2→v3 observed): the macro-F1 gate is `delta ≥ -0.01`, so a same-quality candidate still passes. Plan version numbering accordingly.
- For **TASK-15 (FORCE button)**: `POST /adaptation/trigger` → literal passthrough of adapter statuses: 202 `accepted`, 409 `busy`, 422 `insufficient` (+`detail` string on the non-202 bodies). `last_event.type` ∈ `promotion|rejection|skipped|error` drives the UI banner.
- For **TASK-16**: `/adaptation`'s `model_loaded_at` is api's `_model_loaded_at` (bumped on every hot-swap), not the adapter's `_champion_since` — same semantics, one source.
- For **everyone**: `_set_champion` bumps `_model_loaded_at`/`_model_path_used`, so `/health`, `/model-info` and `/adaptation` all agree post-promotion. `adapter.reset()` does NOT delete `active_model.json` — `/admin/reset` deletes it BEFORE `_load_artifacts()` so the original env-var artifacts come back.
- Known edge: `/admin/reset` during an in-flight retrain can be re-promoted-over (deviation 4) — if it ever shows up, re-run reset; no persistent harm.
- Flask is **left running** on :5001 with `DEMO_MODE=1`, post-reset clean state (v1, empty buffer, drift 0) — same end-state as T08 for T10. Stale `adaptive_*` joblibs and the temp `ml/scripts/` dir were removed.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `ml/api.py` ships `_adapter = LiveAdapter(state_dir=STATE_DIR, …)` with all 5 injected callables; `predict()` runs `observe()`+`maybe_trigger()` in the §9.5 guarded block; `GET /adaptation`=live `get_status()` (model_loaded_at = api's `_model_loaded_at`); `POST /adaptation/trigger`→202/409/422; `POST /admin/reset`→DEMO_MODE=1 gate, deletes active_model.json → resets monitor+adapter → reloads original artifacts; `/model-info` gains `version`; boot order = `active_model.json` → env → defaults.
- CONTEXT fact: drift auto-trigger verified live E2E — PSI event consumed mid-`/predict`, promotion v1→v2 (macro_F1 0.46→1.0), restart restored v3 via `active_model.json` (env vars ignored while pointer exists); manual trigger on labeled buffer → v3 (delta-gate ≥-0.01 passes same-quality candidates — repeat retrains keep bumping versions).
- CONTEXT fact: drift needs **≥500 baseline samples** (exit `warming_up`) before attack traffic latches `drift`; ~300 only reaches `warning`.
- CONTEXT deviation: `/admin/reset` `cleared` lists real actions (incl. `active_model`,`model_artifacts`); `"eval_window"` deferred to T10; reset not guarded against in-flight retrains.
- Open issue: none.
- TRACKER row status: `done` — "Live `/adaptation`+trigger+reset verified E2E: PSI drift auto-fired retrain → v1→v2 promotion (all gates), 202/409/422, boot-restore kept v3 across restart, `/admin/reset` restored v1; forced error/rejection paths contained"
