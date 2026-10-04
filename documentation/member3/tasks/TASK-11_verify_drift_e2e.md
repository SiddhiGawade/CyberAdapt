# TASK-11 — Verify Drift E2E (live stack)

| | |
|---|---|
| **Wave** | C1 — **sequential** (first of the live-stack verification lane; runs while C2 frontend tasks run in parallel) |
| **Depends on** | T08, T02, T03 |
| **Input handoffs** | `handoffs/TASK-08_*.md`, `handoffs/TASK-02_*.md`, `handoffs/TASK-03_*.md` |
| **Files you may touch** | `ml/scripts/` (new check scripts only — e.g., `check_drift_api.py`) |
| **Files you must NOT touch** | `ml/api.py`, `ml/src/*`, `server/`, `client/` — this is a verify-only task; if you find a bug, document it precisely in the handoff and mark `blocked`/`partial` rather than patching outside your ownership (exception: trivially safe fixes only if the orchestrator's standing instruction allows — when in doubt, report) |
| **Goal** | Prove, on the real running stack, that live traffic drives `/concept-drift` from stable → drift and that state persists |

---

## Read first

1. `documentation/member3/CONTEXT.md` — env state, sensor key, merged deviations
2. Your input handoffs — actual endpoints/field names as shipped
3. `00_MASTER_PLAN.md` — §8 `/concept-drift` contract

## Protocol

```bash
# Stack: mongod + server :5000 + flask :5001 (DEMO_MODE=1) — reuse running
# services per shared-stack rule; seed key from CONTEXT.md §A
# Clean slate: POST /admin/reset (via Flask directly or Node proxy w/ JWT)

# 1. BASELINE — run normal generator ≥60 s
python sensor/normal_traffic.py --key "ca_live_…" --duration 60
#    → GET /concept-drift: drift_state stable, PSI <0.10, detectors green,
#      samples_processed climbing, warming_up → active transition observed

# 2. ATTACK — campaign dos phase (or full mixed)
python sensor/attack_campaign.py --key "ca_live_…" --scenario dos
#    → within the phase: GET /concept-drift flips: drift_state "drift",
#      ≥1 drift_events entry w/ detector+signal, last_drift_timestamp set,
#      slot PSI visibly jumps, ADWIN_attack_ratio and/or PageHinkley fired

# 3. PERSISTENCE — restart Flask → events + samples_processed survive

# 4. CONTRACT AUDIT — diff the live JSON against §8 field-by-field
#    (every key present, correct types; drift_events cap 20 newest-first)
```

Record **measured numbers**: batches/flows until drift fired, which detector
fired first, PSI values per slot before/after.

## If drift does NOT fire

Check in order: are attack flows getting attack labels? (`recent-flows`) → is
`attack_ratio` actually rising in `/concept-drift`? → ADWIN `estimation`/
`width` values → `drift_events` empty but `drift_state: warning`? Document the
exact stuck point in the handoff — do not silently loosen thresholds.

## Finish protocol (sequential — update shared files)

- `handoffs/TASK-11_verify-drift.md` — measured numbers + contract audit result.
- Append `CONTEXT.md` §C (e.g., "drift fires ~N batches into dos phase") and
  §A verified rows; set TRACKER.md rows.

## Definition of done

- [ ] Baseline stable → attack → drift transition observed on live stack
- [ ] §8 contract audited field-by-field on real output
- [ ] Restart persistence confirmed
- [ ] Measured timings/PSI in handoff; CONTEXT.md + TRACKER.md updated
