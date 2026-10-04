# HANDOFF — TASK-14 — `ConceptDrift.jsx` Live Wiring

| | |
|---|---|
| **Task** | TASK-14 — ConceptDrift.jsx Live Wiring |
| **Status** | `done` |
| **Wave** | C2 — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-08 (live `/concept-drift` field names + latch semantics), CONTEXT.md |

---

## Files created

- none

## Files modified

- `client/src/pages/ConceptDrift.jsx` — only file touched. Single-fetch
  `useEffect` replaced by LiveTrafficTable's verbatim polling pattern
  (`fetchDrift()` + `setInterval(…, 3000)` + `clearInterval` cleanup + `mounted`
  guard + `intervalRef`); every hardcoded metric replaced by `data?.…` bindings;
  detector cards / PSI table / header rendered from `data.detector_algorithms`,
  `data.labrooms_features_drift`, `data.status`; new "Recent Drift Events" card;
  full-width latched drift banner on `data.drift_detected === true`.

## Interface surface shipped

```jsx
// Polling (LiveTrafficTable pattern verbatim):
useEffect(() => { let mounted = true;
  async function fetchDrift() { try { const res = await api.get('/telemetry/concept-drift'); ... } }
  fetchDrift(); intervalRef.current = setInterval(fetchDrift, 3000);
  return () => { mounted = false; clearInterval(intervalRef.current); };
}, []);

// Bindings (exact §8 /concept-drift keys, verified vs live_monitor.py get_status()):
data.status                       // 'warming_up' | 'active' → header pill text
data.drift_state                  // 'stable'|'warning'|'drift' → NO DRIFT/WARNING/DRIFT DETECTED card
data.drift_detected === true      // → full-width red banner (latched until adaptation resets)
data.samples_processed_since_retrain / data.samples_processed   // samples card + subtitle
data.last_drift_timestamp         // → 'Last drift: <ts>' line (null-tolerated → state subtitle)
data.detector_algorithms.{ADWIN_attack_ratio:{estimation,width,drift_signal,status},
  DDM_pseudo_error:{error_rate,warning_level|null,drift_signal,status},
  PageHinkley:{sum_val,threshold,drift_signal,status},
  KS_Test:{stat|null,p_value|null,drift_signal,status}}          // → 4 cards, titles kept
data.labrooms_features_drift[]    // {slot,name,drift(PSI),status} → dynamic table
data.drift_events[]               // {timestamp,detector,signal,detail,samples_processed} → events list
```

## Verification run

```
$ cd client && npx vite build
→ vite v6.4.3 building for production...
  ✓ 2183 modules transformed.
  dist/assets/index-BJIry0a9.js  623.61 kB
  ✓ built in 10.06s          (exit 0 — no parallel build collision, first try)

$ code review (grep for metric literals: 0.xxx floats, 14250, 25,000, NOMINAL)
→ zero hardcoded metrics left in JSX. Remaining numbers are className/styling
  tokens (p-5, border-2, shadow rgba) + static contract labels
  ("Labrooms-10", "42 zeroed slots filtered", "ADWIN, DDM, PH, KS").
```

Not eyeballed in browser — **code-verified only** (C1 lane owns the running
stack; no services started).

## Outputs produced

- Page polls `GET /api/telemetry/concept-drift` every 3 s; API failure (incl.
  Node's 503 "fetch failed" when Flask is down) keeps last good `data` and shows
  one subdued `{error} — showing last known state` line; first-load failure
  renders all cards/tables with '—' placeholders (no crash, nothing scary).
- Drift Signal card: `drift_state`→NO DRIFT/green, WARNING/yellow, DRIFT
  DETECTED/red; `last_drift_timestamp` shown when set.
- 4 detector cards keep titles ADWIN/DDM/Page-Hinkley/Kolmogorov-Smirnov and show
  the real per-detector fields; badge = DRIFT/red on `drift_signal`, plus
  WARNING/yellow when `status==='warning'`, else STABLE/green. Null-tolerant:
  `warning_level`, KS `stat`/`p_value` render '—' while warming up.
- PSI table renders `labrooms_features_drift` dynamically; chip map
  stable→green / minor_shift→yellow / drifted→red; `SLOT_MEANINGS` map (static
  display metadata, not metrics) preserves the "name & meaning" annotations.
- "Recent Drift Events" card lists `drift_events` (ts, detector badge, signal,
  detail, @ samples); empty state "No drift events recorded this session."
- Banner styling copied from `AttackAlertBanner` (red-950/40, border-red-500,
  glow shadow, ShieldAlert, pulse): "⚠️ CONCEPT DRIFT DETECTED — ADAPTATION
  PIPELINE ENGAGED" + last-drift ts + newest event detail + "DRIFT ACTIVE" pill.

## Deviations from spec

1. Detector badge is 3-state (DRIFT/red on `drift_signal`; WARNING/yellow on
   `status==='warning'`; else STABLE/green) — strict superset of the spec's
   binary `drift_signal ? DRIFT : stable`; surfaces DDM's real warning tier.
2. Feature table keeps the descriptive parentheticals via a `SLOT_MEANINGS`
   slot→text map (falls back to API `name`) — display metadata only, zero
   metric literals.
3. "Detector Suite" card count bound to
   `Object.keys(data.detector_algorithms).length` ('—' when offline) instead of
   hardcoded "4"; the "ADWIN, DDM, PH, KS" subtitle kept as a static label.
4. Banner/badge use the file's own `ShieldAlert` import (lucide-react, already a
   dependency) rather than rendering `AttackAlertBanner` itself — that component
   requires a `flows` prop and shows attack text; spec asked for its *look*.

## Handoff notes for dependent tasks

- For **TASK-15/16/17**: `/concept-drift` fields consumed verbatim — no adapter
  shims; if the contract changes, this page is the exact binding reference.
- `drift_state`/`drift_detected` **latch** until adaptation `reset_reference()`
  — the red banner staying up post-event is correct behavior, not a bug.
- `get_status` ~1 ms server-side; 3 s poll is comfortably inside budget.
- Vite build emits the pre-existing >500 kB chunk warning — unrelated, do not
  chase it.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `ConceptDrift.jsx` polls `/api/telemetry/concept-drift` @3 s
  (LiveTrafficTable pattern + mounted guard); renders full §8 contract incl.
  null-tolerant KS `stat`/`p_value` + DDM `warning_level` ('—' early);
  `drift_detected===true` shows latched red banner until adaptation reset.
- CONTEXT deviation: detector badge renders a WARNING/yellow tier from
  `status==='warning'` (spec's binary DRIFT/STABLE extended, not contradicted);
  feature table keeps meaning annotations via static `SLOT_MEANINGS` slot map.
- Open issue: none.
- TRACKER row status: `done` — "ConceptDrift live-wired: 3 s poll, 4 detector
  cards + PSI table + events list + latched drift banner, zero hardcoded
  metrics, vite build clean (code-verified only)"
