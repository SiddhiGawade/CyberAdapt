# HANDOFF — TASK-04 — Live Adapter Module

> Copy this template to `handoffs/TASK-NN_<slug>.md` (same slug as your task
> file). Fill EVERY field — this file is the only thing dependent agents know
> about your work. Replace TASK-NN everywhere.

| | |
|---|---|
| **Task** | TASK-04 — Live Adapter Module (`ml/src/adaptation/live_adapter.py`) |
| **Status** | `done` |
| **Wave** | A — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- `ml/src/adaptation/__init__.py` — package marker (docstring only; mirrors the empty-pattern `ml/src/drift/__init__.py`).
- `ml/src/adaptation/live_adapter.py` — self-contained `LiveAdapter` (pseudo-label ring buffer, drift-triggered retrain thread, 4-gate promotion, hot-swap via injected `set_champion`, persistent state) + module-level `adapt_model()`.

## Files modified

- none — all dependencies are injected callables; no existing file touched.

## Interface surface shipped

Exact signatures (verbatim from `ml/src/adaptation/live_adapter.py`) — TASK-09 wires against these:

```python
class LiveAdapter:
    def __init__(
        self,
        state_dir: Path,
        get_champion: Callable[[], Tuple[Any, Any]],               # () -> (model, preprocessor)
        set_champion: Callable[[Any, Any, str], None],             # (model, preprocessor, version:str) -> None
        extract_features: Callable[[List[float]], Dict[str, float]], # (raw_52:list) -> dict[features]
        consume_drift_event: Callable[[], Optional[Dict[str, Any]]], # () -> dict | None
        reset_drift_reference: Callable[[], None],                 # () -> None
        capacity: int = 5000,
        min_buffer: int = 200,
        min_attack: int = 30,
        cooldown_sec: int = 60,
    )

    def observe(self, records: List[Dict[str, Any]]) -> None
    def maybe_trigger(self) -> None
    def trigger(self, reason: str) -> Dict[str, Any]      # {status: accepted|busy|insufficient, ...}
    def get_status(self) -> Dict[str, Any]                # exact §8 /adaptation contract
    def reset(self) -> None
    @property
    def champion_version(self) -> str                     # "v1", "v2", ...

def adapt_model(reason: str = "manual") -> Dict[str, Any]  # lazy singleton -> trigger()
```

`trigger()` return shapes:
- accepted → `{"status":"accepted","job":"candidate_retrain","buffer_size":N,"reason":reason}` (map to **202**)
- busy → `{"status":"busy","detail":...,"buffer_size":N}` (map to **409**)
- insufficient → `{"status":"insufficient","detail":...,"buffer_size":N}` (map to **422**)

`get_status()` keys (all §8 fields present): `champion_model`, `champion_version`, `adaptation_mode`, `model_loaded_at`, `adaptation_in_progress`, `online_learning_buffer{capacity,current_size,fill_percentage,label_sources{rule_override,high_confidence,flow_id_tag}}`, `retraining_history[{version,timestamp,f1_score,trigger,promoted,gates_passed}]`, `last_event{type,timestamp,detail}` (null until first event; `type` ∈ `promotion|rejection|skipped|error`).

State files written under `state_dir` (api should pass `ml/artifacts/state`):
- `adaptation_history.json` — list of gate reports (engine-identical keys + `trigger`,`buffer_size`,`train_size`,`validation_size`,`split`,`stratified`), capped at last 50.
- `active_model.json` — `{"model_path","preprocessor_path","version"}` (written on promotion; api.py reads it for boot restore).
- `adapter_state.json` — `{"version","label_sources","last_event"}` (see Deviations).
- Promoted artifacts → `<state_dir>/../models/adaptive_champion_vN.joblib` + `adaptive_preprocessor_vN.joblib` (i.e., `ml/artifacts/models/` when state_dir = `ml/artifacts/state`).

## Verification run

In-process with FAKE injected callables (dummy champion = `DummyClassifier` always-Normal + fitted `CICIDSDataPreprocessor`; no api.py). Script lived outside the repo; all state dirs under `%TEMP%` — no repo pollution.

```
$ .venv/Scripts/python.exe %TEMP%\verify_task04.py
1. observe() OK — buffer 300, label_sources: {'rule_override': 10, 'high_confidence': 250, 'flow_id_tag': 40}
2. trigger('test') -> accepted -> PROMOTED v1->v2 OK (split=stratified_75_25 fallback
   (chronological split left <2 classes in train or validation), stratified=True,
   emerged=DoS, cand_f1=1.000 vs champ=0.304)
3. boot restore OK — v2 + history + label_sources restored
4. second trigger while retrain in-flight -> busy OK
5. trigger on tiny buffer -> insufficient OK
6. maybe_trigger OK — auto fired on drift event; cooldown + insufficient skips recorded
7. champion-missing retrain -> contained, last_event type 'error' OK
8. reset() OK — buffer/label_sources/history cleared, version v1
9. adapt_model() -> {'status': 'insufficient', 'detail': '5 labeled samples < min_buffer 200', 'buffer_size': 5}

ALL CHECKS PASSED
```

Also verified on disk: `adaptation_history.json` report contains every engine key (`window_id, promoted, champion_version_before/after, champion_/candidate_macro_f1, macro_f1_delta, champion_/candidate_balanced_acc, balanced_acc_delta, emerged_class_name, candidate_emerged_class_recall, candidate_normal_fpr, gates_passed{4 bools}, timestamp`); `active_model.json` = `{"model_path","preprocessor_path","version":"v2"}` with both artifacts on disk; `set_champion` called once with `"v2"`; `reset_drift_reference` called once after the retrain.

## Outputs produced

- Buffer filled to 300/5000 (6.0%); `label_sources {high_confidence:250, flow_id_tag:40, rule_override:10}`; low-confidence Normal and malformed-raw records correctly excluded.
- Promotion v1→v2 on 300-sample buffer (candidate macro-F1 1.000 vs champion 0.304; DoS emerged-recall 1.0; all 4 gates true).
- Auto path: injected `{"detector":"ADWIN","signal":"attack_ratio"}` event → retrain fired; trigger label recorded as `"ADWIN drift alert (attack_ratio)"`.
- Skip events correctly written to `last_event` (cooldown-active, insufficient-buffer, busy) — `maybe_trigger` drops the consumed event per spec.
- Forced `get_champion() -> (None,None)` inside the retrain → contained: `last_event.type="error"`, `adaptation_in_progress` cleared, no propagation.

## Deviations from spec

1. **Extra state file `adapter_state.json`.** Task spec requires boot-restoring `label_sources` counts + version counter, but §5.2's file table only assigns `adaptation_history.json` + `active_model.json` to this module — and `active_model.json`'s shape is frozen + flagged "module only writes it" (api.py reads it for boot model selection). So the counters persist in `adapter_state.json` (`{"version","label_sources","last_event"}`); version falls back to last promoted entry in `adaptation_history.json` if the state file is missing.
2. **`PromotionGateConfig` imported from `adaptive_engine.py`** rather than re-declared — single source of truth for the 4 thresholds (import verified clean; no api/monitor imports).
3. **Stratified fallback split.** Spec: chronological 75/25, "stratify if possible, else note it in the report". Implemented: chrono split is tried first; if it leaves <2 classes in train or validation (typical demo: normals then attack campaign → train tail all-Normal), falls back to `train_test_split(stratify=, test_size=0.25)` and records `split`/`stratified` in the report; if even stratify is impossible, keeps chrono and notes it. Validation is always disjoint from candidate's fit.
4. **`reset_drift_reference()` called only on completed retrains** (promoted OR rejected), not on exception paths — if the retrain errors, the drift baseline is left alone so persistent drift can re-fire.
5. `model_loaded_at` in `get_status()` reports when the *current champion version became active* (boot for v1, promotion time after hot-swap) — adapter has no access to api's `_model_loaded_at`; api may overwrite this key at render time if it prefers its own timestamp.

## Handoff notes for dependent tasks

- For TASK-09: inject per the constructor docstring (exact callable order: `get_champion, set_champion, extract_features, consume_drift_event, reset_drift_reference`). `state_dir` should be `ml/artifacts/state` (adapter `mkdir`s it). Map `trigger()` statuses → 202/409/422 per §8. `observe(batch_records)` then `maybe_trigger()` in the guarded §9.5 block. For `/admin/reset`: `adapter.reset()` does NOT delete `active_model.json` — api deletes it + reloads original artifacts (per your task file). `get_status()["model_loaded_at"]` is adapter-side "champion-since"; feel free to replace with `_model_loaded_at` when serializing.
- For TASK-05: pseudo-label rule implemented in `LiveAdapter._resolve_pseudo_label` — copy its semantics exactly (LBL:: tag → rule_override → Normal@conf≥0.90 → excluded; unparseable LBL tag → excluded entirely). It reads `adaptation_history.json` for `promoted:true` + `timestamp` — both keys are present in every report.
- For TASK-01 (`LiveDriftMonitor`): adapter calls `consume_drift_event()` expecting `{"detector","signal",...}` — trigger description renders as `f"{detector} drift alert ({signal})"` (e.g. "ADWIN drift alert (attack_ratio)") matching the §8 example; include both keys in your event dict.
- The singleton behind `adapt_model()` uses no-op callables — fine for standalone smoke but api must use its own injected instance (documented in module docstring).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `LiveAdapter` shipped at `ml/src/adaptation/live_adapter.py`; §9.3 interface conforms exactly; all callables injected, zero api/monitor imports.
- CONTEXT fact: adapter persists a third state file `adapter_state.json` (`version`+`label_sources`+`last_event`) alongside `adaptation_history.json`/`active_model.json` — needed because spec required restoring counters §5.2 didn't allocate a file for.
- CONTEXT fact: retrain split = chronological 75/25 with stratified fallback when chrono leaves <2 classes in either side (recorded in report `split`/`stratified` fields).
- CONTEXT deviation: `adapter_state.json` extra file (above) + `model_loaded_at` = "current-champion-since" timestamp, not api's `_model_loaded_at`.
- Open issue: none.
- TRACKER row status: `done` — "LiveAdapter shipped + verified: promotion v1→v2, gates/artifacts/active_model.json, busy/insufficient/cooldown/error paths all exercised in-process"
