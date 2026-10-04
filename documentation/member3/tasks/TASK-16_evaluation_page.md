# TASK-16 — `Evaluation.jsx` Live Wiring

| | |
|---|---|
| **Wave** | C2 — **parallel** (with T14, T15; runs alongside C1 verification lane) |
| **Depends on** | T10 |
| **Input handoffs** | `handoffs/TASK-10_*.md` (final `/evaluation` fields incl. `insufficient_data` + `pre_post_adaptation`) |
| **Files you may touch** | `client/src/pages/Evaluation.jsx` only |
| **Files you must NOT touch** | `client/src/api.js`, other pages — minimal diff rule |
| **Goal** | Evaluation page renders live rolling metrics with 3 s polling + pre/post-adaptation strip + graceful insufficient-data state |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `handoffs/TASK-10_*.md` — final field names
3. `00_MASTER_PLAN.md` — §8 `/evaluation` contract
4. `client/src/pages/Evaluation.jsx`, `LiveTraffic.jsx` (polling pattern)

## Changes

- Poll `GET /api/telemetry/evaluation` every **3 s**.
- Metric cards + per-class table + confusion matrix → `data.overall_metrics`,
  `data.per_class_metrics`, `data.confusion_matrix` — existing render code
  already loops the response; feed it real data.
- `data.insufficient_data` → muted "Collecting labeled stream samples…" state
  instead of fake zeros.
- New compact **"Pre / Post Adaptation"** strip reading
  `data.pre_post_adaptation` (pre F1 → post F1 with ▲/▼ delta); hidden when
  `last_adaptation` is null.

## Do NOT

- Minimal diff; no new deps/pages.

## Verification

```bash
cd client && npx eslint src/pages/Evaluation.jsx
# code-review: insufficient_data path renders; matrix binds real arrays
```

## Finish protocol

- `handoffs/TASK-16_evaluation-page.md`.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] All metrics/tables/matrix render live with 3 s polling
- [ ] insufficient_data + pre/post strip implemented
- [ ] eslint clean; handoff written
