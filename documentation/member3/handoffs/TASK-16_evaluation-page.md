# HANDOFF — TASK-16 — `Evaluation.jsx` Live Wiring

> Filled per `handoffs/_TEMPLATE.md`. Parallel wave (C2) — CONTEXT.md/TRACKER.md
> intentionally untouched; merge suggestions below.

| | |
|---|---|
| **Task** | TASK-16 — `Evaluation.jsx` Live Wiring |
| **Status** | `done` |
| **Wave** | C2 — parallel (with T14, T15) |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-10 (live `/evaluation` field names), TASK-05 (`get_metrics()` shape — per-class `f1` key, `insufficient_data` only-when-true, `pre_post_adaptation` semantics) |

---

## Files created

- none

## Files modified

- `client/src/pages/Evaluation.jsx` — only file touched. Mount-only fetch → 3 s `setInterval` poll (LiveTrafficTable pattern: `fetchMetrics()` + `intervalRef` + cleanup); fake fallback metrics (`|| 0.987` etc.) replaced with live values / `—`; added insufficient-data muted state, Pre/Post Adaptation strip, live 7×7 confusion matrix, Support column, LIVE WINDOW pill.

## Interface surface shipped

```jsx
// polls GET /api/telemetry/evaluation every 3000 ms; keeps last good snapshot on error
const res = await api.get('/telemetry/evaluation');   // → §8 live contract

// bindings used (all from TASK-10's shipped get_metrics()):
data.window.size / data.window.capacity      // "LIVE WINDOW n/500" header pill
data.overall_metrics.{accuracy, precision_macro, recall_macro, f1_macro, latency_p95_ms}
data.per_class_metrics -> Object.entries -> {precision, recall, f1, support}   // remapped `f1` key
data.confusion_matrix   // 7x7 ints; cell heat = v / max (diag green, off-diag red)
data.class_names        // axis labels, first-word abbreviation + title= full name
data.insufficient_data  // truthy -> muted "Collecting labeled stream samples…" panel
data.pre_post_adaptation.{pre.f1_macro, pre.samples, post.f1_macro, post.samples, last_adaptation}
//   strip shown only when last_adaptation != null && post != null
```

## Verification run

```bash
$ cd client && npx vite build
→ vite v6.4.3 building for production...
  ✓ 2183 modules transformed.
  dist/assets/index-BJIry0a9.js  623.61 kB │ gzip: 183.03 kB
  ✓ built in 17.07s   (exit 0 — first try, no parallel build conflict)
```

Code-review (no eslint config in `client/` — build is the check):
- `insufficient_data` path renders the muted collecting panel (cards/table/matrix
  skipped — no fake zeros anywhere; all fallbacks now `—` or empty-state row).
- Matrix loops `data.confusion_matrix` × `data.class_names` directly; `cmMax`
  clamped `Math.max(1, …)` so an all-zero window can't divide-by-zero.
- `per_class_metrics` loop uses the remapped `f1` key (T05 deviation — not
  `f1_score`).
- `latency_p95_ms` shown as `x.x ms` — honest `0.0 ms` post-restart per T10 note.
- Poll interval cleared on unmount; fetch errors swallowed so a Flask 503/offline
  doesn't blank the last good snapshot.

## Outputs produced

- Live Evaluation page: 5 metric cards + per-class table (P/R/F1/Support) +
  7×7 confusion-matrix grid all bound to the rolling window, refreshing every 3 s.
- Compact "Pre / Post Adaptation" strip: `F1 pre% → post%` with ▲/▼ delta and
  `pre → post samples · last <ISO ts>`; hidden until a real promotion lands.
- Muted "Collecting labeled stream samples…" state with live `window.size`
  progress (notes ≥30-sample threshold) instead of zeros.

## Deviations from spec

1. **Confusion matrix UI added, not just bound** — spec assumed "existing render
   code already loops the response" but no matrix/heatmap markup existed
   anywhere in `client/src` (verified via grep). Added a compact CSS-grid matrix
   in the same page style (diag green / off-diag red, alpha ∝ value/max).
   Contract is always 7×7 so this is presentation only.
2. **Support column + empty-state row added** to the per-class table — contract
   ships `support` and `per_class_metrics` can be `{}`; both additions are
   within the existing table markup.
3. No live E2E against Flask — per task rules, services not started
   unnecessarily; binding verified against the documented T05/T10 contract
   shape and `npx vite build`.

## Handoff notes for dependent tasks

- For **TASK-12/T17 (demo choreography)**: the page now self-updates every 3 s —
  during the demo, evaluation visibly fills after ~30 labeled flows, matrix
  diagonal lights up on LBL traffic, and the Pre/Post strip appears the moment
  the first promotion lands (auto PSI or FORCE button). After `/admin/reset`
  the page flips back to the muted collecting state and `LIVE WINDOW 0/500`.
- For **everyone**: `cyber-surface` and `cyber-purple` utility classes are used
  pervasively in pages (incl. this one) but are NOT in `tailwind.config.js` —
  they're silent no-ops. Kept for style consistency; not a bug introduced here.
- Endpoint consumed: `GET /api/telemetry/evaluation` via existing Node proxy
  (`server/routes/telemetry.js:245`, 3 s abort → 503 on Flask-down; the page
  keeps the last good snapshot on error).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `client/src/pages/Evaluation.jsx` wired live — 3 s poll of `/telemetry/evaluation`; binds `window{size,capacity}`, `overall_metrics`, `per_class_metrics` (`f1` key + `support`), 7×7 `confusion_matrix`/`class_names`; `insufficient_data` → muted "Collecting labeled stream samples…" state; Pre/Post strip (`pre.f1_macro`→`post.f1_macro` + ▲/▼ delta + samples + ts) hidden when `last_adaptation`/`post` is null.
- CONTEXT fact: no confusion-matrix markup existed in `client/src` — T16 added the grid (spec's "already loops the response" was only true for cards + per-class table).
- CONTEXT fact: `cyber-surface`/`cyber-purple` Tailwind classes used across pages are undefined in `tailwind.config.js` (silent no-ops — pre-existing quirk).
- CONTEXT deviation: none beyond handoff §Deviations (matrix UI + Support column added; no new deps).
- Open issue: none.
- TRACKER row status: `done` — "Evaluation page live: 3 s polling, cards/table/7×7 matrix bound to rolling window, muted insufficient-data state, pre/post-adaptation strip; `npx vite build` clean (2183 modules)."
