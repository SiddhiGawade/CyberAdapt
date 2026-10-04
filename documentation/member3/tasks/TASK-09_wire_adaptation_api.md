# TASK-09 — Wire Adaptation into `ml/api.py` (live `/adaptation`, trigger, reset, hot-swap boot)

| | |
|---|---|
| **Wave** | B — **sequential** (single writer on `ml/api.py`; runs after T08) |
| **Depends on** | T04, T08 |
| **Input handoffs** | `handoffs/TASK-04_*.md` (shipped `LiveAdapter` signature), `handoffs/TASK-08_*.md` (batch_records as built, monitor instance name) |
| **Files you may touch** | `ml/api.py` only |
| **Files you must NOT touch** | `ml/src/*`, `server/`, `client/` |
| **Goal** | Instantiate the adapter, feed `batch_records`, live `/adaptation` + `POST /adaptation/trigger` + `POST /admin/reset`, `active_model.json` boot restore, `/model-info` version |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `handoffs/TASK-04_*.md` + `handoffs/TASK-08_*.md` — actual shipped names
3. `00_MASTER_PLAN.md` — §5.2, §5.5 (flow + cooldown), §8 (`/adaptation`,
   trigger, reset contracts), §9.3, §9.5
4. `ml/api.py` — globals `_champion_model`, `_preprocessor`, `_load_artifacts`,
   `predict()` (where T08 put the monitor call), static `adaptation()`,
   `model_info()`, `health()`

## Build

- Instantiate `_adapter = LiveAdapter(state_dir=STATE_DIR, ...)` next to
  `_drift_monitor`, injecting per TASK-04's shipped signature:
  `get_champion` → returns `(_champion_model, _preprocessor)`;
  `set_champion` → reassigns the globals + bumps `_model_loaded_at` /
  `_model_path_used` so `/health` + `/model-info` tell the truth;
  `extract_features` → `_extract_labrooms_features`;
  `consume_drift_event` → `_drift_monitor.consume_drift_event`;
  `reset_drift_reference` → `_drift_monitor.reset_reference`.
- In `predict()` (same guarded block after the monitor call, per §9.5):
  `_adapter.observe(batch_records)` then `_adapter.maybe_trigger()`.
- `GET /adaptation` → `return jsonify(_adapter.get_status())` (replaces static).
- `POST /adaptation/trigger` → `_adapter.trigger("manual_dashboard")` →
  map to 202/409/422 per §8.
- `POST /admin/reset` → only when env `DEMO_MODE=1` (else 403): reset monitor
  + adapter, delete `active_model.json`, reload ORIGINAL artifacts from
  `MODEL_PATH`/`PREPROCESSOR_PATH` via `_load_artifacts`, return §8 payload.
- `GET /model-info` → add `"version": _adapter.champion_version`.
- **Boot restore:** in the load path, check `active_model.json` FIRST — if
  present and its files exist, load those as champion (fallback order:
  `active_model.json` → env vars → defaults inside `_load_artifacts`).

## Do NOT

- Don't block `/predict` on retraining — the adapter's thread handles it.
- Don't touch the ingest route, Mongo models, or `classifyAndAnnotate`.
- Don't weaken the 4 gates or buffer minimums.

## Verification (Flask direct)

```bash
# DEMO_MODE=1 flask up
# 1. POST ~300 normal flows → GET /adaptation: buffer.current_size grows,
#    label_sources.high_confidence > 0
# 2. POST ~100 attack flows (LBL:: or rule shapes) → drift fires →
#    watch adaptation_in_progress flash true → retraining_history gets v2:
#    champion_version "v2", adaptive_champion_v2.joblib on disk,
#    active_model.json written, gate report promoted:true
# 3. GET /model-info → version "v2", model path = adaptive_… file
# 4. POST /predict attack vector → still correct under new champion
# 5. POST /adaptation/trigger ×2 fast → second = 409 busy
# 6. Restart Flask → GET /adaptation still v2 + history (boot restore)
# 7. POST /admin/reset → v1 restored, buffer empty, drift cleared
# 8. Force a retrain-path exception once (e.g. monkeypatch) → /predict
#    unaffected, last_event records error
```

If candidate gets rejected on synthetic data, that's valid behavior (record
it) — but tune buffer composition so you see ≥1 real promotion before `done`.

## Finish protocol (sequential — update shared files)

- `handoffs/TASK-09_wire-adaptation.md` from template.
- Append `CONTEXT.md` §C/§D (+ §A verified rows); set TRACKER.md rows.

## Definition of done

- [ ] Drift auto-triggers retrain (visible in `last_event` + history)
- [ ] `POST /adaptation/trigger` works on Flask (Node proxy was TASK-06)
- [ ] Promotion persists artifacts + `active_model.json`; restart keeps v2
- [ ] `/adaptation` matches §8; `/predict` survives a forced adapter exception
- [ ] Weak-candidate scenario → recorded rejection, champion unchanged
- [ ] `/admin/reset` gated by `DEMO_MODE=1`; `/model-info` shows version
- [ ] Handoff + CONTEXT.md + TRACKER.md updated
