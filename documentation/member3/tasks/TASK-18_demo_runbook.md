# TASK-18 — `DEMO_RUNBOOK.md`

| | |
|---|---|
| **Wave** | D — **parallel** (with T19, after T17) |
| **Depends on** | T17 |
| **Input handoffs** | `handoffs/TASK-17_*.md` (measured timings + checkpoint results) |
| **Files you may touch** | `documentation/member3/DEMO_RUNBOOK.md` (new) only |
| **Files you must NOT touch** | `README.md` (T19 owns it), code files |
| **Goal** | A copy-paste-ready demo runbook with real measured timings and a failure playbook |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `handoffs/TASK-17_*.md` — the measured numbers are your content
3. Root `README.md` "How to Run" — the runbook extends it

## Write `documentation/member3/DEMO_RUNBOOK.md`

- **T-minus setup** — copy-paste commands incl. Windows PowerShell env vars
  (`$env:MODEL_PATH=…`, `$env:PREPROCESSOR_PATH=…`, `$env:DEMO_MODE="1"`),
  mongod start, seed script, `POST /admin/reset`.
- **The 4-act script** — exact commands per act + what to say ("watch the
  drift score spike as the Slowloris wave hits…") mapped to the §7 narrative.
- **Timing notes** — real measured numbers from T17 (time-to-drift,
  time-to-promotion, buffer size at trigger).
- **Failure playbook** — what to do if: drift doesn't fire (run second attack
  phase / check buffer), promotion is rejected (show the REJECTED history row —
  it's still a valid gates demo), Flask dies (ingest unaffected — narrate the
  fire-and-forget design), demo needs a mid-run reset (`/admin/reset`).
- **Screenshot checklist** — drift banner, version bump, pre/post metrics.

## Finish protocol

- `handoffs/TASK-18_runbook.md`.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`** (merge suggestions in handoff).

## Definition of done

- [ ] `DEMO_RUNBOOK.md` complete with real timings + failure playbook
- [ ] Handoff written
