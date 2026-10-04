# HANDOFF — TASK-10 — Wire Evaluation into `ml/api.py` (live `/evaluation`)

> Filled per `handoffs/_TEMPLATE.md`. Sequential wave — CONTEXT.md/TRACKER.md
> updated by this agent.

| | |
|---|---|
| **Task** | TASK-10 — Wire Evaluation into `ml/api.py` (live `/evaluation`) |
| **Status** | `done` |
| **Wave** | B — sequential |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-05 (`LiveEvaluator` signature + `get_metrics()` shape + metrics.py `logger` bug), TASK-09 (predict() §9.5 block layout, `# TASK-10:` marker in `/admin/reset`) |

---

## Files created

- none (verification driver `check_evaluation_api.py` lives in `%TEMP%`, repo untouched — T09 precedent; recreated from the Verification section below if needed)

## Files modified

- `ml/api.py` — `from ml.src.evaluation.live_evaluator import LiveEvaluator`; module-level `_evaluator = LiveEvaluator(STATE_DIR / "eval_window.jsonl")` beside `_adapter`; `predict()` guarded try/except extended with `_evaluator.record(batch_records, latency_ms)` as the 4th §9.5 step; static `evaluation()` body replaced with `jsonify(_evaluator.get_metrics())`; `/admin/reset` step 4 calls `_evaluator.reset()` + appends `"eval_window"` to `cleared`; module docstring endpoint list updated. No other files touched.

## Interface surface shipped

```python
# ml/api.py — module level, after _adapter (line ~212)
_evaluator = LiveEvaluator(STATE_DIR / "eval_window.jsonl")

# inside predict() — SAME guarded try/except, last step (§9.5 order):
try:
    _drift_monitor.process_batch(batch_records)
    _adapter.observe(batch_records)
    _adapter.maybe_trigger()
    _evaluator.record(batch_records, latency_ms)   # T10
except Exception:
    logger.exception("Drift monitor/adapter/evaluator processing failed — /predict unaffected")

# GET /evaluation  → jsonify(_evaluator.get_metrics())
#                    ("dataset": "Live Labrooms stream (pseudo-labeled)",
#                     insufficient_data only when <30 labeled rows)
# POST /admin/reset → cleared now ends with "eval_window"
```

## Verification run

Flask started fresh (was NOT running — T09's instance had died with the session):
`MODEL_PATH=ml/artifacts/models/champion_model.joblib PREPROCESSOR_PATH=ml/artifacts/models/preprocessor.joblib DEMO_MODE=1 PORT=5001 .venv/Scripts/python.exe -m ml.api` → `:5001`. All requests to `http://127.0.0.1:5001` (never `localhost`). Driver imports `build_normal_flow`/`make_flow_id` from `sensor/normal_traffic.py` + `gen_*` from `sensor/attack_campaign.py` (all LBL-tagged → ground-truth rows).

**Cold start — empty window:**
```
$ curl http://127.0.0.1:5001/evaluation
→ "dataset": "Live Labrooms stream (pseudo-labeled)", "insufficient_data": true,
  "overall_metrics": all 0.0, 7×7 zero confusion_matrix, window.size=0
```

**Drive phase (200 normal → +350 normal → 150 attack → wait promotion → +100 mixed):**
```
$ .venv/Scripts/python.exe %TEMP%\check_evaluation_api.py drive
[after-200-normal] size=200 insuff=False acc=1.000 f1=1.000 p95=71.89ms cm_row0 diag=200 off=0
        per_class support={'Normal Traffic': 200}
        pre_post: pre={'f1_macro': 1.0, 'samples': 200} post=None last=None
[warm] drift status=active samples=550 state=stable
[attack] drift_state=stable events=0
[after-150-attack] size=500 insuff=False acc=1.000 f1=1.000 p95=84.54ms cm_row0 diag=350 off=0
        per_class support={'Brute Force': 37, 'DoS': 37, 'Normal Traffic': 350, 'Web Attacks': 76}
        pre_post: pre={...'samples': 300} post={...'samples': 200} last=2026-10-04T06:32:24Z
        attack rows support total=150
[pre-promo] version=v2 in_progress=None
[promo] promoted=True version=v2 last_event={'type': 'promotion',
        'detail': 'Candidate promoted v1 -> v2 (macro_f1 0.2204 -> 1.0000,
        Web Attacks recall 1.0000) [PSI drift alert (feature_psi)]',
        'timestamp': '2026-10-04T06:32:24Z'}
[post-promotion] size=500 acc=1.000 cm_row0 diag=300 off=0
        per_class support={'Brute Force': 51, 'DoS': 53, 'Normal Traffic': 300, 'Web Attacks': 96}
        pre_post: pre={'f1_macro': 1.0, 'samples': 200} post={'f1_macro': 1.0, 'samples': 300}
                  last=2026-10-04T06:32:24Z
[latency] batches=16 predict_ms avg=43.25 max=100.10 | wall avg=62.66 max=131.46 |
          guarded-block+http delta avg=19.41 max=55.30
OK
```
(The PSI drift event fired and was consumed *inside* the same `/predict` batch
that carried it — promotion v1→v2 landed before the next snapshot, so
`[pre-promo]` already shows v2. `drift_state=stable` at the attack snapshot is
`reset_reference()` having already run post-promotion.)

**Evaluator's own cost (in-process, 50-rec batch at full 500-row window):**
```
record() 50 recs at full window: avg=2.56ms p50=2.57 max=2.63
```

**Restart persistence:**
```
$ kill Flask; restart same env
(boot log) LiveEvaluator: restored 500 labeled row(s) from ...\state\eval_window.jsonl
(boot log) LiveAdapter restored: 1 history entries, version v2, label_sources {'flow_id_tag': 800}
(boot log) Boot-restoring promoted champion v2 via active_model.json → adaptive_champion_v2.joblib
$ .venv/Scripts/python.exe %TEMP%\check_evaluation_api.py post-restart
[post-restart] size=500 insuff=False acc=1.000 f1=1.000 p95=0.00ms cm_row0 diag=300 off=0
        per_class support={'Brute Force': 51, 'DoS': 53, 'Normal Traffic': 300, 'Web Attacks': 96}
        pre_post: pre={'samples': 200} post={'samples': 300} last=2026-10-04T06:32:24Z
        restart-check: size=500 last=2026-10-04T06:32:24Z
OK
$ curl http://127.0.0.1:5001/model-info → version: v2  path: ...\adaptive_champion_v2.joblib
```
(Note `p95=0.00` — latency samples are an in-memory deque, not in the jsonl
rows; they re-accumulate after restart. Window rows/metrics/split all intact.)

**DEMO_MODE reset:**
```
$ .venv/Scripts/python.exe %TEMP%\check_evaluation_api.py reset
[reset] -> {'cleared': ['active_model', 'drift_state', 'buffer', 'history',
        'model_artifacts', 'eval_window'], 'status': 'reset'}
[post-reset] size=0 insuff=True acc=0.000 f1=0.000
        per_class support={}
        pre_post: pre={'f1_macro': 0.0, 'samples': 0} post=None last=None
OK
$ ls ml/artifacts/state → adaptation_history.json adapter_state.json drift_state.json
   (eval_window.jsonl deleted)
$ POST /predict (1 LBL normal flow) → 200 Normal Traffic conf=0.9968,
   window.size=1 (recording resumes immediately post-reset)
```

## Outputs produced

- **Live `/evaluation` per §8:** accuracy/f1 move with traffic (1.000 on clean LBL-tagged mix), confusion matrix diagonal-heavy (row0 diag 300, off 0 at final snapshot), `per_class_metrics` gained attack rows (DoS 53 / Brute Force 51 / Web Attacks 96 supports), `class_names` = TARGET_CLASSES.
- **Real promotion → pre/post split:** PSI drift auto-triggered retrain during the attack burst → **v1→v2** (champ macro_f1 0.2204 → cand 1.0000, all gates); `pre_post_adaptation.last_adaptation`=`2026-10-04T06:32:24Z`, pre=200 samples, post=300 samples (window-capped).
- **Persistence:** `eval_window.jsonl` restored 500 rows on boot; metrics + split identical post-restart; v2 champion restored via `active_model.json`.
- **`/admin/reset`:** `cleared` = `["active_model","drift_state","buffer","history","model_artifacts","eval_window"]` → size=0, `insufficient_data:true`, file deleted, model back to v1 originals.
- **Latency budget:** `_evaluator.record()` ≈2.6 ms per 50-record batch at a full window (measured in-process); `/predict` unaffected by construction (same guarded try/except).

## Deviations from spec

1. **`insufficient_data` semantics on the contract skeleton** — none new; inherited T05's shipped behaviour (key only present when true). The pre-T10 static `/evaluation` payload (hardcoded dataset name, `roc_auc`, no window/pre_post) is fully replaced — old keys `roc_auc`/`"dataset": "Labrooms Application-Layer (10 Populated Features)"` are gone; per T16 this is the intended §8 swap.
2. **`latency_p95_ms` resets to 0.0 on restart** — persisted rows carry no latency field (T05's row schema); latency deque is in-memory only. Contract-tolerated (metrics re-accumulate); noted for T16 so the UI doesn't alarm on a transient 0.
3. **No `y_prob` anywhere** — as required (metrics.py:~108 latent `logger` NameError stays dormant).

## Handoff notes for dependent tasks

- For **TASK-13 (verify evaluation E2E)**: a clean drift→promotion cycle is now cheap to reproduce — ~550 LBL normal then a ~150-flow LBL attack burst promotes within seconds (observed v1→v2 here, v1→v2 and v2→v3 in T09). `GET /evaluation` costs ~40 ms at a full window (per-request compute — keep the UI poll interval ≥2 s).
- For **TASK-16 (`Evaluation.jsx`)**: live keys are exactly the §8 shape — `window{size,capacity,since}`, `overall_metrics{accuracy,precision_macro,recall_macro,f1_macro,latency_p95_ms}`, `per_class_metrics{cls:{precision,recall,f1,support}}`, `confusion_matrix` (7×7 ints), `class_names`, `pre_post_adaptation{pre,post,last_adaptation}`. `insufficient_data` appears ONLY when <30 labeled rows — render the graceful empty state. `post` is `null` until a real promotion lands. After `/admin/reset`, `latency_p95_ms` also reads 0.0 until new traffic arrives.
- For **TASK-12/T17 (demo choreography)**: evaluation rows only accumulate for pseudo-labeled flows — untagged, un-overridden, sub-0.90-confidence flows are silently dropped by §5.4. `normal_traffic.py --lbl-tag` / `attack_campaign.py` traffic keeps the window full; unlabeled traffic does NOT shrink it (rows just aren't added).
- For **everyone**: `/admin/reset` now also deletes `eval_window.jsonl` and clears the evaluator — full cleared list `["active_model","drift_state","buffer","history","model_artifacts","eval_window"]`. Flask is **left running** on :5001 (DEMO_MODE=1) in post-reset clean state: v1, empty buffer/history/window, drift counters 0 — same hand-off state T09 left.
- Known edge (unchanged from T09): `/admin/reset` during an in-flight retrain can be re-promoted-over; re-run reset if it ever shows up.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `ml/api.py` ships `_evaluator = LiveEvaluator(STATE_DIR/"eval_window.jsonl")`; `predict()` §9.5 block now ends `_evaluator.record(batch_records, latency_ms)`; `GET /evaluation` = live `get_metrics()`; `/admin/reset` step 4 does `_evaluator.reset()` + `"eval_window"` in `cleared`.
- CONTEXT fact: `/evaluation` verified live E2E — window grows on labeled traffic only, acc 1.000 on clean LBL mix, attack rows appear, real PSI promotion v1→v2 populated pre/post split (pre 200 / post 300), 500 rows survived restart, reset → `insufficient_data`.
- CONTEXT fact: `eval_window.jsonl` rows carry NO latency field → `latency_p95_ms` returns 0.0 after a restart until new labeled traffic arrives (in-memory deque).
- CONTEXT fact: `GET /evaluation` ≈40 ms at full 500-row window (compute per request); `_evaluator.record()` ≈2.6 ms/50-rec batch — /predict overhead budget fine.
- CONTEXT deviation: static `/evaluation` payload fully replaced — `roc_auc` key and old dataset string are gone (intended §8 swap; T16 build against live shape).
- Open issue: none.
- TRACKER row status: `done` — "Live `/evaluation` verified E2E: labeled-only window growth, attack rows, real PSI promotion v1→v2 populated pre/post split, 500 rows survived restart, `/admin/reset` clears `eval_window`; record() ≈2.6 ms/batch".
