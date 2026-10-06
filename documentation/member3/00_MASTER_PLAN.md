# Member 3 — Concept Drift + Model Adaptation — MASTER PLAN

> **This file is the immutable common contract for every task agent.**
> It defines the mission, architecture, locked decisions, API contracts, frozen
> module interfaces, and the wave/dependency map.
>
> **Three files share memory between agents:**
> - `CONTEXT.md` — the *living* common context (environment state, shared
>   facts, merged deviations). Every agent reads it before starting.
> - `handoffs/TASK-NN_*.md` — per-task output files. Each finished task leaves
>   exactly one handoff; dependent tasks read the handoffs listed in their
>   spec.
> - `TRACKER.md` — the task status board (orchestrator-owned during parallel
>   waves).
>
> Task agents are **fresh `subagent_general` runs** — stateless. If a fact is
> not in `CONTEXT.md` or a handoff file, the next agent does not know it.
>
> *(v1 phase files preserved under `_archive_v1/` — superseded by `tasks/`.)*

---

## 1. Mission

Make concept-drift detection and model adaptation **live on the production
streaming path** of CyberAdapt, so the full story is visible on the existing
dashboard:

```
Normal traffic streams in
   → Live Traffic shows "Normal Traffic" labels
   → Attack campaign runs against the Labrooms app
   → Live Traffic shows DoS / Brute Force / Web Attacks labels
   → Concept Drift page shows REAL drift alert firing
   → Adaptation engine retrains a candidate on recent labeled flows
   → Promotion gates pass → new champion hot-swapped into /predict
   → Adaptation page shows new model version + retrain history
   → Evaluation page shows live pre/post adaptation metrics
```

**The core gap today:** `GET /concept-drift`, `/adaptation`, `/explain`,
`/evaluation` in `ml/api.py` (lines ~286–395) return **hardcoded static JSON**.
The real ADWIN detectors (`ml/src/drift/detectors.py`) and the
champion/candidate engine (`ml/src/models/adaptive_engine.py`) exist but are
only exercised inside notebook 03 — nothing feeds live traffic to them.

Member 3 closes that gap.

---

## 2. Team Status (what already exists — do NOT rebuild)

| Member | Scope | Status |
|---|---|---|
| Member 1 | Data pipeline, ingestion, sensor, feature contract | ✅ Done |
| Member 2 | Baseline model, training notebooks, champion artifacts, Flask `/predict` | ✅ Done |
| **Member 3** | **Live concept drift + model adaptation + demo attack story** | ⬜ This plan |
| Member 4 | Evaluation/XAI/dashboard build-out | ❌ Skipped — existing UI is kept; Member 3 tasks only *wire* it to live data |

### Completed work you build on

- **Ingestion path** (`server/routes/telemetry.js`): `POST /api/telemetry/ingest`
  validates a 52-feature envelope, bulk-inserts into MongoDB, responds `202`,
  then fire-and-forget calls Flask `POST /predict` and back-fills
  `threatLabel`/`threatConfidence` onto `TelemetryLog` docs.
- **Flask ML API** (`ml/api.py`): loads `champion_model.joblib` +
  `preprocessor.joblib`, maps Labrooms 52-slot vectors → 8 CICIDS2017 features,
  applies **rule-based app-layer overrides** (Slowloris>30s/504→DoS,
  bwd>10MB→exfil, 401/403→Brute Force, 500/large-payload→Web Attacks) on top of
  model predictions.
- **Drift primitives** (`ml/src/drift/detectors.py`): `ADWINDriftDetector`
  (River ADWIN wrapper) and `StreamDriftMonitor` (error + feature signals).
- **Adaptation primitives** (`ml/src/models/adaptive_engine.py`):
  `AdaptiveModelManager` — `retrain_candidate()` (LightGBM) +
  `evaluate_and_promote_candidate()` with 4 quality gates (macro-F1 delta,
  balanced-acc delta, emerged-class recall ≥0.70, Normal FPR ≤0.05).
- **Metrics** (`ml/src/evaluation/metrics.py`): `evaluate_predictions()`
  returns macro F1, balanced acc, per-class metrics, confusion matrix.
- **Attack one-shot** (`sensor/simulate_attacks.py`): sends 4 attack + 1 normal
  flows once. **Not sustained** — TASK-03 builds the campaign version.
- **Dashboard**: 7 pages exist. `ConceptDrift.jsx`, `Adaptation.jsx`,
  `Evaluation.jsx` fetch once on mount and are partially hardcoded —
  TASK-14/15/16 wire them to live data with polling.

---

## 3. System Architecture Recap

```
sensor/*.py            server/ (Express :5000)              ml/api.py (Flask :5001)
 52-feat flows ──► POST /api/telemetry/ingest ──► MongoDB         ▲
 (X-Sensor-Key)        │ TelemetryLog docs                       │ fire-and-forget
                       └──► POST :5001/predict ──────────────────┘
                              back-fill threatLabel
client/ (Vite :3000) ◄── GET /api/telemetry/* (JWT) ── proxies to Flask GETs
```

Ports: client 3000 · Node API 5000 · Flask 5001 · MongoDB 27017.

---

## 4. Feature Contract Cheat Sheet (memorize this)

Labrooms sensors emit a **52-slot** vector; only 10 slots are populated.
`LABROOMS_SLOT_MAP` in `ml/api.py` (lines ~66–76):

| Slot | Meaning | → CICIDS2017 feature |
|---|---|---|
| 1 | Flow Duration (µs) | `Flow Duration` |
| 2 | Total Fwd Packets | `Total Fwd Packets` |
| 3 | Total Bwd Packets | `Bwd Packet Length Max` (proxy) |
| 4 | Total Fwd Bytes | `Total Length of Fwd Packets` |
| 5 | Total Bwd Bytes | `Bwd Packet Length Min` (proxy) |
| 6 | Fwd Pkt Len Max | `Fwd Packet Length Max` |
| 7 | Fwd Pkt Len Min | `Fwd Packet Length Min` |
| 14 | Flow Bytes/s | `Flow Bytes/s` |
| 44 | **HTTP status code** (hijacked SYN slot) | *not an ML feature — used by rules* |
| 0 | Flow ID hash | *identifier — never used* |

Target classes (index order): `Normal Traffic, DoS, DDoS, Port Scanning,
Brute Force, Web Attacks, Bots`.

`LABROOMS_DEPLOYMENT_FEATURES` (8 names) is the model input contract — retrained
candidates MUST use the same 8 features (`ml/src/features/feature_contract.py`).

---

## 5. Locked Design Decisions (all tasks must follow these)

### 5.1 Where drift/adaptation state lives
Inside the **Flask process** (`ml/api.py` + new modules under `ml/src/`).
River is Python-only; detectors and the adaptive engine already exist there.
The Node server stays a dumb proxy — **no drift logic in Node**.

### 5.2 Runtime state persistence
All live state is written to `ml/artifacts/state/` (each owning module
`mkdir`s defensively on first persist; TASK-08 adds it to `.gitignore`):

| File | Contents | Written by |
|---|---|---|
| `drift_state.json` | detector stats, samples processed, drift event log, per-slot reference stats | `LiveDriftMonitor` (TASK-01) |
| `adaptation_history.json` | promotion gate reports / version history (same shape `AdaptiveModelManager.save_state()` writes) | `LiveAdapter` (TASK-04) |
| `active_model.json` | pointer `{model_path, preprocessor_path, version}` so restarts load the latest promoted champion | `LiveAdapter` (TASK-04) |
| `eval_window.jsonl` | bounded (≤2000 lines) rolling log of `{ts, y_true, y_pred, confidence, version}` for live evaluation | `LiveEvaluator` (TASK-05) |

Persist on every drift event and every promotion (not per-flow — too chatty;
per-batch is fine).

### 5.3 Drift signals (what ADWIN actually monitors)
Per `/predict` batch AND per flow:

1. **attack_ratio** — fraction of batch predicted non-Normal (post-rule-override
   labels). Feeds ADWIN + Page-Hinkley. *This is the primary demo signal* —
   normal traffic ≈0.0, attack campaign ≈0.8+.
2. **mean_confidence** — mean prediction confidence per batch → ADWIN.
   Warning-only; never triggers retrain alone.
3. **pseudo_error stream** — where a rule-override fired, `1` if the raw model
   label ≠ rule label else `0` → DDM-style error monitoring.
4. **per-slot feature stats** — maintain a *reference window* (first W=500
   flows since last retrain/reset) and a *recent window* (last W=500). Per
   populated slot (1,4,5,14,44) compute **PSI** (Population Stability Index):
   `<0.1 stable`, `0.1–0.25 minor_shift`, `>0.25 drifted`. Log1p-scale
   byte/duration slots before binning.

**Drift decision:** `drift_detected = ADWIN(attack_ratio) OR PageHinkley
fires OR ≥2 slots drifted`. Single-signal firing on confidence alone logs a
*warning*, not a drift event (avoids flaky retrains).

River provides `ADWIN` and `PageHinkley` in `river.drift`. KS test: use
`scipy.stats.ks_2samp` (scipy is already installed — sklearn depends on it).

### 5.4 Pseudo-labeling (the no-ground-truth problem)
Production streams have no true labels. Buffer/eval labels resolved in this
order (**implemented identically by TASK-04 and TASK-05**):

1. **`LBL::` flow_id convention** — flows whose `flow_id` starts with
   `LBL::<CLASS_NAME>::` carry a simulator ground-truth tag (class name must
   match `TARGET_CLASSES`, underscores→spaces).
2. **Rule-override label** — if `_detect_labrooms_app_layer_anomaly` fired,
   that label is ground-truth-quality for our 4 attack patterns.
3. **High-confidence Normal** — model predicted Normal with confidence ≥0.90
   and no rule fired → label Normal.
4. Everything else → **excluded** (unlabeled).

This is honest (rule labels are real detection knowledge) and keeps the demo
fully automatic.

### 5.5 Adaptation flow
On `drift_detected` (auto) or `POST /adaptation/trigger` (manual):

```
if buffer has ≥ MIN_BUFFER (default 200) labeled samples AND
   ≥2 distinct classes AND ≥ MIN_ATTACK (default 30) non-Normal samples:
    spawn daemon thread:
        candidate = LightGBM retrain on buffer (train 75% / validation tail 25%)
        evaluate_and_promote → 4 gates (same semantics as adaptive_engine.py)
        if promoted: persist adaptive_champion_vN.joblib +
                     adaptive_preprocessor_vN.joblib +
                     active_model.json; hot-swap champion in api.py
        append gate report to adaptation_history.json + in-memory log
        reset drift reference windows
else: record "skipped — insufficient buffer" event
```

Guard: one retrain at a time (adapter lock); after a drift trigger, cooldown
of 60 s before auto-trigger can fire again (manual trigger always allowed).

**Hot-swap:** `ml/api.py` globals `_champion_model`/`_preprocessor` are
reassigned on promotion via the injected `set_champion` callable; `/predict`
and `/model-info` then use the new model immediately. `/model-info` gains a
`version` field.

### 5.6 New/changed endpoints (contracts in §8)
- `GET  /concept-drift` → live detector state (replaces static) — TASK-08
- `GET  /adaptation` → live buffer/version/history (replaces static) — TASK-09
- `POST /adaptation/trigger` → manual retrain trigger **(new)** — TASK-09
- `GET  /evaluation` → live rolling metrics + pre/post adaptation (replaces static) — TASK-10
- `POST /admin/reset` → demo reset, only when env `DEMO_MODE=1` **(new)** — TASK-09/10
- Node proxy: add `POST /api/telemetry/adaptation/trigger` and
  `POST /api/telemetry/admin/reset` (JWT-authed) mirroring existing GET proxies — TASK-06
- `GET /explain` stays static (Member 4 scope, out of ours).

### 5.7 Hard rules for every task
- **Never slow the ingest path.** `/ingest` must still return 202 immediately;
  all drift/adaptation work happens inside Flask or background threads.
- **Fire-and-forget stays fire-and-forget.** `classifyAndAnnotate` in Node is
  untouched except optionally passing flow docs through unchanged.
- No schema changes to `TelemetryLog` unless a task explicitly says so.
- Match existing code style: Flask module-level globals + `_`-prefixed helpers;
  Node = Express routers, async/await, 3–5 s `AbortController` timeouts.
- Windows env: `.venv\Scripts\activate`, `mongod` must be running,
  `MODEL_PATH`/`PREPROCESSOR_PATH` env vars point at `ml/artifacts/models/`.
- Work on branch `member3-drift` if doing git ops; commit per wave.
- **File ownership:** touch ONLY the files your task file lists under
  "Files you may touch". Parallel-wave agents never share editable files.
- **Shared stack rule:** before starting mongod/Node/Flask, check if the port
  is already serving (`curl`/`Test-NetConnection`). If yes, reuse it.
  **Never kill a service you did not start.** Multiple generators posting
  flows concurrently is fine — ingestion is safe for parallel writers.
- Every task ends with the finish protocol in §10.

---

## 6. Task & Wave Map (execution DAG)

Each task is executed by a **fresh `subagent_general` agent**. Tasks in the
same wave run in parallel; waves run in order. Lane C1 and Lane C2 run
concurrently after Wave B.

| ID | Task file | Delivers | Wave | Mode | Depends on |
|---|---|---|---|---|---|
| T01 | `tasks/TASK-01_drift_monitor_module.md` | `ml/src/drift/live_monitor.py` | A | ∥ | — |
| T02 | `tasks/TASK-02_normal_traffic_gen.md` | `sensor/normal_traffic.py` | A | ∥ | — |
| T03 | `tasks/TASK-03_attack_campaign_gen.md` | `sensor/attack_campaign.py` | A | ∥ | — |
| T04 | `tasks/TASK-04_live_adapter_module.md` | `ml/src/adaptation/live_adapter.py` | A | ∥ | — |
| T05 | `tasks/TASK-05_live_evaluator_module.md` | `ml/src/evaluation/live_evaluator.py` | A | ∥ | — |
| T06 | `tasks/TASK-06_node_proxy_routes.md` | 2 POST proxies in `telemetry.js` | A | ∥ | — |
| T07 | `tasks/TASK-07_api_js_post_helper.md` | `api.post()` in `client/src/api.js` | A | ∥ | — |
| T08 | `tasks/TASK-08_wire_drift_api.md` | live `/concept-drift` + predict hook | B | seq | T01 |
| T09 | `tasks/TASK-09_wire_adaptation_api.md` | live `/adaptation`, trigger, reset, hot-swap boot | B | seq | T04, T08 |
| T10 | `tasks/TASK-10_wire_evaluation_api.md` | live `/evaluation` | B | seq | T05, T09 |
| T11 | `tasks/TASK-11_verify_drift_e2e.md` | drift verified on live stack | C1 | seq | T08, T02, T03 |
| T12 | `tasks/TASK-12_verify_adaptation_e2e.md` | promotion verified end-to-end | C1 | seq | T09, T11 |
| T13 | `tasks/TASK-13_verify_evaluation_e2e.md` | metrics verified end-to-end | C1 | seq | T10, T12 |
| T14 | `tasks/TASK-14_conceptdrift_page.md` | `ConceptDrift.jsx` live + polling | C2 | ∥ | T08 |
| T15 | `tasks/TASK-15_adaptation_page.md` | `Adaptation.jsx` live + FORCE button | C2 | ∥ | T06, T07, T09 |
| T16 | `tasks/TASK-16_evaluation_page.md` | `Evaluation.jsx` live + polling | C2 | ∥ | T10 |
| T17 | `tasks/TASK-17_e2e_rehearsal.md` | 2 timed E2E runs, all checkpoints | D | seq | T11–T16 |
| T18 | `tasks/TASK-18_demo_runbook.md` | `DEMO_RUNBOOK.md` | D | ∥ | T17 |
| T19 | `tasks/TASK-19_readme_update.md` | README delta | D | ∥ | T17 |

### Wave diagram

```
WAVE A (7 parallel agents — disjoint files only)
  T01 drift monitor   T02 normal gen   T03 attack gen   T04 adapter
  T05 evaluator       T06 node proxy   T07 api.js post
                          │
WAVE B (sequential — single writer on ml/api.py)
  T08 wire drift ──► T09 wire adaptation ──► T10 wire evaluation
                          │
          ┌───────────────┴────────────────┐
LANE C1 (sequential, live stack)   LANE C2 (parallel, frontend)
  T11 verify drift ──► T12 verify ──► T13 verify eval
          adaptation                 T14 ConceptDrift.jsx ∥ T15 Adaptation.jsx ∥ T16 Evaluation.jsx
          └───────────────┬────────────────┘
WAVE D (closeout)
  T17 E2E rehearsal ×2 ──► T18 DEMO_RUNBOOK.md ∥ T19 README delta
```

**Why parallel where it is:** Wave A units are pure new-file authoring (or
exclusive-file edits) coded against the frozen §9 interfaces — zero shared
files. Wave B serializes because all three tasks edit `ml/api.py`. Lane C1
serializes because the verification tasks share one live Flask process's
state. Lane C2 parallelizes because each page is a separate file. T18/T19
parallelize over separate docs.

**Critical path:** T01/T04 → T08 → T09 → T10 → T11 → T12 → T13 → T17 → T18.

---

## 7. The Demo Narrative (what we're building toward)

1. Stack up (mongod, :5000, :5001, :3000). `POST /admin/reset` → clean slate.
2. `normal_traffic.py` streams benign flows → Live Traffic = green "Normal",
   Concept Drift = STABLE, PSI scores ~0.
3. `attack_campaign.py` starts a Slowloris+brute-force wave against Labrooms →
   Live Traffic floods red (DoS / Brute Force) → within seconds Concept Drift
   shows ADWIN DRIFT + red banner, feature PSI spikes.
4. Adaptation page: buffer fills → auto-retrain fires → "candidate evaluating"
   → gates pass → **version bumps v1→v2**, history row appears.
5. Post-adaptation: predictions continue correctly; Evaluation page shows
   pre-F1 vs post-F1 and the confusion matrix over the live window.
6. Talking point: "The model detected that the world changed and healed itself."

---

## 8. API Contracts (exact shapes — build to these)

### `GET /concept-drift` → 200
```json
{
  "status": "active",
  "drift_detected": false,
  "drift_state": "stable",
  "samples_processed": 12345,
  "samples_processed_since_retrain": 200,
  "last_drift_timestamp": "2026-10-04T10:22:10Z",
  "attack_ratio_recent": 0.04,
  "detector_algorithms": {
    "ADWIN_attack_ratio":  {"status": "stable", "estimation": 0.03, "width": 812, "drift_signal": false},
    "PageHinkley":         {"status": "nominal", "sum_val": 1.42, "threshold": 50.0, "drift_signal": false},
    "DDM_pseudo_error":    {"status": "stable", "error_rate": 0.021, "warning_level": 0.05, "drift_signal": false},
    "KS_Test":             {"status": "stable", "stat": 0.042, "p_value": 0.612, "drift_signal": false}
  },
  "labrooms_features_drift": [
    {"slot": 1,  "name": "Flow Duration",     "drift": 0.012, "status": "stable"},
    {"slot": 4,  "name": "Total Fwd Bytes",   "drift": 0.018, "status": "stable"},
    {"slot": 5,  "name": "Total Bwd Bytes",   "drift": 0.245, "status": "minor_shift"},
    {"slot": 14, "name": "Flow Bytes/s",      "drift": 0.028, "status": "stable"},
    {"slot": 44, "name": "HTTP Status Code",  "drift": 0.005, "status": "stable"}
  ],
  "drift_events": [
    {"timestamp": "2026-10-04T10:22:10Z", "signal": "attack_ratio",
     "detector": "ADWIN", "samples_processed": 11900, "detail": "attack_ratio estimation jumped 0.02 → 0.71"}
  ]
}
```
`drift_state` ∈ `stable | warning | drift`. `drift` in feature table = PSI score.
`drift_events` = last 20, newest first.

### `GET /adaptation` → 200
```json
{
  "champion_model": "LGBMClassifier",
  "champion_version": "v2",
  "adaptation_mode": "Drift-triggered candidate retrain + gated promotion",
  "model_loaded_at": "2026-10-04T10:30:00Z",
  "adaptation_in_progress": false,
  "online_learning_buffer": {
    "capacity": 5000, "current_size": 1420, "fill_percentage": 28.4,
    "label_sources": {"verified_label": 20, "rule_override": 320, "flow_id_tag": 1060}
  },
  "retraining_history": [
    {"version": "v2", "timestamp": "...", "f1_score": 0.984,
     "trigger": "ADWIN drift alert (attack_ratio)", "promoted": true,
     "gates_passed": {"gate_macro_f1": true, "gate_bal_acc": true,
                      "gate_emerged_recall": true, "gate_normal_fpr": true}}
  ],
  "last_event": {"type": "promotion|rejection|skipped", "timestamp": "...", "detail": "..."}
}
```

### `POST /adaptation/trigger` → 202
```json
{"status": "accepted", "job": "candidate_retrain", "buffer_size": 1420}
```
or `409 {"status":"busy"}` if a retrain is running, `422` if buffer insufficient.

### `GET /evaluation` → 200
```json
{
  "dataset": "Live Labrooms stream (pseudo-labeled)",
  "window": {"size": 500, "since": "2026-10-04T10:00:00Z"},
  "overall_metrics": {"accuracy": 0.987, "precision_macro": 0.981,
    "recall_macro": 0.979, "f1_macro": 0.980, "latency_p95_ms": 3.4},
  "per_class_metrics": {"Normal Traffic": {"precision": 0.99, "recall": 0.99, "f1": 0.99, "support": 420}, "...": {}},
  "confusion_matrix": [[...7x7...]],
  "class_names": ["Normal Traffic","DoS","DDoS","Port Scanning","Brute Force","Web Attacks","Bots"],
  "pre_post_adaptation": {
    "pre":  {"f1_macro": 0.71, "samples": 300},
    "post": {"f1_macro": 0.96, "samples": 200},
    "last_adaptation": "2026-10-04T10:31:00Z"
  }
}
```
With <30 labeled samples in window: return `"insufficient_data": true` + zeros —
the UI handles it gracefully.

### `POST /admin/reset` → 200 (requires env `DEMO_MODE=1`, else 403)
```json
{"status": "reset", "cleared": ["drift_state", "buffer", "history", "eval_window"]}
```
Reloads the *original* champion artifacts from `MODEL_PATH`/`PREPROCESSOR_PATH`.

---

## 9. Frozen Module Interfaces (the parallel-contract)

Wave-A agents code against these signatures **exactly** — this is what makes
parallel authoring safe. If reality forces a deviation, record it in your
handoff AND flag it in the "Merge suggestions" section so the orchestrator
updates `CONTEXT.md`.

### 9.1 `batch_record` — the shared payload

`predict()` in `ml/api.py` builds one `list[dict]` per request and passes the
same list to monitor, adapter, and evaluator:

```python
batch_record = {
    "flow_id": str,               # as received (may carry LBL:: tag)
    "raw_features": list[float],  # the raw 52-slot vector
    "label": str,                 # FINAL label, post rule-override
    "label_index": int,           # index into TARGET_CLASSES
    "confidence": float,          # probability of the final label
    "rule_override": bool,        # did _detect_labrooms_app_layer_anomaly fire
    "model_raw_label": str,       # model's label BEFORE override
    "model_raw_index": int,
}
```

### 9.2 `LiveDriftMonitor` — `ml/src/drift/live_monitor.py` (TASK-01)

```python
class LiveDriftMonitor:
    def __init__(self, state_path: Path, window: int = 500): ...
    def process_batch(self, records: list[dict]) -> dict:
        """Feed one /predict batch. Returns batch drift summary.
        Fires at most one drift event per batch."""
    def get_status(self) -> dict:
        """Exact §8 /concept-drift contract."""
    def consume_drift_event(self) -> dict | None:
        """Pop the pending drift trigger (for the adapter). None if none."""
    def reset_reference(self) -> None:
        """Rotate reference←recent baselines (call after every promotion)."""
    def reset(self) -> None: ...
    def _persist(self) -> None: ...
    def _restore(self) -> None: ...

def detect_drift() -> bool:   # module-level; wraps singleton check
```

### 9.3 `LiveAdapter` — `ml/src/adaptation/live_adapter.py` (TASK-04)

Dependencies are **injected callables**, never imports of api.py or the
monitor — this is what lets TASK-04 ship before TASK-08/09 run:

```python
class LiveAdapter:
    def __init__(self, state_dir: Path,
                 get_champion,          # () -> (model, preprocessor)
                 set_champion,          # (model, preprocessor, version:str) -> None
                 extract_features,      # (raw_52:list) -> dict[8 features]
                 consume_drift_event,   # () -> dict | None
                 reset_drift_reference, # () -> None
                 capacity: int = 5000, min_buffer: int = 200,
                 min_attack: int = 30, cooldown_sec: int = 60): ...
    def observe(self, records: list[dict]) -> None:
        """Append pseudo-labeled samples (§5.4 rule) to ring buffer."""
    def maybe_trigger(self) -> None:
        """If drift event pending + cooldown ok + buffer sufficient → retrain."""
    def trigger(self, reason: str) -> dict:
        """Manual trigger → {status: accepted|busy|insufficient, ...}."""
    def get_status(self) -> dict:
        """Exact §8 /adaptation contract."""
    def reset(self) -> None: ...
    @property
    def champion_version(self) -> str: ...

def adapt_model(reason: str = "manual") -> dict:   # module-level; wraps singleton trigger
```

### 9.4 `LiveEvaluator` — `ml/src/evaluation/live_evaluator.py` (TASK-05)

```python
class LiveEvaluator:
    def __init__(self, state_path: Path, window: int = 500): ...
    def record(self, records: list[dict], latency_ms: float) -> None:
        """Append pseudo-labeled rows only (§5.4 rule — same as adapter)."""
    def get_metrics(self) -> dict:
        """Exact §8 /evaluation contract; insufficient_data when <30 samples."""
    def reset(self) -> None: ...
```

### 9.5 Wiring order inside `predict()` (TASK-08/09/10)

```python
batch_records = [...]                      # built once, per §9.1
with guarded_try_except():                  # never break /predict
    _drift_monitor.process_batch(batch_records)   # T08
    _adapter.observe(batch_records)               # T09
    _adapter.maybe_trigger()                      # T09
    _evaluator.record(batch_records, latency_ms)  # T10
```

---

## 10. Context & Handoff Protocol — every agent MUST do this

### Files
- **`CONTEXT.md`** — common context. Read fully before starting. Append-only
  for sequential agents; **parallel-wave agents must NOT edit it** (race) —
  they put updates in their handoff's "Merge suggestions" section and the
  orchestrator merges between waves.
- **`handoffs/TASK-NN_<slug>.md`** — your output file. Copy
  `handoffs/_TEMPLATE.md`, fill every field, paste real verification output.
- **`TRACKER.md`** — status board. Sequential agents set their own row;
  parallel-wave agents leave it to the orchestrator (same race rule).

### Agent steps
1. Read, in order: `CONTEXT.md` → your `tasks/TASK-NN_*.md` → the handoff
   files listed under your task's "Input handoffs" → referenced code files.
   Skim `00_MASTER_PLAN.md` sections your task cites (§4, §5.x, §8, §9).
2. Verify dependencies: required handoffs must exist and show `done` (or an
   acceptable `partial`). If not, STOP and report the blocker — do not
   improvise around missing work.
3. Implement exactly to spec + §8/§9 contracts. If reality diverges, prefer
   working software and record the deviation in your handoff.
4. Run your task's Verification section; paste real outputs into the handoff.
5. Write `handoffs/TASK-NN_<slug>.md`.
6. **Sequential task?** Also update `CONTEXT.md` (append facts/deviations)
   and your `TRACKER.md` row. **Parallel task?** Fill the handoff's
   "Merge suggestions" section instead — orchestrator merges.
7. Report back a short summary + anything the operator must know.

---

## 11. Orchestrator Runbook (how to launch agents)

Execute waves in order. Within a wave, launch all tasks **in parallel** (one
`run_subagent(profile="subagent_general")` call per task, background mode).
Wait for the whole wave (or lane) before starting the next — then merge
handoffs into `CONTEXT.md`/`TRACKER.md`.

### Launch sequence
1. **Wave A:** launch T01–T07 in parallel → merge.
2. **Wave B:** launch T08 → wait → T09 → wait → T10 → merge.
3. **Wave C:** launch lanes concurrently — C1: T11 → T12 → T13 sequential;
   C2: T14, T15, T16 parallel → merge.
4. **Wave D:** T17 → then T18 ∥ T19 → merge → final TRACKER audit.

### Subagent launch prompt (copy-paste template)

```
You are a fresh task agent executing TASK-NN of the CyberAdapt Member-3 plan.
Repo root: E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project
You are stateless — everything you need is in files.

Read, in this order:
1. documentation/member3/CONTEXT.md
2. documentation/member3/tasks/TASK-NN_<slug>.md   ← your complete spec
3. documentation/member3/handoffs/<dep files listed in your task>
4. 00_MASTER_PLAN.md sections your task cites (§4, §5.x, §8, §9)

Rules:
- Touch ONLY the files listed under "Files you may touch" in your task.
- Follow the spec + frozen interfaces (master plan §9) exactly. If reality
  diverges, prefer working software and record the deviation.
- Shared stack rule (§5.7): reuse running services, never kill others'.
- Run your task's Verification section with real commands.

When done:
- Write documentation/member3/handoffs/TASK-NN_<slug>.md using
  handoffs/_TEMPLATE.md — every field filled, real outputs pasted.
- [PARALLEL] Do NOT edit CONTEXT.md or TRACKER.md — fill "Merge suggestions"
  in your handoff.
- [SEQUENTIAL] Append your facts to CONTEXT.md and set your TRACKER.md row.

Report back: status (done|partial|blocked) + ≤5-line summary + blockers.
```

### Merge step (between waves)
For each handoff in the finished wave:
- Apply "Merge suggestions" → `CONTEXT.md` (shared facts, deviations).
- Set the task's `TRACKER.md` row status + link the handoff.
- If a task ended `partial`/`blocked`, decide: retry with a new agent, fold
  the leftover into a dependent task, or escalate to the operator.
