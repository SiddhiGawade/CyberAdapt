# TASK-17 — E2E Demo Rehearsal ×2

| | |
|---|---|
| **Wave** | D — **sequential** (after C1 + C2 merge; runs alone) |
| **Depends on** | T11–T16 all `done`/`partial`-with-accepted-notes in TRACKER.md |
| **Input handoffs** | ALL previous handoffs — every `partial`/`blocked` leftover must be resolved or explicitly carried before this task passes |
| **Files you may touch** | `ml/scripts/`, and small bugfixes ONLY if a checkpoint fails and the fix is unambiguous (record every such fix in the handoff) |
| **Files you must NOT touch** | docs/runbook files (T18/T19 own those) |
| **Goal** | Prove the whole Member-3 story end-to-end on the real stack — twice — with measured timings |

---

## Read first

1. `documentation/member3/CONTEXT.md` — all merged facts
2. ALL `handoffs/*.md` — leftover issues
3. `00_MASTER_PLAN.md` — §7 narrative, §8 contracts
4. Root `README.md` "How to Run"

## Rehearsal protocol — run the full sequence **twice**

Run 1 = shake out bugs (fix small things, record each fix). Run 2 = timed and
clean as if presenting. Every checkpoint must pass or carry a recorded
explanation.

### Setup (T-minus)

```bash
# 1. mongod running · server npm run dev :5000 · flask DEMO_MODE=1 + model
#    env vars :5001 · client :3000, logged in as admin@acme-test.local
# 2. POST /api/telemetry/admin/reset (JWT) → {"status":"reset"}
#    → GET /concept-drift shows samples_processed ≈ 0
# 3. cd client && npm run build   # frontend compiles clean (C2's deferred check)
```

### Act 1 — Baseline (~2 min)

```bash
python sensor/normal_traffic.py --key "ca_live_…" --interval 2 --batch-size 8
```
- [ ] Live Traffic fills with `Normal Traffic` labels
- [ ] Concept Drift: `drift_state: stable`, PSI < 0.10, detectors green
- [ ] Adaptation: buffer `current_size` climbing, `high_confidence` growing

### Act 2 — Attack (the reveal)

```bash
python sensor/attack_campaign.py --key "ca_live_…" --scenario mixed
```
- [ ] Live Traffic floods DoS / Brute Force / Web Attacks within ~5 s
- [ ] Concept Drift: red banner, `drift_state: drift`, ≥1 event entry,
      ADWIN_attack_ratio fired, slot-1/5 PSI visibly jumps
- [ ] Overview attack banner (existing component) also fires

### Act 3 — Adaptation (the payoff) — automatic; keep cursor on /adaptation

- [ ] `adaptation_in_progress` → true → false
- [ ] `champion_version` v1→v2; new history row: trigger "ADWIN drift", 4 gates PASS
- [ ] `ml/artifacts/models/adaptive_champion_v2.joblib` on disk
- [ ] FORCE ADAPTATION button works (hit once, observe 202; twice → 409 message)

### Act 4 — Recovery + metrics

- [ ] Normal generator still running → predictions correct under new champion
- [ ] Evaluation: `pre_post_adaptation` post ≥ pre F1 (or honest recorded delta)
- [ ] Confusion matrix + per-class populated on the page

### Robustness passes (once each)

- [ ] Restart Flask mid-demo → drift history + version survive
- [ ] Kill Flask → dashboard degrades gracefully, ingest still 202s
- [ ] `POST /adaptation/trigger` ×2 fast → second = 409
- [ ] `POST /admin/reset` → whole story repeatable

## Record in the handoff

Actual timings: time-to-drift after attack start, time-to-promotion, buffer
size at trigger, pre/post F1, per-phase label counts — T18's runbook needs
your measured numbers.

## Finish protocol (sequential — update shared files)

- `handoffs/TASK-17_e2e-rehearsal.md` — checkpoints table + measured timings +
  any fixes made.
- Append `CONTEXT.md`; set TRACKER.md rows.

## Definition of done

- [ ] Two full rehearsals; every checkpoint passed or has recorded explanation
- [ ] `npm run build` clean
- [ ] All timings measured and in the handoff
- [ ] Handoff + CONTEXT.md + TRACKER.md updated
