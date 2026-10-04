# PHASE 05 — Dashboard Wiring (live data, polling, real FORCE button)

| | |
|---|---|
| **Goal** | Wire `ConceptDrift`, `Adaptation`, `Evaluation` pages to the now-live endpoints: polling refresh, real values everywhere, working trigger button, drift alert surface |
| **Depends on** | Phases 01, 03, 04 (the live APIs) |
| **Enables** | Phase 06 (demo) |
| **Est. scope** | 3 page edits + `api.js` helper (no new deps, no new pages — Member 4's UI stands, we only connect it) |

---

## Read first

1. `documentation/member3/00_MASTER_PLAN.md` — §8 contracts (field names are law)
2. `documentation/member3/TRACKER.md` — Phase 01/03/04 entries for final field names + deviations
3. `client/src/pages/ConceptDrift.jsx`, `Adaptation.jsx`, `Evaluation.jsx` — current hardcoded blocks
4. `client/src/api.js` + `client/src/components/AttackAlertBanner.jsx` — existing conventions (api.get wrapper, banner styling)

## Rules

- **Minimal diff.** Keep the existing dark cyber theme, layout, and
  classNames. Replace hardcoded values with `data?.…` bindings; don't redesign.
- **Poll every 3 s** on all three pages: `useEffect` + `setInterval` +
  cleanup, guard with `mounted`. Match how `LiveTraffic.jsx` polls if it does
  (check it first — copy its pattern verbatim).
- API failures → keep last good data, show nothing scary (pages already
  render defaults). `api.js` probably returns `res.data` — verify.
- No new npm packages. Recharts is already available if needed, but prefer
  reusing existing markup over adding charts.

## Changes

### `client/src/api.js`
If it only exposes `get`, add `post(path, body)` hitting the same
`/api`-proxied axios/fetch base with the JWT header — copy `get`'s auth
handling exactly.

### `ConceptDrift.jsx`
- Poll `GET /api/telemetry/concept-drift` every 3 s.
- **Drift Signal card**: `data.drift_state` → `NO DRIFT`/`cyber-green` |
  `WARNING`/`yellow-400` | `DRIFT DETECTED`/red — plus
  `data.last_drift_timestamp` line under it when drifted.
- **Samples card**: `data.samples_processed_since_retrain` (already bound) +
  total `data.samples_processed` in the subtitle.
- **Detector cards ×4**: map `data.detector_algorithms` (keys
  `ADWIN_attack_ratio`, `PageHinkley`, `DDM_pseudo_error`, `KS_Test`) onto the
  existing four cards — keep card titles (`ADWIN`, `DDM`, `Page-Hinkley`,
  `Kolmogorov-Smirnov`) and show each entry's real numeric fields
  (`estimation`/`width`, `error_rate`, `sum_val`/`threshold`, `stat`/`p_value`).
  Badge = `drift_signal ? DRIFT/red : STABLE|NOMINAL/green`.
- **Feature table**: render `data.labrooms_features_drift` rows dynamically
  (slot, name, `drift` score, status chip: `stable`→green, `minor_shift`→yellow,
  `drifted`→red) — replacing the 5 hardcoded `<tr>`.
- **New small block** under the table: "Recent Drift Events" — list
  `data.drift_events` (timestamp, detector, signal, detail); empty state
  "No drift events recorded this session." Keep it the same card style.
- **Full-width alert** at top when `data.drift_detected === true`: reuse
  `AttackAlertBanner`'s look (import it or clone its classes) — text like
  `CONCEPT DRIFT DETECTED — adaptation pipeline engaged`.

### `Adaptation.jsx`
- Poll `GET /api/telemetry/adaptation` every 3 s.
- Champion card → `data.champion_model` + `data.champion_version` (append
  version prominently — it's the demo payoff).
- Buffer card → `data.online_learning_buffer` real values; subtitle shows
  `label_sources` breakdown (e.g. `rule:320 · conf:1090 · tag:10`).
- Weight bars: the champion is a single LightGBM, not the static ensemble —
  replace the three hardcoded weight bars with either (a) real per-class
  importance data if cheap, or (b) **repurpose the block** as "Promotion Gate
  Status" showing the latest `gates_passed` (4 rows: gate name + PASS/FAIL
  chip) from the newest `retraining_history` entry — pick (b), it tells the
  adaptation story better and uses real data.
- History table → `data.retraining_history` (real rows; add a `Status` column:
  `promoted`→green `PROMOTED` / `rejected`→red `REJECTED`).
- `adaptation_in_progress` → show a `RETRAINING…` spinner badge in the header
  area.
- **FORCE ADAPTATION button** → real `api.post('/telemetry/adaptation/trigger')`;
  on 202 show inline "Adaptation queued" state; on 409 "retrain already
  running"; on 422 show the insufficiency reason. Replace the `alert()`.

### `Evaluation.jsx`
- Poll `GET /api/telemetry/evaluation` every 3 s.
- Metric cards + per-class table + confusion matrix → `data.overall_metrics`,
  `data.per_class_metrics`, `data.confusion_matrix` (keep existing render code;
  it already loops the response — just feed it real data).
- If `data.insufficient_data` → render a muted "Collecting labeled stream
  samples…" state instead of fake zeros.
- Add a compact "Pre / Post Adaptation" strip reading
  `data.pre_post_adaptation` (pre F1 → post F1 with a ▲/▼ delta); hide when
  `last_adaptation` is null.

## Do NOT

- No routing/sidebar/theme changes; no new pages.
- Don't touch `Overview`, `LiveTraffic`, `SensorSetup`, `Explainability`
  (`/explain` stays static — out of Member 3 scope).
- Don't add websockets/SSE — polling matches the codebase's approach.

## Verification

```bash
# stack + generators running (Phase 02 scripts)
# Browser at :3000 (logged in):
# 1. /concept-drift — PSI numbers move every 3 s; during attack wave:
#    red banner appears, detector badge flips, event appears in list
# 2. /adaptation — buffer % climbs during traffic; after drift: RETRAINING…
#    then version v2 + new history row; FORCE button returns real states
#    (hit it twice fast → 409 message)
# 3. /evaluation — metrics reflect live window; after promotion the
#    pre/post strip shows the delta
# 4. kill Flask → pages degrade gracefully (no crash, stale data stays)
# 5. npm run build in client/ passes with no errors
```

## Definition of done

- [ ] All three pages render live data with 3 s polling, zero hardcoded metrics left
- [ ] Drift produces visible red alert + event entry without manual refresh
- [ ] FORCE ADAPTATION button performs a real POST and reports 202/409/422
- [ ] `npm run build` clean; no console errors on the three pages
- [ ] TRACKER.md updated
