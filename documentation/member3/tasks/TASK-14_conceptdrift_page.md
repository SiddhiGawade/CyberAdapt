# TASK-14 — `ConceptDrift.jsx` Live Wiring

| | |
|---|---|
| **Wave** | C2 — **parallel** (with T15, T16; runs alongside C1 verification lane) |
| **Depends on** | T08 |
| **Input handoffs** | `handoffs/TASK-08_*.md` (final `/concept-drift` field names as shipped) |
| **Files you may touch** | `client/src/pages/ConceptDrift.jsx` only |
| **Files you must NOT touch** | `client/src/api.js`, other pages, components — minimal diff rule |
| **Goal** | Concept Drift page renders live data with 3 s polling + drift alert banner — zero hardcoded metrics left |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. Your input handoffs — final field names (§8 contract is law; handoff records any deviation)
3. `00_MASTER_PLAN.md` — §8 `/concept-drift` contract
4. `client/src/pages/ConceptDrift.jsx` — current hardcoded blocks
5. `client/src/pages/LiveTraffic.jsx` — copy its polling pattern verbatim (useEffect + setInterval + cleanup + mounted guard)
6. `client/src/components/AttackAlertBanner.jsx` — banner look to reuse

## Rules

- **Minimal diff:** keep dark cyber theme, layout, classNames; replace
  hardcoded values with `data?.…` bindings — no redesign.
- Poll `GET /api/telemetry/concept-drift` every **3 s**.
- API failures → keep last good data; nothing scary (pages render defaults).

## Changes

- **Drift Signal card:** `data.drift_state` → `NO DRIFT`/green |
  `WARNING`/yellow | `DRIFT DETECTED`/red + `data.last_drift_timestamp` line.
- **Samples card:** `data.samples_processed_since_retrain` + total
  `data.samples_processed` in subtitle.
- **Detector cards ×4:** map `data.detector_algorithms`
  (`ADWIN_attack_ratio`, `PageHinkley`, `DDM_pseudo_error`, `KS_Test`) onto the
  existing four cards — keep card titles (ADWIN, DDM, Page-Hinkley,
  Kolmogorov-Smirnov); show each entry's real fields (`estimation`/`width`,
  `error_rate`, `sum_val`/`threshold`, `stat`/`p_value`); badge =
  `drift_signal ? DRIFT/red : stable/green`.
- **Feature table:** render `data.labrooms_features_drift` dynamically
  (slot, name, `drift` PSI score, status chip: stable→green,
  minor_shift→yellow, drifted→red) — replace the 5 hardcoded `<tr>`.
- **New block** under the table: "Recent Drift Events" — list
  `data.drift_events` (timestamp, detector, signal, detail); empty state
  "No drift events recorded this session." Same card style.
- **Full-width alert** when `data.drift_detected === true`: reuse
  `AttackAlertBanner` look — `CONCEPT DRIFT DETECTED — adaptation pipeline engaged`.

## Do NOT

- No routing/sidebar/theme changes; no new packages, no websockets/SSE.
- Don't touch other pages.

## Verification

```bash
cd client
npx eslint src/pages/ConceptDrift.jsx        # clean
# code-level: grep the file — no hardcoded metric literals left in JSX
# (npm run build runs in T17 — if you run it yourself and a parallel agent
#  is also building, wait/retry; dist/ is shared)
# If stack + C1 lane allows, eyeball the page once — else note "code-verified
# only" in the handoff.
```

## Finish protocol

- `handoffs/TASK-14_conceptdrift-page.md` — list bindings made + any field-name
  deviations you had to match.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] Page polls every 3 s, renders live values for every card/table
- [ ] Drift banner + events list implemented
- [ ] Zero hardcoded metrics; eslint clean
- [ ] Handoff written
