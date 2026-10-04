# PHASE 01 — Live Drift Detection Backend

| | |
|---|---|
| **Goal** | Replace the static `/concept-drift` placeholder in `ml/api.py` with a real streaming drift monitor fed by every `/predict` batch |
| **Depends on** | nothing (first phase) |
| **Enables** | Phase 03 (drift events trigger adaptation), Phase 05 (UI reads this endpoint) |
| **Est. scope** | 1 new module + `api.py` edits + state file |

---

## Read first

1. `documentation/member3/00_MASTER_PLAN.md` — §4 (feature contract), §5.2–5.3 (state + signals), §8 (response contract)
2. `documentation/member3/TRACKER.md` — confirm no one else mid-flight
3. `ml/api.py` — especially `predict()` (~lines 185–282), the rule-override helper `_detect_labrooms_app_layer_anomaly` (~148), and the static `concept_drift()` (~286)
4. `ml/src/drift/detectors.py` — reuse `ADWINDriftDetector` where sensible; do NOT rewrite it
5. River docs in your head: `from river.drift import ADWIN, PageHinkley`; `detector.update(x)`; `detector.drift_detected` (ADWIN) / `drift_detected` property (PageHinkley)

## Build

### 1. New module: `ml/src/drift/live_monitor.py`

A `LiveDriftMonitor` class — singleton owned by `ml/api.py`. Requirements:

```python
class LiveDriftMonitor:
    def __init__(self, state_path: Path, window: int = 500): ...
    def process_batch(self, flows: list[dict]) -> dict:
        """Called once per /predict batch.
        flows[i] = {flow_id, raw_features(52), label, label_index,
                    confidence, rule_override(bool), model_raw_label}
        Returns the batch's drift summary; fires at most one drift event
        per batch."""
    def get_status(self) -> dict:
        """Returns the exact /concept-drift contract shape (master plan §8)."""
    def reset(self) -> None: ...
    def _persist(self) -> None: ...   # writes state_path JSON
    def _restore(self) -> None: ...   # loads on __init__ if exists
```

**Signals to implement** (per master plan §5.3):

- `attack_ratio` per batch → `ADWIN(delta=0.002)` AND `PageHinkley`. Batch-level, not per-flow (per-flow on a binary burst signal double-fires; batch ratio is smooth and demo-legible).
- `mean_confidence` per batch → second `ADWIN(delta=0.01)` — warning-only signal.
- `pseudo_error` per flow → stream of `1/0` where a rule override disagreed/agreed with raw model label → third `ADWIN` or simple DDM-style running error-rate. Reported as `DDM_pseudo_error` in the contract. If a batch has zero rule-overrides, skip updating (no evidence).
- **Per-slot PSI** on slots `[1, 4, 5, 14, 44]`: keep `reference_counts` (histogram, 10 bins over log1p for 1/4/5/14; raw for 44) built from the first `window` flows since reset/retrain, and `recent_counts` over the last `window`. PSI per slot = `Σ (ref% - rec%) * ln(ref%/rec%)`, guard empty bins with eps=1e-4. Status: `<0.10 stable`, `0.10–0.25 minor_shift`, `>0.25 drifted`.
- **KS test**: `scipy.stats.ks_2samp(reference_bytes_per_sec, recent_bytes_per_sec)` on slot 14 raw values — report `stat` + `p_value`, `drift_signal = p_value < 0.05`. Keep the raw per-slot values in two `collections.deque(maxlen=window)`.
- **Auto-baseline**: until `window` flows seen, reference is still filling — report `status: "warming_up"` top-level and PSI scores as computed anyway.

**Drift decision** (exactly as §5.3):
`drift = ADWIN(attack_ratio) fired OR PageHinkley fired OR (≥2 slots drifted)`.
On drift: append to `drift_events` (cap 20, newest first), set
`last_drift_timestamp`, reset the ADWIN detectors that fired (per
`ADWINDriftDetector.reset()` semantics — a fired ADWIN keeps alerting forever
otherwise), rotate reference←recent for the slot histograms, and expose
`consume_drift_event()` so Phase 03's adapter can pull the trigger.

Expose a module-level `detect_drift()` function wrapping the monitor's check —
the team plan lists `detect_drift()` as a Member 3 deliverable, keep the name.

**Concurrency:** Flask runs threaded — guard all state mutation with a
`threading.Lock`. Keep per-batch work O(window) worst case; PSI on 500×5 is
trivial.

### 2. Wire into `ml/api.py`

- Instantiate `LiveDriftMonitor` at module load (after `_load_artifacts`), state
  path `ml/artifacts/state/drift_state.json` (mkdir parents).
- In `predict()`: while building `predictions`, collect for each flow its
  `raw` vector, final label, confidence, whether `app_anomaly` fired, and the
  raw model label index (before override). After the response is assembled,
  call `_drift_monitor.process_batch(...)` — **inside a try/except that logs
  and never raises**: drift monitoring must never break `/predict`.
- Replace the static `concept_drift()` body with `return jsonify(_drift_monitor.get_status())` — keep the route path and auth-free access identical.
- Keep the response keys exactly per contract §8 — the UI agent in Phase 05 builds against that shape.
- Store the *raw model label* (pre-override) in the batch payload — Phase 03 needs it for pseudo-error and buffer labeling. Don't remove it after Phase 01.

### 3. State file

`ml/artifacts/state/drift_state.json` — detector estimations/widths,
`samples_processed`, `last_drift_timestamp`, `drift_events`, serialized
histograms + deques (as lists). `_restore()` on boot; tolerate missing/corrupt
file by starting fresh with a warning. Add `ml/artifacts/state/` to
`.gitignore` (runtime state, not source).

## Do NOT

- Don't touch `server/` or `client/` — this phase is Flask-only.
- Don't add dependencies beyond `river` + `scipy` (already present via sklearn).
- Don't trigger retraining yet — Phase 03 consumes `consume_drift_event()`.
- Don't change `/predict`'s response shape — Node depends on it.

## Verification

Run the stack (master plan §Environment: mongod, :5001, :5000 optional for this test — you may hit Flask directly):

```bash
# 1. warm baseline — 10 batches of normal-ish flows
python -c "..."   # POST /predict with ~50 flows: duration<1s, bwd_bytes<50k, status 200

# 2. GET /concept-drift
#    expect: status active, drift_state stable, samples_processed=500+,
#            detector_algorithms.*.drift_signal all false,
#            labrooms_features_drift all stable/minor

# 3. attack burst — POST 5 batches, flows with duration>30s + status 504
#    (reuse the vector shapes in sensor/simulate_attacks.py::build_labrooms_flow)

# 4. GET /concept-drift again
#    expect: drift_state "drift", at least one entry in drift_events,
#            last_drift_timestamp set, slot-1 PSI likely spiked,
#            ADWIN_attack_ratio.drift_signal true (or already consumed/reset)

# 5. restart Flask → GET /concept-drift → samples_processed + drift_events
#    survived the restart (state file worked)
```

Write a small throwaway script `scripts/` or just curl/python `-c` — your call;
delete or keep under `ml/scripts/` if it's reusable (name it
`check_drift_api.py`, note it in tracker).

## Definition of done

- [ ] `/concept-drift` returns live data matching §8 contract exactly
- [ ] Attack burst produces a `drift_events` entry + `drift_state: "drift"`
- [ ] State survives Flask restart
- [ ] `/predict` response shape unchanged; latency overhead <20 ms/batch
- [ ] `detect_drift()` callable exists in `ml/src/drift/live_monitor.py`
- [ ] TRACKER.md updated (status row + log entry)
