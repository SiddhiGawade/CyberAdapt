# TASK-15 — `Adaptation.jsx` Live Wiring + FORCE Button

| | |
|---|---|
| **Wave** | C2 — **parallel** (with T14, T16; runs alongside C1 verification lane) |
| **Depends on** | T06, T07, T09 |
| **Input handoffs** | `handoffs/TASK-09_*.md` (final `/adaptation` fields + trigger status codes), `handoffs/TASK-07_*.md` (**exact `api.post` return shape**), `handoffs/TASK-06_*.md` (proxy path) |
| **Files you may touch** | `client/src/pages/Adaptation.jsx` only |
| **Files you must NOT touch** | `client/src/api.js`, other pages — minimal diff rule |
| **Goal** | Adaptation page renders live buffer/version/history with 3 s polling + a real FORCE ADAPTATION button |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. Your input handoffs — especially TASK-07's `post()` return shape (you must distinguish 202/409/422)
3. `00_MASTER_PLAN.md` — §8 `/adaptation` + trigger contracts
4. `client/src/pages/Adaptation.jsx`, `LiveTraffic.jsx` (polling pattern)

## Changes

- Poll `GET /api/telemetry/adaptation` every **3 s** (same pattern as siblings).
- **Champion card:** `data.champion_model` + `data.champion_version`
  prominently — the version bump is the demo payoff.
- **Buffer card:** `data.online_learning_buffer` real values; subtitle with
  `label_sources` breakdown (e.g. `rule:320 · conf:1090 · tag:10`).
- **Weight bars block → repurpose as "Promotion Gate Status":** the champion
  is a single LightGBM, not the static ensemble — show the newest
  `retraining_history` entry's `gates_passed` (4 rows: gate name + PASS/FAIL
  chip). Tells the adaptation story with real data.
- **History table:** `data.retraining_history` real rows; add `Status` column
  (promoted→green `PROMOTED` / rejected→red `REJECTED`).
- `adaptation_in_progress` → `RETRAINING…` spinner badge in header area.
- **FORCE ADAPTATION button** → real `api.post('/telemetry/adaptation/trigger')`:
  202 → inline "Adaptation queued"; 409 → "retrain already running";
  422 → the insufficiency reason. Replace the `alert()`.

## Do NOT

- Minimal diff; no new deps/pages; don't touch other files.

## Verification

```bash
cd client && npx eslint src/pages/Adaptation.jsx
# code-review: button handler covers 202/409/422 via api.post's real shape
# (npm run build in T17; dist/ is shared mid-wave)
```

## Finish protocol

- `handoffs/TASK-15_adaptation-page.md` — bindings + how you mapped status codes.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] Live buffer/version/history/gates render with 3 s polling
- [ ] FORCE button performs real POST, reports 202/409/422 inline
- [ ] RETRAINING badge works; eslint clean
- [ ] Handoff written
