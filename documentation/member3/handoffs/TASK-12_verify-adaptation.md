# HANDOFF — TASK-12 — Verify Adaptation E2E (live stack)

| | |
|---|---|
| **Task** | TASK-12 — Verify Adaptation E2E (live stack) |
| **Status** | `done` |
| **Wave** | C1 — sequential |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-09 (trigger semantics, cooldown, `active_model.json`), TASK-11 (drift latch behavior, warmup-shift caveat) |

---

## Files created

- `ml/scripts/check_adaptation_api.py` — verification helper (verify-only task:
  no `ml/api.py`/`ml/src/*` touched). Modes: `status` · `poll [s]` · `audit`
  (38-check §8 field-by-field contract audit) · `full` · `modelinfo` ·
  `trigger`/`triggerx2` (Flask) · `proxytrigger`/`proxytriggerx2` (Node + JWT
  login) · `reset` · `seed dos|normal N [batch]` (flows via real Node ingest
  path) · `predict dos|normal N` (Flask direct) · `waitpromo [s]`.
  Uses `127.0.0.1`, ASCII-only output, reuses `attack_campaign.py`'s real
  generator envelopes.

## Files modified

- none (verify-only task)

## Stack state (as found / left)

- **Found: whole stack DOWN** — no LISTENING sockets on 27017/5000/5001/3000
  (CONTEXT.md §A claimed T11 left it running; it was gone at T12 start — same
  thing T11 found after T10). All ports free → started all three myself per
  §5.7: `mongod --dbpath %USERPROFILE%\mongodb-data` · Flask
  `MODEL_PATH=ml/artifacts/models/champion_model.joblib PREPROCESSOR_PATH=ml/artifacts/models/preprocessor.joblib DEMO_MODE=1 PORT=5001 python -m ml.api`
  · `npm run dev` in `server/`.
- **Left running:** mongod :27017, Flask :5001 (DEMO_MODE=1, **post-reset
  clean**: v1, buffer 0, drift n=0), Node :5000. Client :3000 not started.
  Stale `adaptive_*_v2..v5` joblibs removed post-verification (T09 convention).

## Verification run — 7-step protocol

### 0. Clean slate + empty-buffer 422 (spec step 5, done early)

```
$ check_adaptation_api.py reset
→ 200 {"cleared":["drift_state","buffer","history","model_artifacts","eval_window"],"status":"reset"}
  version=v1 buffer=0/5000 labels all-0 hist=0 last_event=None | stable n=0

$ check_adaptation_api.py trigger          (Flask direct)
→ 422 {"buffer_size":0,"detail":"0 labeled samples < min_buffer 200","status":"insufficient"}

$ check_adaptation_api.py proxytrigger     (POST /api/auth/login → JWT → Node proxy)
→ JWT ok; POST /api/telemetry/adaptation/trigger → 422 (same body — literal passthrough)
```

### 1. BUFFER — normal_traffic.py (no --lbl-tag → high_confidence path)

```
$ python sensor/normal_traffic.py --key ca_live_5d14… --url http://127.0.0.1:5000/api/telemetry/ingest \
    --interval 0.5 --batch-size 16 --duration 70
→ 138 batches, 0 errors, 2208 flows accepted (31.5 flows/s)
```

| t | buffer | label_sources |
|---|---|---|
| +20s | 784/5000 (15.7%) | hc:784 |
| +50s | 1904/5000 (38.1%) | hc:1904 |
| end  | 2208/5000 (44.2%) | hc:2208 |

`buffer.current_size` grew linearly and `label_sources.high_confidence` climbed
0→2208 exactly as spec'd; monitor crossed `warming_up→active` at n=500 and
stayed `stable` (all PSI <0.10). **Every buffered row is Normal** — the
~2% "Brute Force" model FPs are correctly *excluded* (non-Normal, no
rule_override, no LBL tag → §5.4 rule 4).

### 2. TRIGGER — drift auto-trigger → promotion v1→v2

The known T11 hazard: on a `normal_traffic` baseline, `attack_campaign`'s
warmup fires PSI ~16 s in, before any non-Normal label exists → skip. Fix per
the task hint: prime the buffer with non-Normal labels first, via the **real
ingest path** (Node `/api/telemetry/ingest` → Mongo → fire-and-forget → Flask
`/predict`), using `attack_campaign.py`'s own `gen_dos` envelopes with
`LBL::DoS::` tags:

```
$ check_adaptation_api.py seed dos 90 30
[seed dos] +30 via ingest -> 202 accepted=30   → buffer=2238 tag:30  drift_state=warning
[seed dos] +30 via ingest -> 202 accepted=30   → buffer=2268 tag:60  drift event FIRED
   {"timestamp":"2026-10-04T06:53:50Z","signal":"feature_psi","detector":"PSI",
    "samples_processed":2268,
    "detail":"attack_ratio 1.00; PSI drifted on 4 slots (Flow Duration,
              Total Bwd Bytes, Flow Bytes/s, HTTP Status Code)"}
   → maybe_trigger() consumed it in the SAME /predict call (buffer already had
     the firing batch's DoS labels: 2208 Normal + 60 DoS — sufficient)
   → daemon retrain → PROMOTION v1→v2
[seed dos] +30 via ingest -> 202 accepted=30   → version=v2
```

Flask log (measured):
```
12:23:50.930  drift event fired (PSI): attack_ratio 1.00; PSI drifted on 4 slots
12:23:50.941  POST /predict 200   ← firing request returned normally
12:23:50.949  Fitted preprocessor on 1701 training records with 8 features
12:23:51.056  Saved adaptive_preprocessor_v2.joblib
12:23:51.063  Champion hot-swapped to v2 → adaptive_champion_v2.joblib
12:23:51.064  PROMOTION SUCCESSFUL v1 -> v2 (trigger: PSI drift alert (feature_psi))
```

**Measured numbers — promotion #1:**
- Buffer size at trigger: **2,268** (snapshot in gate report; 2,208 hc-Normal +
  60 tag-DoS)
- Time drift-event → promotion: **≈0.13 s** (50.930→51.064, daemon thread)
- Gates (all true): champion_macro_f1 **0.4933** → candidate_macro_f1 **1.0000**
  (Δ+0.5067); bal_acc 0.50→1.00; emerged_class DoS recall **1.0000**;
  normal_fpr **0.0**
- Split: `stratified_75_25 fallback` (chrono tail was single-class — expected;
  train 1,701 / val 567)
- Artifacts: `adaptive_champion_v2.joblib` (38,964 B) +
  `adaptive_preprocessor_v2.joblib` + `state/active_model.json` written

**Then ran the spec's campaign** (`attack_campaign.py --scenario dos --rate 12
--batch-size 12`, 1,260 flows, 0 errors) — and it produced a **second, fully
organic auto-promotion** plus a live cooldown enforcement:

```
event2  06:55:26Z n=2470  PSI 2 slots (Bwd Bytes, Flow B/s) attack_ratio 0.00
        ← campaign-warmup generator-switch shift (T11's known caveat)
        → cooldown (60 s) had elapsed → retrain → PROMOTION v2→v3 (all gates)
event3  06:55:42Z n=2662  PSI 2 slots — SAME signal refired post-rotation
        → consumed but "skipped — drift trigger dropped — cooldown active
          (44s remaining)"  ← §5.5 auto-cooldown verified live
```

Post-campaign: `version=v3 buffer=3574 (hc:2208 tag:1366) hist=2 drift_state=drift`
(latch stays `drift` after a skipped event — documented T11 semantics).

### 3. HOT-SWAP

```
$ GET /model-info → version=v3, model_path=…\adaptive_champion_v3.joblib,
                    model_type=LGBMClassifier, n_estimators=60
$ predict dos 8   → labels={'DoS': 8}          lat=4.7 ms   (v2, mid-run)
$ predict normal 8 → labels={'Normal Traffic':7,'Brute Force':1}  lat=4.9 ms
```

Predictions stay correct under each new champion; `/predict` latency ~5 ms per
8-flow batch — ingest path unaffected (§5.7 holds; retrain ran in daemon while
/predict kept returning 200, see timestamps above).

### 4. MANUAL trigger — Flask direct AND Node proxy+JWT

```
$ triggerx2  (Flask)
 #1 → 202 {"status":"accepted","job":"candidate_retrain","buffer_size":3574}
 #2 → 409 {"status":"busy","detail":"candidate retrain already in progress"}
   → retrain promoted v3→v4 (macro_f1 1.0→1.0 — delta-gate ≥-0.01 passes
     same-quality candidates; T09-documented behavior)

$ proxytriggerx2  (JWT login admin@acme-test.local → Bearer)
 #1 → 202 accepted   → promoted v4→v5
 #2 → 409 busy
```

`adaptation_in_progress` flipped true→false between polls (retrains ≈150 ms —
the 409 `busy` response is itself proof the flag was set server-side).

### 5. NEGATIVE — 422 insufficient

- Empty buffer (n=0, fresh reset): **422** both Flask-direct and Node-proxy
  (`{"status":"insufficient","detail":"0 labeled samples < min_buffer 200"}`).
  Re-verified post-final-reset as spec ordered.
- The adapter also records the rejection as `last_event.type="skipped"`.
- Gate-rejection path (`last_event.type="rejection"`, champion unchanged) was
  already proven live + in-process by T09; not reproducible without patching —
  not re-attempted (verify-only task).

### 6. PERSISTENCE — Flask restart (v5 state)

```
$ kill Flask; restart with identical env
log → drift state restored: 3574 samples, 3 events, active=False
log → LiveAdapter restored: 4 history entries, version v5,
      label_sources {'rule_override':0,'high_confidence':2208,'flow_id_tag':1366}
log → Boot-restoring promoted champion v5 via active_model.json → adaptive_champion_v5.joblib
$ GET /adaptation  → version=v5 hist=4 label_sources restored buffer=0
$ GET /model-info  → version=v5 model_path=…\adaptive_champion_v5.joblib
```

Everything except the buffer ring (documented non-persistent, §5.2) survived:
version, gate history, label counters, last_event, drift events/latch, and the
**boot model itself** (pointer file took precedence over env vars).

### 7. RESET — POST /admin/reset

```
→ 200 {"status":"reset","cleared":["active_model","drift_state","buffer",
       "history","model_artifacts","eval_window"]}
→ version=v1 buffer=0 labels all-0 hist=0 last_event=None
→ /concept-drift: stable n=0 events=0
→ /model-info: version=v1, model_path=ml\artifacts\models\champion_model.joblib,
   model_type=WeightedSoftVotingEnsemble   ← ORIGINAL artifact reloaded
→ state/active_model.json deleted; eval_window.jsonl deleted
→ post-reset trigger → 422 (spec step 5 re-verified)
```

## Contract audit — GET /adaptation vs §8

**PASSED — 38 checks**, run on the populated post-restart v5 state AND on the
fresh reset state (`check_adaptation_api.py audit`):

- Top-level keys **exactly** the §8 set — no missing, no extras:
  `champion_model`, `champion_version`, `adaptation_mode`,
  `model_loaded_at`, `adaptation_in_progress`,
  `online_learning_buffer`, `retraining_history`, `last_event`.
- Types: `champion_model`/`champion_version`/`adaptation_mode`/`model_loaded_at`
  str (version `vN`, loaded_at ISO-Z), `adaptation_in_progress` bool.
- `online_learning_buffer` = exactly {capacity int>0, current_size int≥0,
  fill_percentage float, label_sources {rule_override, high_confidence,
  flow_id_tag} all int≥0}.
- `retraining_history` rows = exactly {version, timestamp, f1_score, trigger,
  promoted bool, gates_passed {gate_macro_f1, gate_bal_acc,
  gate_emerged_recall, gate_normal_fpr} all bool}.
- `last_event` = exactly {type, timestamp, detail}; `type` vocab observed:
  `promotion`, `skipped` (both live). `null` on a truly-fresh boot.
- §8 trigger codes confirmed live: **202** accepted `{status, job:
  candidate_retrain, buffer_size, reason}`; **409** `{status:busy, detail,
  buffer_size}`; **422** `{status:insufficient, detail, buffer_size}`.

## Outputs produced

- **Full loop verified on real traffic**: buffer fill → PSI drift →
  auto-trigger (event consumed mid-`/predict`) → gated retrain → promotion
  **v1→v2 in ~0.13 s** → hot-swap → artifacts persisted → restart restore →
  reset to v1. Then two more auto/manual promotions (v2→v3, v3→v4, v4→v5).
- Measured: buffer at trigger 2,268; champ F1 0.4933 → cand 1.0000; DoS recall
  1.0; normal_fpr 0.0; 60 s auto-cooldown enforced (dropped event recorded);
  one-retrain lock enforced (409); boot-restore via `active_model.json`.
- `/predict` stayed healthy throughout (~5 ms/8-flow batch incl. the batch that
  fired the drift event).

## Deviations from spec

1. **Buffer priming before the campaign** — spec's literal order (normal
   baseline → `attack_campaign.py`) guarantees the T11 outcome: warmup-PSI
   fires with an all-Normal buffer → `skipped — insufficient buffer` → latch
   consumes the only event → no auto-promotion. Per the task hint I primed
   ≥30 non-Normal labels first (90 `LBL::DoS` flows through the real ingest
   path). Result: the *seed itself* fired the drift event and promoted v1→v2;
   the campaign then produced a second organic auto-promotion v2→v3. The
   verified mechanism is identical: PSI drift event → `maybe_trigger()` →
   gated retrain → hot-swap.
2. **Step 5 (422) executed at step 0** — empty buffer was the natural moment;
   re-verified after the final reset too. No behavioral difference.
3. Nothing in shipped code — verify-only task, nothing patched.

## Handoff notes for dependent tasks

- For **TASK-13 (verify evaluation)**: promotion history now exists in every
  run (`pre_post_adaptation` should populate post-promotion). Buffer is
  empty after restart but `eval_window.jsonl` persists rows across restarts
  (500 rows restored this session). Stack left up; run `/admin/reset` for a
  clean slate or reuse the warm state.
- For **TASK-15/17**: manual trigger ALWAYS promotes when buffer is healthy
  (delta-gates ≥-0.01 — candidate can't lose to an identical champion).
  Version bumps each FORCE press — fine for demo; expect v2→v3→v4…
  Also: auto-cooldown = 60 s; a second drift event inside the window is
  recorded as `skipped — cooldown active (Ns remaining)` in last_event.
- For **T14/T15 UI**: `last_event.type` ∈ {promotion, rejection, skipped,
  error}; observed live: promotion + skipped. `last_event` is `null` only on
  a pristine boot (before any trigger/skip). `model_loaded_at` = api's
  `_model_loaded_at` (bumped on every hot-swap).
- **Watch out**: on a `normal_traffic.py` baseline, `attack_campaign.py`
  warmup ALWAYS fires PSI first (~16 s in) — for a demo auto-promotion either
  prime ≥30 attack labels first (what I did), run the campaign on a fresh
  monitor (contaminated-ref route — untested), or accept the warmup-skip and
  use the FORCE button.
- The drift latch clears on promotion (`reset_reference()` post-retrain) —
  drift_state returns to stable/warning, NOT stuck at drift. After a
  *skipped* event the latch stays `drift` (T11 documented).
- Reusable checker: `ml/scripts/check_adaptation_api.py` (status/audit/
  trigger/proxytrigger/seed/predict/reset/waitpromo).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT §A "Stack last state": all three up — mongod :27017, Flask :5001
  (DEMO_MODE=1, post-reset clean v1, n=0), Node :5000. Stack was fully DOWN at
  T12 start; T12 agent started all three.
- CONTEXT fact: adaptation verified E2E — PSI drift auto-triggered retrain →
  promotion v1→v2 in ~0.13 s (buffer 2,268; champ F1 0.4933→cand 1.0, all 4
  gates); campaign-warmup generator-shift produced a second auto-promotion
  v2→v3; 60 s auto-cooldown dropped a third event (recorded `skipped`);
  manual triggers promoted v3→v4→v5; boot-restore kept v5 across restart;
  `/admin/reset` → v1 + original ensemble artifact.
- CONTEXT fact: `/adaptation` §8 contract audited field-by-field — PASSED
  (38 checks, populated + fresh states; `ml/scripts/check_adaptation_api.py
  audit`). last_event.type vocab live: promotion|skipped; null on pristine boot.
- CONTEXT fact: manual-trigger promotion is deterministic when buffer is
  healthy (delta-gates ≥-0.01 — same-quality candidates pass; each FORCE
  press bumps the version).
- Open issue: none.
- TRACKER row status: `done` — "Adaptation verified E2E: PSI drift
  auto-trigger → v1→v2 promotion (buffer 2268, F1 0.49→1.0, ~0.13 s), second
  auto-promotion v2→v3 on campaign warmup, cooldown-skip + 409/422 paths live,
  hot-swap correct, boot-restore v5, reset→v1; §8 audit PASSED 38 checks"
