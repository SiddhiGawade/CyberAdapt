# HANDOFF — TASK-17 — E2E Demo Rehearsal ×2

| | |
|---|---|
| **Task** | TASK-17 — E2E Demo Rehearsal ×2 (timed, measured) |
| **Status** | `done` |
| **Wave** | D — sequential |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | ALL (T01–T16) — esp. T11 warmup-PSI caveat, T12 priming choreography, T13 demo arc, T14–T16 page bindings |

---

## Files created

- `documentation/member3/handoffs/TASK-17_e2e-rehearsal.md` — this handoff

## Files modified

- none — **zero checkpoint failures → zero fixes required.** No `ml/scripts/`
  edits, no source patches. (Reused existing `check_*_api.py` scripts only.)

## Stack state (as found / left)

- **Found: whole stack DOWN again** — no LISTENING sockets on 27017/5000/5001/3000
  (CONTEXT §A said T13 left it up; same session-death pattern T11/T12/T13 all
  hit). All ports free → started all four per §5.7: `mongod --dbpath
  %USERPROFILE%\mongodb-data` · Flask `MODEL_PATH=…champion_model.joblib
  PREPROCESSOR_PATH=…preprocessor.joblib DEMO_MODE=1 PORT=5001 python -m ml.api`
  · `npm run dev` in `server/` · `npm run dev` in `client/`.
- **Left running:** mongod :27017, Flask :5001 (DEMO_MODE=1, **post-reset
  clean**: v1, buffer 0, drift n=0), Node :5000, **client :3000 (now running —
  Vite dev server)**. Stale `adaptive_champion/preprocessor_vN.joblib` removed
  post-run (T09/T12 convention).
- **Env quirk recorded:** Vite on this box binds IPv6 `[::1]:3000` only —
  `localhost:3000` works (dual-stack), `127.0.0.1:3000` refuses. Use
  `http://localhost:3000` for the dashboard, `127.0.0.1` for API checks.

## Setup checks (both runs)

```
$ POST /api/telemetry/admin/reset (Node+JWT)
→ {"cleared":["drift_state","buffer","history","model_artifacts","eval_window"],"status":"reset"}
→ /concept-drift: warming_up stable n=0 events=0   ✓

$ cd client && npm run build          (C2's deferred check — spec gate)
→ ✓ 2183 modules transformed. ✓ built in 6.11s   (pre-existing >500 kB chunk
   warning only — known non-issue)
```

---

## RUN 1 — shake-out (all timings measured, UTC)

### Act 1 — Baseline
`normal_traffic.py --interval 0.5 --batch-size 16 --duration 60`
→ **1,888 flows / 60.0 s (31.5 f/s), 0 errors**
- `warming_up→active` at n≈500 ✓ (status=active at n=928 poll)
- `drift_state=stable`, `attack_ratio=0.0`, all PSI <0.10 (max s4=0.0976) ✓
- `buffer=1888/5000 hc:1888` — high_confidence climbing ✓
- Mongo `threatLabel` = 100% "Normal Traffic" (all-time agg: 8,872 docs,
  minConf 0.991) — Live Traffic label feed ✓ **(API-level)**

### Act 2 — Reveal (priming per T12 choreography)
`check_adaptation_api.py seed dos 90 30` @ **07:19:46.237**
- **Drift event @ 07:19:47Z** (n=1948, PSI 4 slots, `attack_ratio 1.00`) —
  **time-to-drift ≈0.8 s after attack-seed start**
- → auto **PROMOTION v1→v2** same-second (**event→promotion <1 s**; T12's
  daemon measurement ≈0.13 s) — buffer@trigger **1,948** (1,888 hc + 60 tag),
  gates 4/4, champ macro_f1 0.4922→cand 1.0, DoS recall 1.0
- `adaptive_champion_v2.joblib` (41,700 B) + preprocessor + `active_model.json`
  + `/model-info.version=v2` ✓

`attack_campaign.py --scenario mixed --rate 12 --batch-size 6` @ 07:21:28
→ **2,880 flows / 240.9 s, 0 errors** (warmup 360, dos 540, bf 540, sqli 540,
exfil 540, cooldown 360)
- **Event 2 @ 07:21:43** (warmup PSI n=2164, atk 0.00 — generator-switch
  caveat) → **auto v2→v3** (116 s post-trigger → cooldown elapsed)
- **Event 3 @ 07:21:59** (dos-phase PSI n=2350, atk 1.00) → consumed,
  `skipped — cooldown active (44s remaining)`; latch stays `drift` ✓
- `attack_ratio_recent` → **1.00**; PSI peaks **s1=9.32 s5=12.09 s14=5.73
  s44=10.24** ✓ (slot-1/5 jump checkpoint)
- DDM=True + KS=True sustained through attack phases; **ADWIN=True flicker
  caught live @ n=4708** (cooldown decay, atk 0.59); **PH=True @ n=4840** —
  the "ADWIN_attack_ratio fired" checkpoint verified (1 s polling)
- recent-flows during dos phase: **100/100 = DoS** → Live Traffic flood +
  Overview `AttackAlertBanner` data ✓ **(API-level)**

### Act 3 — Adaptation
- FORCE via real Node+JWT path (`proxytriggerx2`): **#1 → 202 accepted**
  (buffer 4,858), **#2 → 409 busy** — `adaptation_in_progress` proven
  server-side by the 409 ✓
- That retrain was **honestly REJECTED** (hist row 3, promoted:false):
  `gate_emerged_recall` (WA 0.368<0.70) + `gate_normal_fpr` (0.60>0.05) FAIL;
  `macro_f1_delta +0.3264` + `gate_bal_acc` PASS — gates vetoed a worse
  candidate on the attack-heavy buffer (train 3,643/val 1,215 chrono split).
  Champion stayed v3 — **the rejection path is real and demo-worthy**.

### Act 4 — Recovery + metrics
- Recovery `normal_traffic --lbl-tag` 25 s (752 flows): fired **"world healed"
  PSI events 4–5** @ 07:27:32/35 (atk 0.00, post-rejection latch was clear) →
  event-4 auto retrain → **REJECTED** (same gates: WA 0.323, fpr 0.5895) →
  event-5 `skipped — cooldown (58s)`.
- Predictions under v3: LBL-normal window 500/500 acc=1.0000; campaign normals
  98.3% correct.
- Eval: CM populated (row0 diag 500 off 0), per-class DoS/BF/WA/Normal rows,
  `pre_post_adaptation` populated post-promotion (pre {1.0,440}/post {1.0,60}
  at the moment of promotion; later snaps show pre empty — window slides past
  `last_adaptation` after ~500 rows — honest).

### Robustness (Run 1)
- Flask restart mid-state → **v3 + hist=4 + events=5 + eval 500 + latch drift +
  PSI windows + label_sources all restored** via `active_model.json` +
  `drift_state.json` + `eval_window.jsonl` (buffer ring intentionally 0,
  `latency_p95_ms`→0 as documented). ✓
- Flask killed → ingest **202** (fire-and-forget tolerates ML down), all Node
  GET proxies **503** + POST trigger **503** → UI offline path feeds. ✓
- `POST /adaptation/trigger` ×2 → **202 → 409** ✓
- `POST /admin/reset` → 6-entry cleared list → v1/n0 → story repeatable. ✓

---

## RUN 2 — timed clean (spec cadence, all timings measured)

### Act 1 — Baseline
`normal_traffic.py --interval 2 --batch-size 8 --duration 140` (spec command)
→ **560 flows / 140.0 s (4.0 f/s), 0 errors**
- `warming_up→active` at ~n=552; end-state n=560 stable, PSI ~0.005, buffer
  hc:560. **T18 note: at spec cadence the predict/monitor path keeps exact
  pace (n == flows sent).**

### Act 2 — Reveal
`seed dos 90 30` @ **07:32:56.124**
- **Drift event @ 07:32:57Z** (n=620, PSI 3 slots, atk 1.00) —
  **time-to-drift ≈0.9 s**
- → auto **v1→v2** same-second (**event→promotion <1 s**), buffer@trigger
  **620** (560 hc + 60 tag), gates 4/4, champ f1 0.4746→cand 1.0
- Eval immediately post-promo — **real split captured**: `pre {f1:1.0, n:440}
  post {f1:1.0, n:60}` `last_adaptation=07:32:57Z`
- FORCE ×2 → **202 → promoted v2→v3 @ 07:33:17** (deterministic on
  normal-heavy buffer) + **409 busy** ✓

`attack_campaign.py --scenario mixed --rate 12 --batch-size 6` @ 07:34:2x
→ 2,880 flows / ~241 s, 0 errors
- **Event 2 @ 07:34:42** (warmup PSI n=836, atk 0.00) → **auto v3→v4**
  (85 s post-FORCE → cooldown elapsed)
- **Event 3 @ 07:34:58** (dos PSI n=1028, atk 1.00) → `skipped — cooldown
  active (44s)`; latch stays `drift`
- attack_ratio → 1.00; PSI peaks s1=8.97 s5=12.01 s14=7.31 s44=10.24 ✓
- ADWIN: no `=True` catch under 2 s polling (estimation climbed to ~1.0 during
  attack; flicker is a 1-batch flag — Run 1 caught it at 1 s polling; see
  checkpoint table note)
- Per-phase labels under v4: dos DoS **540/540**, bf BF **540/540**, sqli WA
  **540/540**, exfil WA **540/540**, warmup Normal 357+BF 3, cooldown Normal
  354+BF 6 ✓

### Act 4 — Recovery
- Recovery `normal_traffic --lbl-tag` 25 s (800 flows): **no new events** —
  event-3's *skipped* latch suppresses all further auto-events (mechanic:
  latch clears only on completed retrain or reset). Run 1's rejected-retrain
  had cleared it, so recovery events fired there. **T18 runbook note.**
- Eval final: LBL-normal 500/500 acc=1.0000 under **v4** ✓
- End state: **v4, hist=3** (auto v2 · manual v3 · auto v4), buffer 4,330
  (hc 560 + tag 3,770), drift latched with 3 events — then `/admin/reset` →
  clean.

---

## Checkpoint table (spec §Act1–4 + robustness)

| Checkpoint | Result | Evidence |
|---|---|---|
| Setup: reset → n≈0; `npm run build` clean | ✅ | 6-entry cleared ×2; 2183 modules 6.11 s |
| A1: Live Traffic Normal labels | ✅ API-level (Mongo + recent-flows) | 100% Normal, conf ≥0.99 |
| A1: `drift_state:stable`, PSI<0.10, detectors green | ✅ | max PSI 0.0976 (R1) / 0.005 (R2) |
| A1: buffer current_size + high_confidence climbing | ✅ | 1,888 (R1) / 560 (R2) hc |
| A2: Live Traffic floods DoS/BF/WA ~5 s | ✅ API-level | recent-flows 100/100 DoS; per-phase 540/540 |
| A2: red banner data `drift_state:drift` + ≥1 event | ✅ | latched drift, 3–5 events/run |
| A2: `ADWIN_attack_ratio` fired | ✅ (R1 live-caught; R2 see note) | `ADWIN=True` @ n=4708 R1 cooldown; 1-batch flicker — needs ≤1 s polling or a sharp transition; PSI always beats it to the event latch |
| A2: slot-1/5 PSI visibly jumps | ✅ | peaks s1 8.97–9.32, s5 12.01–12.09 |
| A2: Overview attack banner | ✅ API-level (data feed verified; component consumes same `recent-flows` prop) | 100% attack labels in window |
| A3: `adaptation_in_progress` true→false | ✅ (via 409 proof; retrain ~0.15–0.5 s too fast to poll) | `{"status":"busy"}` on 2nd trigger |
| A3: `champion_version` bump + history row + 4 gates | ✅ | v1→v2→v3→v4 across runs; `gates_passed` all-true rows |
| A3: `adaptive_champion_vN.joblib` on disk | ✅ | v2/v3/v4 artifacts written per run |
| A3: FORCE → 202 then 409 | ✅ ×2 runs (Node+JWT path) | Run 2 promoted v2→v3 on #1 |
| A4: predictions correct under new champion | ✅ | LBL-normal acc 1.0; attack phases 100% under v3/v4 |
| A4: pre/post F1 (or honest delta) | ✅ | R2 post-promo split pre 440/post 60 (f1 1.0/1.0); slides to post-only >500 rows later (honest, recorded) |
| A4: confusion matrix + per-class populated | ✅ | 7×7 live; CM row0 off-diag = honest FPs |
| Robust: restart survives drift history + version | ✅ | v3+hist4+events5+eval500 restored |
| Robust: kill Flask → degrade gracefully, ingest 202 | ✅ | ingest 202; proxies+trigger 503 |
| Robust: trigger×2 → 409 | ✅ | both runs |
| Robust: `/admin/reset` → repeatable | ✅ | 6-entry cleared → v1/n0 ×3 |

**UI-level vs API-level:** all checks above were verified at HTTP/API + Mongo
level. A Vite browser preview (`http://localhost:3000`) was opened for the
operator to eyeball — page bindings were already code-verified in T14–T16
(same JSON fields), and the data feeding every page element was confirmed
live here.

## Key measured numbers for T18's runbook

| Metric | Run 1 | Run 2 |
|---|---|---|
| Baseline | 1,888 fl/60 s @31.5 f/s | 560 fl/140 s @4.0 f/s (spec cadence) |
| time-to-drift after attack start | **≈0.8 s** (2nd seed batch) | **≈0.9 s** |
| drift→promotion | **<1 s** (same-second; daemon ~0.13 s per T12) | **<1 s** |
| buffer at 1st trigger | 1,948 | 620 |
| auto-promotions | v1→v2, v2→v3 | v1→v2, v3→v4 (+manual v2→v3) |
| gates on healthy buffer | 4/4 PASS, champ f1 ~0.48→1.0 | 4/4 PASS |
| FORCE on attack-heavy buffer | REJECTED (WA recall 0.37<0.70, fpr 0.60>0.05) | — (pressed early, promoted) |
| time-to-promotion wall (seed start→v2) | ~1.4 s | ~1.5 s |
| campaign (mixed @12 f/s) | 2,880 fl/241 s, 6 events/promotions+skips | same |
| per-phase labels | attack 100% (540/540 each); normals ~98% | identical |
| PSI peaks | s1 9.32 s5 12.09 | s1 8.97 s5 12.01 |

## Deviations from spec

1. **Priming before the campaign** (per task's own choreography hint +
   T11/T12 caveat): buffer must hold ≥200 labeled + ≥30 non-Normal BEFORE the
   first drift fires, else warmup-PSI skips auto-promotion and cooldown eats
   the next event. Used `check_adaptation_api.py seed dos 90` through the real
   Node ingest path — the seed itself is the attack reveal and fires the first
   promotion. The spec's literal order (baseline → `attack_campaign mixed`)
   reproduces T11's skip outcome by design.
2. **Campaign rate** `--rate 12 --batch-size 6` (2 monitor batches/s vs spec's
   implicit 1/s) — shortens ADWIN/PH detection latency to fit the demo window;
   phase durations unchanged.
3. **Spec's "history row trigger 'ADWIN drift'"** — reality: every auto event
   this session was `PSI drift alert (feature_psi)` (PSI is the fast detector;
   ADWIN is the ~65-batch backstop that flickers one update, never wins the
   latch first). Recorded as spec-vs-reality, not a bug.
4. **Reset `cleared` list is dynamic** — first post-promotion reset shows
   `active_model`; subsequent resets show 5 entries (pointer already gone).
   Documented by T13, re-confirmed.
5. **`eval_window` pre goes empty >500 rows post-promotion** — window slides;
   honest split only exists near the promotion. Runbook should check eval
   right after the bump for a populated pair.

## Handoff notes for dependent tasks

- **For TASK-18 (demo runbook)** — recommended ~4.5 min arc, Run-2 proven:
  reset → `normal_traffic --interval 2 --batch-size 8 --duration 140` (~560
  flows, active@500) → `check_adaptation_api.py seed dos 90 30` (drift+promo
  in ~1 s; FORCE ×2 now for 202→409 while buffer is normal-heavy — **deterministic
  promote**; on an attack-dominated buffer the same press REJECTS — either is
  a talking point, script it deliberately) → wait ~60 s (cooldown) →
  `attack_campaign --scenario mixed --rate 12 --batch-size 6` (~4 min:
  warmup-PSI second promotion, dos latch+skip, floods, PSI peaks ~9–12,
  ADWIN/PH flicker on cooldown decay — poll drift ≤1 s if you want to catch
  `ADWIN=True` live) → recovery normals (fires "world healed" events only if
  the latch is clear — see below).
- **Latch mechanics the runbook must state:** a *skipped* drift event holds
  the latch — no further auto-events until a retrain completes (promoted OR
  rejected) or `/admin/reset`. A *completed* retrain clears it via
  `reset_reference()` (drift_state returns stable). Recovery-normal PSI events
  therefore only fire after a clear latch.
- **Buffer composition drives gates:** normal-heavy buffer → retrains promote
  deterministically (delta ≥ −0.01); attack-heavy buffer → honest rejections
  (`emerged_recall`/`normal_fpr` on the chrono validation tail — observed
  twice, both on ~3.7 k-tag buffers).
- **`warming_up` needs ≥500 samples** before drift can latch; at spec cadence
  (4 f/s) that's ~125 s of baseline — the "~2 min" Act-1 is calibrated right.
- Reusable checkers: `ml/scripts/check_{drift,adaptation,evaluation}_api.py`
  (status/poll/audit/snap/seed/trigger/proxytriggerx2/waitpromo).
- Mongo label-check field is `receivedAt` (not `ingestedAt`); sensorId filters
  per-generator (`normal-traffic-gen`, `attack-campaign-<phase>`, `t12-seed`,
  `t17-flaskdown`).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT §A "Stack last state": all four up — mongod :27017, Flask :5001
  (DEMO_MODE=1, post-reset clean v1/n0), Node :5000, **client :3000** (Vite;
  binds ::1 — use `localhost`). Stack was fully DOWN at T17 start; T17 agent
  started all four.
- CONTEXT fact: E2E rehearsed ×2 with timings — spec-cadence baseline (4 f/s,
  ~560 fl) → `seed dos 90` → drift+auto-promotion in <1 s (buffer ~600–1,900);
  campaign mixed @12 f/s → 2nd auto-promotion on warmup PSI + cooldown-skip on
  next event; FORCE×2 → 202/409; restart/kill/reset all survive; `npm run
  build` green.
- CONTEXT fact: ADWIN/PH `drift_signal` is a per-update flicker (one batch) —
  caught live at 1 s polling (ADWIN @ cooldown decay); events latch only via
  the first detector (PSI in practice). A *skipped* event holds the latch and
  blocks further auto-events until a completed retrain clears it.
- CONTEXT fact: manual/auto retrains on attack-dominated buffers honestly
  REJECT (`gate_emerged_recall`+`gate_normal_fpr` on chrono val tail); on
  normal-heavy buffers they promote deterministically.
- CONTEXT fact: Vite dev server binds `[::1]:3000` on this box — `127.0.0.1`
  fails; use `localhost:3000` for the dashboard.
- Open issue: none.
- TRACKER row status: `done` — "E2E rehearsal ×2 passed: baseline→prime→campaign→promotion→recovery all live; measured drift ~0.9 s, promotion <1 s, 3 promotions (2 auto + 1 manual) R2, rejection path live R1, restart/kill/reset verified, build clean"
