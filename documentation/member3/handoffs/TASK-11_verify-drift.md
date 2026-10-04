# HANDOFF — TASK-11 — Verify Drift E2E (live stack)

| | |
|---|---|
| **Task** | TASK-11 — Verify Drift E2E (live stack) |
| **Status** | `done` |
| **Wave** | C1 — sequential |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-08, TASK-02, TASK-03 (+ T01 monitor internals for the audit) |

---

## Files created

- `ml/scripts/check_drift_api.py` — verification helper (verify-only task: no
  `ml/api.py`/`ml/src/*` touched). Modes:
  `once` (compact status line) · `poll [s]` · `audit` (26-check field-by-field
  §8 contract audit) · `full` (raw JSON). Uses `127.0.0.1`, ASCII-only output.

## Files modified

- none (verify-only task)

## Stack state (as found / left)

- **Found: whole stack DOWN** — no LISTENING sockets on 27017/5000/5001/3000
  (CONTEXT.md §A said Flask was left running by T10; it was gone at T11 start).
  All ports were free → started all three myself per §5.7, killed nothing:
  `mongod --dbpath %USERPROFILE%\mongodb-data` · Flask `python -m ml.api`
  (MODEL_PATH/PREPROCESSOR_PATH→`ml/artifacts/models/`, DEMO_MODE=1, PORT=5001)
  · `npm run dev` in `server/`.
- **Left running:** mongod :27017, Flask :5001 (DEMO_MODE=1, **post-reset
  clean**: v1, warming_up, n=0), Node :5000. Client :3000 not started (not needed).

## Verification run — 4-step protocol

### 0. Clean slate

```
$ curl -X POST http://127.0.0.1:5001/admin/reset
→ {"cleared":["drift_state","buffer","history","model_artifacts","eval_window"],"status":"reset"}
  → status=warming_up drift_state=stable n=0, all signals False, PSI all 0.0
```

### 1. BASELINE — normal_traffic.py

```
$ python sensor/normal_traffic.py --key "ca_live_5d14…" --url http://127.0.0.1:5000/api/telemetry/ingest \
    --interval 0.5 --batch-size 16 --duration 90 --lbl-tag
→ Batches OK/err: 176/0   Flows accepted: 2816  (31.3 flows/s)   Elapsed: 90.0s
```

Polled `/concept-drift` every ~12 s:

```
n=48    warming_up stable  atk=0.0  all PSI 0.0000
n=432   warming_up stable  atk=0.0  all PSI 0.0000
n=832   active      stable  atk=0.0  s14=0.0454(max)   ← warming_up→active at the 500 mark
n=1584  active      stable  atk=0.0  s14=0.0459
n=2816  active      stable  atk=0.0  s1=0.0311 s4=0.0382 s5=0.0196 s14=0.0278 s44=0.0128
```

End-state detectors: ADWIN est=0.0 width=176 · PH sum=0.0 · DDM err=0.0 ·
KS stat=0.036 p=0.9027 · `last_drift_timestamp=null` · `drift_events=[]`.
**Every PSI slot stayed <0.10 for the whole 2816-flow baseline.** ✓

### 2. ATTACK — attack_campaign.py --scenario dos

```
$ python sensor/attack_campaign.py --key "ca_live_5d14…" --url http://127.0.0.1:5000/api/telemetry/ingest \
    --scenario dos --rate 12 --batch-size 12
→ warmup 360/360 · dos 540/540 · cooldown 360/360 · 0 errors · 105.3 s
```

Polled every ~5 s. **Measured sequence:**

```
n=2840  stable   KS=F  s5=0.0141                    (campaign warmup flowing)
n=2912  stable   KS=T  s5=0.0669 s14=0.1402         ← KS first to notice shift
n=2972  stable   KS=T  s5=0.1851 s14=0.2261         ← minor_shift, climbing
n=3032  DRIFT latched, events=1, PSI rotated ~0     ← FIRED at n=3008
n=3092  drift    DDM=T        atk_ratio=0.006       (first DoS labels landing)
n=3656  drift    DDM=T KS=T   atk=0.96 s5=10.71 s14=8.88
n=3716  drift    DDM=T KS=T   atk=1.00 s1=11.16 s5=13.58 s14=11.93 s44=4.91  ← peaks
n=4028  drift    DDM=T KS=T   atk=0.40 s5=5.33      (cooldown normals decay the window)
n=4076  drift    DDM=T KS=T   atk=0.30  events STILL = 1   ← latch suppression verified
```

**The drift event (verbatim):**

```json
{"timestamp": "2026-10-04T06:39:50Z", "signal": "feature_psi", "detector": "PSI",
 "samples_processed": 3008,
 "detail": "attack_ratio 0.00; PSI drifted on 2 slots (Total Bwd Bytes, Flow Bytes/s)"}
```

- **Flows until drift:** fired at `samples_processed=3008` → **192 flows into
  the campaign (~16 s at 12 f/s), i.e. during the warmup phase — *before* a
  single DoS flow had arrived** (attack_ratio still 0.00 in the detail string).
  Detector: **PSI** (slots 5 + 14 crossed PSI>0.25 in the same batch → ≥2-slot rule).
  Root cause: `attack_campaign.py`'s warmup "web-" envelopes are a different
  normal distribution than `normal_traffic.py`'s envelopes — PSI honestly
  caught the generator switch as covariate shift. The *attack* then produced
  the dramatic climb: `attack_ratio_recent` 0→1.00, PSI peaks s5=13.58 /
  s14=11.93 / s1=11.16 / s44=4.91.
- `DDM_pseudo_error.drift_signal=True` once rule-override DoS labels landed
  (model disagrees with every override → pseudo-error 1.0 — expected per T08).
- `ADWIN_attack_ratio` and `PageHinkley` never signaled this run — PSI beat
  them to the latch, and events are suppressed while `_drift_active`
  (repeat-spam suppression verified: 1 event over 1,068 post-fire flows).
  PH needs ~126 batches of elevated attack_ratio; only ~45 dos batches ran.
- Adapter consumed the pending event: `/adaptation.last_event` =
  `skipped — insufficient buffer: fewer than 2 distinct classes` (buffer was
  all-Normal at fire time). No promotion → latch stays `drift` — correct §9
  semantics, and good for the demo banner.

### 3. PERSISTENCE — Flask restart

```
$ kill Flask; restart with identical env
log → "drift state restored: 4004 samples, 1 events, active=True"
$ GET /concept-drift
→ status=active drift_state=drift drift_detected=True
  samples_processed=4004  last_drift_timestamp=2026-10-04T06:39:50Z
  drift_events=[same PSI event]  attack_ratio_recent=0.444  DDM=True KS=True
  PSI windows restored (s5=5.65, s14=2.58, …)
```

Event, latch, timestamp, attack-flag window, ref/recent PSI windows, DDM flag —
**all survived the restart**. `samples_processed` restored to 4004 vs live 4076:
state persists every 25 batches (+ on fire/reset), so the ≤2-batch tail is
lost — documented T01 behavior, not a bug. ✓

### 4. CONTRACT AUDIT — §8 field-by-field (`check_drift_api.py audit`)

**PASSED — 26/26 checks**, on both the post-restart *drifted* state and a
fresh-reset *warming_up* state:

- Top-level keys **exactly** the §8 set (no missing, no extras): `status`,
  `drift_detected`, `drift_state`, `samples_processed`,
  `samples_processed_since_retrain`, `last_drift_timestamp`,
  `attack_ratio_recent`, `detector_algorithms`, `labrooms_features_drift`,
  `drift_events`.
- `status` ∈ {warming_up, active}; `drift_state` ∈ {stable, warning, drift};
  `drift_detected` bool; counters int≥0; `last_drift_timestamp` ISO-Z str|null;
  `attack_ratio_recent` float 0–1.
- `detector_algorithms` = exactly {ADWIN_attack_ratio{status,estimation,width,
  drift_signal}, PageHinkley{status,sum_val,threshold,drift_signal},
  DDM_pseudo_error{status,error_rate,warning_level,drift_signal},
  KS_Test{status,stat,p_value,drift_signal}} — all types verified incl. null
  paths (warning_level/stat/p_value null pre-data).
- `labrooms_features_drift` = exactly 5 rows, slots {1 Flow Duration,
  4 Total Fwd Bytes, 5 Total Bwd Bytes, 14 Flow Bytes/s, 44 HTTP Status Code},
  `drift`=PSI float, `status` ∈ {stable, minor_shift, drifted}.
- `drift_events` ≤20, newest-first, every event has exactly
  {timestamp, signal, detector, samples_processed, detail}.

## Outputs produced

- Live proof: baseline stable → campaign → **latched drift**, event recorded,
  state survives restart, contract conforms on real output.
- Measured: warming_up→active at 500 samples; drift fired at n=3008 (192 flows
  into campaign warmup); first detector = **PSI** (slots 5+14); PSI peaks
  13.58/11.93 during dos; attack_ratio_recent peaked 1.00; persist granularity
  = 25 batches (72-flow tail unpersisted at restart).

## Deviations from spec

1. **Baseline run rate raised** (`--interval 0.5 --batch-size 16`, 31 f/s vs
   spec'd defaults) — needed ≥500 flows to exit `warming_up` inside 90 s.
   Spec's "≥60 s" satisfied (90 s, 2816 flows).
2. **Attack at `--rate 12 --batch-size 12`** (vs default 6) — same phase
   durations; faster per-phase sample count. Scenario unchanged (dos =
   warmup→dos→cooldown).
3. None in shipped code — verify-only task, nothing patched.

## Handoff notes for dependent tasks

- For **TASK-12 (verify adaptation)**: the auto-trigger *consumed* my drift
  event but **skipped** (buffer was single-class at fire time — drift fired on
  warmup covariate shift before any attack labels existed). To get a real
  auto-promotion, T09's repro still works: ~550 LBL normal + ~150 LBL attack
  burst — or let the attack land *before* PSI fires (see next note).
- For **TASK-17/18 (demo/runbook)**: **mixed-generator gotcha** — baseline on
  `normal_traffic.py` then `attack_campaign.py --scenario dos` fires drift
  during *warmup* (its normal envelopes differ → PSI shift, attack_ratio 0.00).
  For the clean "attack causes the banner" narrative either (a) run the
  campaign's mixed scenario so warmup+dos blend (still fires pre-attack — PSI
  is honest), or (b) build baseline with the same generator, or (c) accept and
  demo the fact: "PSI caught a distribution change before the attack even
  started." Numbers for the script: expect latch ~15–20 s into any generator
  switch, event detail names the slots.
- For **TASK-14 (ConceptDrift.jsx)**: live field vocabulary = `status` ∈
  {warming_up, active}, `drift_state` ∈ {stable, warning, drift}, feature
  `status` ∈ {stable, minor_shift, **drifted**} (third value real — renders
  red-tier), detector `status` strings are free-form-ish ("stable"/"nominal"/
  "warning"/"drift" observed); `warning_level`/`stat`/`p_value`/`last_drift_
  timestamp` are **null** until data exists — UI must null-guard.
- `GET /concept-drift` ≈1 ms server-side (unchanged); full audit script lives
  at `ml/scripts/check_drift_api.py` — reusable for T12/T17 smoke checks.
- Persist granularity is 25 batches — expect restart to lose <2 batches of
  samples (observed −72 flows); events/latch always persist.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT §A "Stack last state": all three up — mongod :27017, Flask :5001
  (DEMO_MODE=1, post-reset clean v1, warming_up n=0), Node :5000. Stack was
  fully DOWN at T11 start; T11 agent started all three.
- CONTEXT fact: drift verified E2E on the real pipeline — PSI fired 192 flows
  into `attack_campaign.py` warmup (slots 5+14, "generator-switch" covariate
  shift); DoS phase then drove attack_ratio→1.0 and PSI peaks s5=13.6/s14=11.9;
  latch suppresses repeat events (1 event over 1,068 post-fire flows); restart
  restored latch+event+windows (persist = every 25 batches, ±2-batch tail).
- CONTEXT fact: `/concept-drift` §8 contract audited field-by-field, PASSED on
  drifted + fresh states (`ml/scripts/check_drift_api.py audit` — 26 checks);
  feature status vocab is stable/minor_shift/drifted; several detector subfields
  are null pre-data — UI must null-guard.
- Open issue: none.
- TRACKER row status: `done` — "Drift verified E2E: 2,816-flow baseline stable
  (PSI<0.10, warming_up→active @500), PSI drift latched at n=3008 on dos
  campaign (attack_ratio→1.0, PSI peaks 13.6/11.9), latch+event survive restart,
  §8 contract audit PASSED field-by-field"
