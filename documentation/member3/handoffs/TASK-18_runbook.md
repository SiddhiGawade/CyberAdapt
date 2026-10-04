# HANDOFF — TASK-18 — `DEMO_RUNBOOK.md`

| | |
|---|---|
| **Task** | TASK-18 — `DEMO_RUNBOOK.md` (copy-paste demo script + failure playbook) |
| **Status** | `done` |
| **Wave** | D — **parallel** (with T19) |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-17 (measured timings + mechanics), CONTEXT.md, root README.md "How to Run", master plan §7/§8 |

---

## Files created

- `documentation/member3/DEMO_RUNBOOK.md` — presenter-usable demo runbook:
  mechanics crib-notes, T-minus PowerShell setup, 4-act script with
  copy-paste commands + what-to-say lines mapped to §7, measured timing
  table, failure playbook, screenshot checklist.

## Files modified

- none (task scope: the one new file only)

## Interface surface shipped

*(Doc-only task — no code interfaces. The runbook's operator surface:)*

```
T-minus:  mongod :27017 · server/ npm run dev :5000 ·
          Flask $env:MODEL_PATH/$env:PREPROCESSOR_PATH/$env:DEMO_MODE="1"/$env:PORT="5001" :5001 ·
          client/ npm run dev → http://localhost:3000 (::1-bound, NOT 127.0.0.1)
Acts:     reset → normal_traffic --interval 2 --batch-size 8 --duration 140
        → check_adaptation_api.py seed dos 90 30        (prime + reveal, ~0.9 s to drift, <1 s to v2)
        → FORCE ×2 (UI or proxytriggerx2 → 202/409)
        → attack_campaign --scenario mixed --rate 12 --batch-size 6  (2,880 fl / 241 s)
        → normal_traffic --lbl-tag --duration 25        (recovery + honest eval rows)
```

## Verification run

*(Doc-authoring task — verified every command + expected output against
script sources and T17's measured outputs; nothing was executed live.)*

```
$ grep argparse flags sensor/normal_traffic.py
→ --interval --batch-size --duration --lbl-tag --key(env SENSOR_KEY) confirmed

$ grep argparse flags sensor/attack_campaign.py
→ --scenario mixed (6 phases) --rate --batch-size --scale --no-lbl-tag confirmed

$ read ml/scripts/check_adaptation_api.py
→ subcommands seed|trigger|triggerx2|proxytrigger|proxytriggerx2|reset|status|poll|waitpromo confirmed;
  SENSOR_KEY is HARDCODED line 37 (docstring's env-override claim not implemented — runbook warns)

$ read ml/scripts/check_drift_api.py / check_evaluation_api.py
→ subcommands once|poll|audit|full and snap|full|audit|reset|file confirmed

$ grep server/routes/telemetry.js
→ POST /api/telemetry/adaptation/trigger and /api/telemetry/admin/reset JWT proxies exist (l.261/280)
```

## Outputs produced

- `DEMO_RUNBOOK.md` complete, 400 lines: §0 mechanics crib (warm-up ≥500,
  prime-before-drift, skipped-event latch, buffer-composition→gates),
  §1 T-minus (ports, 5 terminals, PowerShell env vars, reset, sanity
  outputs), §2 four acts with exact commands + measured expected outputs +
  SAY lines mapped to §7.2–§7.6, §3 T17 timing table (both runs +
  compressed ~6 min cut), §4 failure playbook (14-row table), §5 screenshot
  checklist (14 items).
- Priming choreography stated explicitly and twice (§0 rule 2 + Act 2
  callout): `seed dos 90` must precede `attack_campaign`, else warmup-PSI
  skips on an insufficient all-Normal buffer and the latch holds.
- All quoted numbers are T17-measured: drift ≈0.8–0.9 s after attack start,
  event→promotion <1 s, buffer at trigger 620–1,948, PSI peaks
  s1≈9/s5≈12/s14≈6–7/s44≈10, 540/540 per-phase labels, 2,880 fl/241 s.

## Deviations from spec

- **Runbook arc is ~8–9 min wall** (T17 said "~4.5 min"; the Run-2 cadence
  it recommends — 140 s baseline + 241 s campaign + waits — sums higher).
  Runbook lists honest per-act wall times and ships a compressed ~6 min
  variant (Run-1 baseline cadence) so the presenter can pick.
- Failure playbook extends the spec's 3 cases to a 14-row table (adds:
  warming_up stall, cooldown-skip latch narration, 409/422 semantics,
  localhost/::1 traps both directions, key revocation, ADWIN/PH flicker,
  build warning).

## Handoff notes for dependent tasks

- For TASK-19 (README): the runbook links itself as "extends How to Run" —
  consider adding a pointer in README's Documentation table. Runbook assumes
  the hardcoded `SENSOR_KEY` in `check_adaptation_api.py` stays valid.
- Gotcha for any future doc: `check_adaptation_api.py` docstring claims
  SENSOR_KEY/FLASK_URL env overrides — **not implemented** (constants only).
- DEMO_RUNBOOK §4 row "Flask dies" documents the fire-and-forget + 503
  degrade path as a *feature* — keep that framing consistent in slides.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `DEMO_RUNBOOK.md` shipped (member3/) — T17-measured timings
  (drift ~0.9 s, promotion <1 s, buffer 620–1,948), 4-act script with
  priming choreography (seed-dos BEFORE campaign), skipped-event latch and
  buffer→gates mechanics written as presenter crib notes, 14-row failure
  playbook, screenshot checklist.
- CONTEXT deviation: `check_adaptation_api.py` docstring claims env
  overrides (FLASK_URL/NODE_URL/SENSOR_KEY/LOGIN_*) — code uses hardcoded
  constants; runbook documents the real behavior (edit line 37 on reseed).
- Open issue: none.
- TRACKER row status: `done` — "DEMO_RUNBOOK.md shipped: T-minus PS setup,
  4-act script w/ measured T17 timings + say-lines, priming + latch
  mechanics, failure playbook, screenshot checklist"
