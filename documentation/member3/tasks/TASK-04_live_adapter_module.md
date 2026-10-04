# TASK-04 — Live Adapter Module (`ml/src/adaptation/live_adapter.py`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T01–T07) |
| **Depends on** | none — code against the frozen §9.3 interface (dependencies are injected callables, NOT imports of the monitor or api.py) |
| **Input handoffs** | none |
| **Files you may touch** | `ml/src/adaptation/__init__.py` (new), `ml/src/adaptation/live_adapter.py` (new) only |
| **Files you must NOT touch** | `ml/api.py`, `ml/src/models/adaptive_engine.py`, everything else — wiring is TASK-09 |
| **Goal** | Self-contained `LiveAdapter`: pseudo-label buffer, drift-triggered retrain thread, 4-gate promotion, hot-swap via injected `set_champion`, persistent state |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `00_MASTER_PLAN.md` — §5.2 (state files), §5.4 (pseudo-labels), §5.5 (adaptation flow), §8 (`/adaptation` + trigger contracts), §9.1/§9.3 (frozen interface)
3. `ml/src/models/adaptive_engine.py` — `AdaptiveModelManager`, `PromotionGateConfig`, gate report shape (replicate semantics, don't rewrite)
4. `ml/src/features/preprocessing.py` — `CICIDSDataPreprocessor`
5. `ml/src/features/feature_contract.py` — `LABROOMS_DEPLOYMENT_FEATURES` (8 names)
6. `ml/src/evaluation/metrics.py` — `evaluate_predictions()`
7. `ml/src/drift/__init__.py` — mirror its pattern for `ml/src/adaptation/__init__.py`

## Key reality check (from the v1 plan — still binding)

`AdaptiveModelManager` was written for notebook 03 (52-feature CICIDS frames).
Live buffer rows are **8-name Labrooms dicts** + pseudo-labels → **option (a)**:
replicate the manager's *gate logic* (`PromotionGateConfig`, 4 gates, report
shape) inside `LiveAdapter` operating on `LABROOMS_DEPLOYMENT_FEATURES` frames;
reuse `evaluate_predictions()` for both champion and candidate eval. The gate
report shape must stay identical to `adaptive_engine.py` (`window_id`,
`promoted`, `champion_*`, `candidate_*`, `gates_passed`, timestamps) — the UI
and grading rubric read that shape.

## Build — `ml/src/adaptation/live_adapter.py`

Class + module function per §9.3 **exactly**. Constructor takes injected
callables: `get_champion`, `set_champion`, `extract_features`,
`consume_drift_event`, `reset_drift_reference` — so this module never imports
`api.py` or `live_monitor.py` (that's what makes it parallel-safe).

**`observe(records)`** — pseudo-label resolution per §5.4 in order:
`LBL::<Class>::` flow_id → rule_override label → `Normal Traffic` @ conf ≥0.90
→ else not buffered. Track `label_sources` counts (`rule_override`,
`high_confidence`, `flow_id_tag`) for the status payload.
Buffer: `deque(maxlen=capacity)` of `{x: dict[8 features], y: int_label, ts, source}`.

**`maybe_trigger()`** — if `consume_drift_event()` returns an event AND
cooldown elapsed AND buffer sufficient (≥`min_buffer` labeled, ≥2 classes,
≥`min_attack` non-Normal) → start retrain thread. Else record a
`skipped — insufficient buffer`/cooldown event in `last_event` where relevant.

**`trigger(reason)`** — manual trigger (POST /adaptation/trigger path):
returns `{status: accepted|busy|insufficient, ...}`; manual ignores cooldown
but respects the one-retrain lock and buffer minimums.

**`_retrain_and_gate(trigger_desc)`** — daemon thread:
- Snapshot buffer under lock → `pd.DataFrame` of 8 features + `y`.
- Chronological split: train = first 75%, **validation = last 25%** (never
  seen by candidate); stratify if possible, else note it in the report.
- Candidate: `lgb.LGBMClassifier(n_estimators=60, max_depth=6,
  learning_rate=0.1, class_weight="balanced", random_state=42, verbose=-1)`
  on a fresh `CICIDSDataPreprocessor(feature_cols=LABROOMS_DEPLOYMENT_FEATURES)`.
- Eval champion (from `get_champion()`) AND candidate on validation tail →
  `evaluate_predictions` both → apply 4 gates; `emerged_class` = most frequent
  non-Normal pseudo-label in buffer (fallback `"DoS"`).
- **On promote:** `joblib.dump` → `ml/artifacts/models/adaptive_champion_vN.joblib`
  + `adaptive_preprocessor_vN.joblib`; write `ml/artifacts/state/active_model.json`
  `{"model_path","preprocessor_path","version"}`; call
  `set_champion(candidate, cand_preproc, "vN")`; version increments v1→v2→…
- **Always** append gate report to `adaptation_history.json` (promoted AND
  rejected — rejections are part of the story) + in-memory history (cap 50),
  update `last_event`.
- On finish: call `reset_drift_reference()` (post-adaptation baseline shift).
- All thread exceptions → log + `last_event {type:"error"}`; never propagate.

**`get_status()`** — exact §8 `/adaptation` contract
(`adaptation_in_progress`, `online_learning_buffer{capacity,current_size,
fill_percentage,label_sources}`, `retraining_history`, `last_event`,
`champion_version`).

**Boot state:** on init, restore `adaptation_history.json` + `label_sources`
counts + version counter (buffer contents need not survive restart). Note:
reading `active_model.json` to pick the boot model is **api.py's job in
TASK-09** — your module only writes it.

**Threading:** `_lock` guards buffer + state; one daemon retrain thread;
`adaptation_in_progress` flag in status.

Module-level `adapt_model(reason="manual")` — team deliverable name; wraps a
lazy singleton's `trigger`. Document in the module docstring that TASK-09
should prefer constructor injection on the api-owned instance.

## Do NOT

- Don't touch `ml/api.py` or any existing file.
- Don't retrain on unlabeled flows / drop the confidence threshold.
- Don't auto-promote without all 4 gates.
- Don't import `live_monitor` or `api` — injected callables only.

## Verification (in-process — api.py not wired yet)

```bash
.venv\Scripts\activate
python -c "
# Instantiate LiveAdapter with FAKE injected callables (tiny stub champion =
# joblib-loaded real preprocessor+model if handy, else a dummy sklearn clf)
# feed synthetic records (§9.1): ~250 high-conf Normals + ~40 LBL::DoS rows
# → observe() grows buffer + label_sources
# → trigger('test') → accepted → wait for thread → retraining_history has a
#   gate report; adaptation_history.json on disk; promoted→ set_champion
#   called with v2 + active_model.json written
# → second immediate trigger → busy
# → fresh adapter on minuscule buffer → trigger → insufficient
# → reset() clears"
```

## Finish protocol

- `handoffs/TASK-04_live-adapter.md` from template — exact shipped signatures
  under "Interface surface shipped" (TASK-09 wires against them).
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] `LiveAdapter` + `adapt_model()` match §9.3 exactly
- [ ] Pseudo-label order per §5.4; `label_sources` counted
- [ ] Promotion writes artifacts + `active_model.json` + calls `set_champion`
- [ ] Rejections + skipped events recorded in history/`last_event`
- [ ] `busy`/`insufficient` paths verified; thread exceptions contained
- [ ] `get_status()` returns every §8 contract field
- [ ] Handoff written with interface surface + verification output
