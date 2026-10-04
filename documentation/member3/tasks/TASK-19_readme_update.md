# TASK-19 — README Update

| | |
|---|---|
| **Wave** | D — **parallel** (with T18, after T17) |
| **Depends on** | T17 |
| **Input handoffs** | `handoffs/TASK-17_*.md` (what actually works) |
| **Files you may touch** | `README.md` (root) only |
| **Files you must NOT touch** | everything else |
| **Goal** | Flip the "static placeholder" notes to live + list the new generator scripts — ~10 lines, minimal diff |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `handoffs/TASK-17_*.md`
3. `README.md` — "What Is Implemented" + "Send telemetry" sections

## Changes (~10 lines total)

Under "What Is Implemented": flip the four placeholders from static to live —
one line each:
- live ADWIN / Page-Hinkley / DDM / KS drift monitoring on the ingest stream
- drift-triggered gated retraining + hot-swap (`POST /adaptation/trigger`,
  `/admin/reset` under `DEMO_MODE`)
- rolling pseudo-labeled evaluation with pre/post-adaptation metrics
- dashboard pages now poll live data

Under "Send telemetry": add `sensor/normal_traffic.py` +
`sensor/attack_campaign.py` with one-line usage each.

## Finish protocol

- `handoffs/TASK-19_readme.md`.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`**.

## Definition of done

- [ ] README reflects live implementation accurately, ~10-line diff
- [ ] Handoff written
