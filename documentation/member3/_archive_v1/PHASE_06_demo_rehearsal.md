# PHASE 06 — E2E Demo Rehearsal & Runbook

| | |
|---|---|
| **Goal** | Prove the whole Member-3 story end-to-end on the real stack, produce a timed demo runbook + README updates |
| **Depends on** | Phases 01–05 all `done` in TRACKER.md |
| **Enables** | The actual project presentation |
| **Est. scope** | Verification runs + `documentation/member3/DEMO_RUNBOOK.md` + README delta |

---

## Read first

1. `documentation/member3/00_MASTER_PLAN.md` — §7 narrative, §8 contracts
2. `documentation/member3/TRACKER.md` — **all** agent log entries; every
   `partial`/`blocked` leftover must be resolved before this phase passes
3. Root `README.md` "How to Run" — your runbook extends this

## The rehearsal protocol

Run the full sequence below **twice**: once to shake out bugs, once timed and
clean as if presenting. Every checkpoint must pass — record actual numbers in
TRACKER.md.

### Setup checklist (T-minus)

```bash
# 1. mongod running (README step 0)
# 2. server/.env has ML_API_URL=http://localhost:5001; npm run dev → :5000
# 3. Flask: DEMO_MODE=1 + MODEL_PATH + PREPROCESSOR_PATH set → python -m ml.api → :5001
# 4. client npm run dev → :3000, logged in as admin@acme-test.local
# 5. POST /api/telemetry/admin/reset (JWT) → {"status":"reset"}
#    → GET /concept-drift shows samples_processed ≈ 0
```

### Act 1 — Baseline (2 min)

```bash
python sensor/normal_traffic.py --key "ca_live_…" --interval 2 --batch-size 8
```
Checkpoints:
- [ ] Live Traffic fills with `Normal Traffic` labels
- [ ] Concept Drift: `drift_state: stable`, PSI scores < 0.10, all detectors green
- [ ] Adaptation: buffer `current_size` climbing, `high_confidence` label source growing

### Act 2 — Attack (the reveal)

```bash
python sensor/attack_campaign.py --key "ca_live_…" --scenario mixed
# (or single phase for a shorter demo: --scenario dos)
```
Checkpoints:
- [ ] Live Traffic floods with DoS / Brute Force / Web Attacks labels within ~5 s
- [ ] Concept Drift: red banner, `drift_state: drift`, ≥1 `drift_events` entry,
      ADWIN_attack_ratio signal fired, slot-1/5 PSI visibly jumps
- [ ] Overview page attack banner (existing component) also fires

### Act 3 — Adaptation (the payoff)

Checkpoints (automatic — but keep the cursor on /adaptation):
- [ ] `adaptation_in_progress` → true → false
- [ ] `champion_version` increments (v1→v2)
- [ ] New `retraining_history` row: trigger "ADWIN drift alert", all 4 gates PASS
- [ ] `ml/artifacts/models/adaptive_champion_v2.joblib` exists on disk
- [ ] Manual `FORCE ADAPTATION` button also works (hit once, observe 202)

### Act 4 — Recovery + metrics

- [ ] Normal generator still running → predictions stay correct under new champion
- [ ] Evaluation: `pre_post_adaptation` shows post ≥ pre F1 (or honest delta —
      record actual numbers)
- [ ] Confusion matrix + per-class metrics populated on the page

### Robustness passes (once each)

- [ ] Restart Flask mid-demo → drift history + version survive (state files)
- [ ] Kill Flask entirely → dashboard degrades gracefully, ingest still 202s
- [ ] `POST /adaptation/trigger` ×2 fast → second = 409
- [ ] `POST /admin/reset` → whole story repeatable from clean slate

## Write the runbook

Create `documentation/member3/DEMO_RUNBOOK.md`:

- T-minus setup commands (copy-paste ready, incl. env vars for Windows PS)
- The 4-act script with the exact commands + what to say ("watch the drift
  score spike as the Slowloris wave hits…")
- Timing notes from your rehearsal (how long until drift fires, until promotion)
- Failure playbook: what to do if drift doesn't fire (run a second attack
  phase / check buffer), if promotion is rejected (show the REJECTED history
  row — it's still a valid demo of the gates), if Flask dies (ingest unaffected
  — talk through the fire-and-forget design)
- Screenshot checklist (drift banner, version bump, pre/post metrics)

## README update

Append to root `README.md` under "What Is Implemented": flip the four
placeholders from "static" to live — one line each: live ADWIN/PH/DDM/KS drift
monitoring on the ingest stream, drift-triggered gated retraining +
hot-swap, rolling pseudo-labeled evaluation, `POST /adaptation/trigger` +
`/admin/reset` (DEMO_MODE). Add `sensor/normal_traffic.py` +
`attack_campaign.py` to the "Send telemetry" section. Keep it to ~10 lines.

## Definition of done

- [ ] Two full rehearsals completed; every checkpoint above passed or has a
      recorded explanation in TRACKER.md
- [ ] `DEMO_RUNBOOK.md` written with real measured timings
- [ ] README updated
- [ ] TRACKER.md fully updated — all phases `done`
- [ ] Final report to operator: what works, actual numbers, any known limits
