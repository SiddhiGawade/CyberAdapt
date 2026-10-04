# HANDOFF — TASK-13 — Verify Evaluation E2E (live stack)

| | |
|---|---|
| **Task** | TASK-13 — Verify Evaluation E2E (live stack) |
| **Status** | `done` |
| **Wave** | C1 — sequential |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-10 (`/evaluation` wiring, eval_window.jsonl semantics, restart/reset behavior), TASK-12 (promotion choreography — prime ≥30 non-Normal labels BEFORE drift; cooldown semantics; `check_adaptation_api.py` reused for seed/predict/waitpromo) |

---

## Files created

- `ml/scripts/check_evaluation_api.py` — verification helper (verify-only:
  no `ml/api.py`/`ml/src/*` touched). Modes: `snap [label]` (compact snapshot:
  size, metrics, CM row-0 diag/off, per-class supports, pre/post block,
  champion) · `full` (raw JSON) · `audit` (49-check §8 field-by-field contract
  audit incl. cross-invariants cm_total==size, Σsupport==size,
  pre+post==size) · `file` (eval_window.jsonl + adaptation_history.json stats)
  · `reset`. Uses `127.0.0.1`, ASCII-safe output.

## Files modified

- none (verify-only task)

## Stack state (as found / left)

- **Found: whole stack DOWN again** — no LISTENING sockets on 27017/5000/5001
  (CONTEXT.md §A said T12 left it running; same session-death pattern T12 hit
  after T11). All ports free → started all three per §5.7:
  `mongod --dbpath %USERPROFILE%\mongodb-data --bind_ip 127.0.0.1` · Flask
  `MODEL_PATH=ml/artifacts/models/champion_model.joblib PREPROCESSOR_PATH=ml/artifacts/models/preprocessor.joblib DEMO_MODE=1 PORT=5001 python -m ml.api`
  · `npm run dev` in `server/`. Booted into post-reset clean v1 (n=0,
  eval_window.jsonl absent, adapter_state last_event=null after re-reset).
- **Left running:** mongod :27017, Flask :5001 (DEMO_MODE=1, **post-reset
  clean**: v1, buffer 0, drift n=0, eval window 0), Node :5000. Client :3000
  not started. Orphaned `adaptive_champion_v2`/`adaptive_preprocessor_v2`
  joblibs removed post-verification (T09/T12 convention).

## Verification run — protocol order

### 0. Cold start — empty window + contract audit (insufficient regime)

```
$ check_evaluation_api.py snap cold-start
size=0/500 since=None insuff=True acc=0 p=0 r=0 f1=0 p95=0.00ms
cm row0 diag=0 | support={} | pre=f1:0.0/n:0 post=None last=None | v1
$ check_evaluation_api.py audit   → PASSED (all checks; insufficient_data:true
                                   present since size<30)
```

### 1. Normal traffic — `normal_traffic.py` via real Node ingest, 45 s

```
$ python sensor/normal_traffic.py --key ca_live_5d14… \
    --url http://127.0.0.1:5000/api/telemetry/ingest \
    --interval 0.5 --batch-size 16 --duration 45
→ 87 batches, 0 errors, 1,392 flows accepted (30.9 flows/s)

$ check_evaluation_api.py snap after-normal-45s
size=500/500 since=2026-10-04T07:05:05.710020Z insuff=False
acc=1.0000 p=1.0000 r=1.0000 f1=1.0000 p95=42.66ms
cm row0 diag=500 off=0 | total=500 offdiag=0
support={'Normal Traffic': 500}
pre_post: pre=f1:1.0/n:500 post=None last=None
$ file → eval_window.jsonl 500 lines, versions={'v1':500}
```

Window grew on hc-Normal pseudo-labels only (no --lbl-tag): every row is
y_true=0/y_pred=0 → perfectly diagonal. `latency_p95_ms` populated (42.66 ms —
this is the ingest→Node→Flask round path latency per /predict batch).
Drift monitor reached active (n=1392), buffer 1,392 hc labels.

### 2+3. Attack burst → per-class rows + REAL auto-promotion (T12 choreography)

Buffer already ≥200 labeled; primed ≥30 non-Normal LBL labels first:

```
$ check_adaptation_api.py seed dos 90 30        # LBL::DoS via Node ingest
+30 → buffer=1422 tag:30  drift_state=warning
+30 → drift event FIRED (feature_psi) → consumed mid-/predict
    → PROMOTION v1 -> v2 (champ macro_f1 0.4895 -> cand 1.0000,
       DoS recall 1.0000, all gates)   buffer≈1,452 (1,392 hc + 60 tag-DoS)
+30 → version=v2  (latch cleared post-promotion, reset_reference ran)
$ seed bruteforce 60 30 → +60 LBL::Brute_Force  (buffer tag:150)
$ seed sqli 60 30       → +60 LBL::Web_Attacks; 2nd PSI event fired
    → last_event=skipped — cooldown active (50s remaining)   (60 s auto-gate)
```

```
$ snap post-attack-promotion
size=500/500 acc=1.0000 f1=1.0000 p95=42.62ms
cm row0 diag=290 off=0 | total=500 offdiag=0
support={'Brute Force':60,'DoS':90,'Normal Traffic':290,'Web Attacks':60}
pre_post: pre=f1:1.0/n:320 post=f1:1.0/n:180 last=2026-10-04T07:05:39Z  ← POPULATED
adaptation_history.json: 1 entry, promoted ts=2026-10-04T07:05:39Z (matches)
```

### 3b. Metric-movement proof — 120 `LBL::Normal_Traffic` flows (tagged truth)

Self-consistent pseudo-labels (hc/rule/attack-tags) can only yield 1.0; tagged
normal exposes honest model error (~1.7% FP rate observed on v2):

```
$ seed normal 120 40
$ snap post-lbl-normal
size=500/500 acc=0.9960 p=0.9919 r=0.9983 f1=0.9950 p95=42.61ms
cm row0 = [288,0,0,0,2,0,0]   ← 2 Normal→BruteForce FPs (only off-diag cells)
support={'BF':60,'DoS':90,'Normal':290,'WA':60}
per_class: BF precision 0.9677 (2 FP), recall 1.0; Normal recall 0.9931;
           DoS/WA perfect 1.0; DDoS/PortScan/Bots all-zero rows
pre_post: pre=f1:1.0000/n:200 post=f1:0.9938/n:300 last=07:05:39Z
          → measured Δf1(post−pre) = −0.0062
$ audit → PASSED (all checks, populated regime)
```

### 4. Flask restart — window survives (eval_window.jsonl)

```
$ kill Flask; restart same env
boot log → LiveEvaluator: restored 500 labeled row(s) from eval_window.jsonl
boot log → LiveAdapter restored: 1 history, version v2, {hc:1392 tag:330}
boot log → Boot-restoring promoted champion v2 via active_model.json
boot log → drift state restored: 1572 samples, 2 events (≤persist-tail loss
           vs n=1722 — documented T11: every-25-batches persist)
$ snap post-restart
size=500 acc=0.9960 f1=0.9950 p95=0.00ms   ← p95 resets (in-memory deque, known)
cm/supports/pre_post ALL IDENTICAL to pre-restart | champion=v2
$ audit → PASSED
```

### 5. `/admin/reset` → insufficient_data + threshold boundary

```
$ reset → 200 {"cleared":["active_model","drift_state","buffer","history",
                          "model_artifacts","eval_window"]}
post-reset: size=0 insuff=True all metrics 0, champion=v1,
            eval_window.jsonl DELETED, adaptation_history.json = []
$ predict dos 15 → size=15 insuff=True   (p95 already live 65.40ms;
                   pre.samples=15 — honest counters even in skeleton)
$ predict dos 20 → size=35 insuff GONE; acc=1.0 support={DoS:35}
   → <30 boundary verified exactly; recording resumes immediately post-reset
$ audit (35-row single-class regime) → PASSED, 49 checks, 0 FAIL
```

### Cleanup for next agent

Second `/admin/reset` → clean v1/n=0/buffer 0/window 0 (this reset's `cleared`
list = 5 entries, no `active_model` — pointer already gone; honest list).
Removed orphaned `adaptive_*_v2.joblib` artifacts.

## Outputs produced

- **Live metrics track traffic**: window 0→500 on labeled traffic only;
  acc 1.0000 → 0.9960 when tagged-normal FPs landed; per_class gained DoS(90)/
  BF(60)/WA(60) rows with real precision/recall; CM diagonal-heavy (498/500).
- **pre_post_adaptation populated by a REAL auto-promotion**: PSI drift →
  v1→v2 (buffer ≈1,452; champ f1 0.4895→cand 1.0). Split: pre {f1 1.0, n 200},
  post {f1 0.9938, n 300}, last_adaptation=2026-10-04T07:05:39Z — matches
  adaptation_history.json's promoted ts exactly. pre+post == window.size.
- **Persistence**: 500 rows + identical metrics + split + v2 champion across
  restart; `latency_p95_ms` 0.0 until new batches (documented in-memory deque).
- **Reset**: `eval_window` in cleared list; file deleted; insufficient_data:true;
  <30 boundary verified at 15 vs 35 samples.
- **§8 contract audit PASSED in 3 regimes** (cold-insufficient / populated-500 /
  post-reset-35): exact top-level set + `insufficient_data` only when <30;
  dataset string exact; window {size,capacity(500),since}; overall_metrics exact
  5 keys; per_class always emits all 7 classes (zero-support rows — superset of
  §8 example); CM 7×7 ints, total==size; class_names exact §8 order; pre_post
  invariants hold.

## Deviations from spec

1. **Stack was DOWN at start** (again) — CONTEXT §A said T12 left it up;
   services die between sessions. Started all three myself; no code impact.
2. **`eval_window.jsonl` row `version` is always "v1"** — §9.1 `batch_record`
   carries no version field, so the evaluator's `DEFAULT_MODEL_VERSION` is
   used even for post-promotion rows. Not contract-visible (§8 exposes no
   row version); cosmetic only. Flagging so T17 isn't confused by all-v1 rows
   in the file.
3. **Insufficient skeleton carries real values in 3 fields** —
   `window.size`, `pre_post_adaptation.pre.samples`, and `latency_p95_ms`
   are honest (15/15/65.4 ms observed at n=15) while the metric block is
   zeroed. Contract-tolerated; T16's empty state already handles it.
4. **Promotion choreography**: reused T12's — prime 60 `LBL::DoS` (buffer
   already had ≥200 hc-Normal) → the seed itself fired PSI and promoted.
   Second PSI event during sqli seed → `skipped — cooldown (50s)`, latch
   stayed `drift` (T11-documented semantics).
5. Nothing in shipped code — verify-only task, nothing patched.

## Handoff notes for dependent tasks

- For **TASK-17/18 (rehearsal/runbook)**: full evaluation demo arc is cheap —
  ~45 s `normal_traffic.py` (fills window + warms monitor past 500) →
  `seed dos 60-90` (primes non-Normal labels AND fires PSI → auto v1→v2) →
  optional `seed bruteforce/sqli` for class variety → `seed normal ~120`
  produces honest non-1.0 metrics (FPs → off-diagonal CM cells) and a non-zero
  pre/post Δf1. Reusable: `check_evaluation_api.py snap|audit|file|reset`.
- For **TASK-16 (`Evaluation.jsx`)**: live audit confirms the exact §8 shape
  in all regimes; `per_class_metrics` always lists all 7 classes (zero rows
  for absent classes — render, don't filter); `post`/`last_adaptation` are
  `null` until first promotion; after reset or restart `latency_p95_ms` reads
  0.0 transiently — already documented.
- For **everyone**: `eval_window.jsonl` row `version` never advances past
  "v1" (no version in `batch_record`) — don't build on it. The window's
  `since` = oldest row ts; pre/post split is over the CURRENT 500 rows only
  (pre rows rotate out as the window slides — post eventually fills it).
- The `/admin/reset` `cleared` list is honest/dynamic — second consecutive
  reset omits `active_model` (pointer already deleted).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT §A "Stack last state": all three up — mongod :27017, Flask :5001
  (DEMO_MODE=1, post-reset clean v1/n=0), Node :5000. Stack was fully DOWN at
  T13 start again; T13 agent started all three.
- CONTEXT fact: evaluation verified E2E — window grew on labeled traffic only
  (1,392 hc-Normal → 500/500), acc moved 1.0→0.996 on tagged-normal FPs,
  real PSI auto-promotion v1→v2 populated pre_post (pre 200/post 300,
  Δf1 −0.0062), 500 rows + v2 survived restart, reset→insufficient_data:true,
  <30 boundary verified; §8 audit PASSED ×3 regimes
  (`ml/scripts/check_evaluation_api.py audit`).
- CONTEXT fact: `eval_window.jsonl` row `version` is always "v1" — §9.1
  batch_record carries no version; cosmetic, not contract-visible.
- CONTEXT fact: `/admin/reset` cleared list is dynamic — second consecutive
  reset shows 5 entries (no `active_model` when pointer absent).
- Open issue: none.
- TRACKER row status: `done` — "Evaluation verified E2E: metrics track traffic
  (acc 1.0→0.996 on FPs, attack per-class rows), real PSI promotion v1→v2
  populated pre/post (200/300, Δf1 −0.0062), 500-row window + v2 survive
  restart, reset→insufficient_data (<30 boundary exact), §8 audit PASSED in
  3 regimes (49 checks)"
