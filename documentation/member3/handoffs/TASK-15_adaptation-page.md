# HANDOFF — TASK-15 — `Adaptation.jsx` Live Wiring + FORCE Button

> Copy this template to `handoffs/TASK-NN_<slug>.md` (same slug as your task
> file). Fill EVERY field — this file is the only thing dependent agents know
> about your work. Replace TASK-NN everywhere.

| | |
|---|---|
| **Task** | TASK-15 — `Adaptation.jsx` live wiring + FORCE button |
| **Status** | `done` |
| **Wave** | C2 — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-06 (proxy path + literal status passthrough + 503 shape), TASK-07 (`postWithStatus` `{status, ok, data}` shape — Option A pattern used), TASK-09 (`/adaptation` field names, trigger 202/409/422, `last_event.type` values) |

---

## Files created

- `documentation/member3/handoffs/TASK-15_adaptation-page.md` — this handoff

## Files modified

- `client/src/pages/Adaptation.jsx` — full live wiring (only file touched, per spec):
  fetch-once `useEffect` → 3 s `setInterval` poll; `alert()` FORCE button → real
  `api.postWithStatus('/telemetry/adaptation/trigger')` handler with inline
  status line; champion card gains `champion_version`; buffer card gains
  `label_sources` subtitle; static ensemble-weight-bars block repurposed as
  "Promotion Gate Status"; history table gains `Status` column + honest empty
  state; `RETRAINING…` badge added; offline banner when `GET` fails.

## Interface surface shipped

*(Exact names/signatures other tasks will call — copy real code lines.
Dependent tasks build against THIS, not the plan.)*

```jsx
// client/src/pages/Adaptation.jsx — bindings to GET /api/telemetry/adaptation
// (Task-09's live get_status() payload, Node-proxied verbatim):

data.champion_model            // e.g. "LGBMClassifier" — card line 1
data.champion_version          // e.g. "v2" — rendered 2xl amber (demo payoff)
data.adaptation_mode           // "Drift-triggered candidate retrain + gated promotion"
data.adaptation_in_progress    // bool → amber "RETRAINING…" spinner badge in header
data.online_learning_buffer    // {capacity, current_size, fill_percentage,
                               //  label_sources: {rule_override, high_confidence, flow_id_tag}}
                               //   rendered as: "Labels — rule:N · conf:N · tag:N"
data.retraining_history        // [{version, timestamp, f1_score, trigger,
                               //   promoted, gates_passed:{gate_macro_f1,
                               //   gate_bal_acc, gate_emerged_recall,
                               //   gate_normal_fpr}}]
                               // NEWEST = LAST element (adapter appends
                               // chronologically); table renders .reverse()
data.last_event                // {type: promotion|rejection|skipped|error,
                               //   timestamp, detail} — shown under gate rows

// FORCE button (TASK-07 Option A — no try/catch needed for HTTP statuses):
const { status, data: body } = await api.postWithStatus('/telemetry/adaptation/trigger');
// 202 → "Adaptation queued — candidate retrain started"   (green)
// 409 → "Retrain already running — wait for it to finish" (amber)
// 422 → body.detail (e.g. "0 labeled samples < min_buffer 200") (amber)
// 503 → "ML offline — Flask API unreachable"              (red)
// other → "Unexpected response (NNN)"                     (amber)
// fetch reject (Node down) → "Request failed — Node API unreachable" (red)
// Message renders inline under the button; button disabled only while the
// POST is in flight (label flips to TRIGGERING…), so the 409 path stays
// reachable/visible during a real retrain.
```

## Verification run

*(Paste REAL commands + outputs. "It should work" is not verification.)*

```
$ cd client && npx vite build
vite v6.4.3 building for production...
✓ 2183 modules transformed.
dist/index.html                  0.99 kB │ gzip:   0.53 kB
dist/assets/index-BfyStG1N.css  27.59 kB │ gzip:   5.71 kB
dist/assets/index-BwKze2l_.js  625.39 kB │ gzip: 183.69 kB
(!) Some chunks are larger than 500 kB after minification.   ← pre-existing
✓ built in 4.83s                                              (same warning
                                                               T07 observed)
```

Code review vs spec (no eslint config in `client/` — build is the check):
- Poll: `load()` + `setInterval(load, 3000)` + `clearInterval` cleanup — same
  pattern as `Overview.jsx`/`LiveTrafficTable.jsx`.
- Status mapping covers 202/409/422/503 + transport-failure catch; the real
  `postWithStatus` resolves `{status, ok, data}` for ANY HTTP status and only
  rejects on no-response — matches TASK-07 Option A exactly.
- Gate keys verified against `live_adapter.py:593-598` + `adaptive_engine.py:34-40`
  (thresholds in labels: delta ≥ -0.01 / recall ≥ 0.70 / FPR ≤ 0.05 — real
  `PromotionGateConfig` values).
- `label_sources` keys verified against `live_adapter.py:168-172`
  (`rule_override`/`high_confidence`/`flow_id_tag`).
- Backend NOT live-tested — parallel C1 lane owns the running stack per spec;
  bindings written against the shipped `get_status()` code, not the §8 example.

## Outputs produced

- Adaptation page now renders live buffer fill/version/history/gates with 3 s
  refresh; FORCE performs the real proxied POST and reports all four status
  codes inline; `RETRAINING…` badge appears while `adaptation_in_progress`;
  history table shows PROMOTED (green) / REJECTED (red) per row.

## Deviations from spec

1. **Fake fallbacks removed, honest placeholders added** — the pre-existing
   hardcoded fallbacks (`1420/5000 flows`, `28.4%`, `WeightedSoftVotingEnsemble`,
   fake `v1.4` history row) were replaced with `'—'` / an empty-state row and a
   red "ML API offline" banner when `GET` returns nothing. Required by the
   "real values" goal — showing fabricated numbers when Flask is down would be
   wrong. No behavioral contract change.
2. **`RETRAINING…` badge and gate-block `last_event` line** are small additions
   implied by the spec ("`adaptation_in_progress` → RETRAINING… badge in header
   area"; T09's note that `last_event.type` drives the UI banner) — both render
   only when the fields are present.
3. **History table renders newest-first** (`history.slice().reverse()`);
   LiveAdapter appends oldest→newest, so the demo's latest promotion lands on
   top. No data change.

## Handoff notes for dependent tasks

- For **TASK-17/T18 (rehearsal + runbook)**: FORCE button is safe to click
  live — with an empty/cold buffer it shows the real 422 `detail` (e.g.
  `"0 labeled samples < min_buffer 200"`); during a running retrain it shows
  the 409 message; both are good demo moments. A same-quality manual retrain
  still promotes (delta gates ≥ -0.01) — each accepted trigger bumps v1→v2→v3.
- For **TASK-16**: same polling pattern and same offline-banner convention
  used here; `/evaluation` ≈40 ms at full window so ≥2 s poll stays fine.
- Gotcha: `retraining_history` entries always carry `promoted` +
  `gates_passed` (gate reports are the only history items); `skipped`/
  `insufficient` events exist ONLY in `last_event`, never in history.
- `dist/` was rebuilt by this verification (shared mid-wave — expected).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `client/src/pages/Adaptation.jsx` — polls `GET /api/telemetry/adaptation`
  every 3 s; binds `champion_model`/`champion_version`, `online_learning_buffer`
  (incl. `label_sources` → `rule:N · conf:N · tag:N`), newest
  `retraining_history` entry's `gates_passed` as "Promotion Gate Status",
  `last_event.detail` subtitle, `adaptation_in_progress` → `RETRAINING…` badge;
  FORCE button uses `api.postWithStatus('/telemetry/adaptation/trigger')` →
  202/409/422/503 inline messages; `vite build` green.
- CONTEXT deviation: page's fabricated fallbacks (1420/5000, v1.4 row,
  ensemble weight bars) fully removed — honest `'—'`/empty-state + red
  "ML API offline" banner when the GET fails.
- Open issue: none.
- TRACKER row status: `done` — "Adaptation.jsx live: 3 s poll, champion
  version card, buffer label_sources, 4-gate PASS/FAIL block, PROMOTED/REJECTED
  history table, RETRAINING badge, real FORCE button (202/409/422/503 inline);
  build clean"
