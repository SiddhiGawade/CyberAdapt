# HANDOFF — TASK-01 — Drift Monitor Module

| | |
|---|---|
| **Task** | TASK-01 — Drift Monitor Module (`ml/src/drift/live_monitor.py`) |
| **Status** | `done` |
| **Wave** | A |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- `ml/src/drift/live_monitor.py` — `LiveDriftMonitor` + module-level singleton helpers; the full §9.2 interface, all §5.3 signals, §5.2 `drift_state.json` persistence.

## Files modified

- none

## Interface surface shipped

```python
# ml/src/drift/live_monitor.py
class LiveDriftMonitor:
    def __init__(self, state_path: Path, window: int = 500)
    @property
    def drift_detected(self) -> bool                    # latched until reset_reference()/reset()
    def process_batch(self, records: list[dict]) -> dict
        # returns {"batch_size","attack_ratio","mean_confidence","drift_detected",
        #          "drift_state","status","signals":{adwin_attack_ratio,page_hinkley,
        #          slots_drifted,confidence_warning,ddm_warning,ddm_drift},"event":dict|None}
    def get_status(self) -> dict                        # exact §8 /concept-drift contract
    def consume_drift_event(self) -> Optional[dict]     # returns event once, then None
    def reset_reference(self) -> None                   # rotate ref<-recent + clear drift latch (post-promotion)
    def reset(self) -> None                             # full wipe + persist
    def _persist(self) -> None
    def _restore(self) -> None                          # called from __init__

def set_default_monitor(monitor: Optional[LiveDriftMonitor]) -> None
def get_default_monitor() -> LiveDriftMonitor           # lazy; ml/artifacts/state/drift_state.json
def detect_drift() -> bool                              # get_default_monitor().drift_detected
```

**TASK-08 wiring (preferred — constructor injection):**
```python
_drift_monitor = LiveDriftMonitor(STATE_DIR / "drift_state.json")
set_default_monitor(_drift_monitor)   # only if api.py also calls detect_drift()
# in predict(): _drift_monitor.process_batch(batch_records)
# in /concept-drift: jsonify(_drift_monitor.get_status())
```

## Verification run

```
$ .venv/Scripts/python.exe _verify_task01.py   (synthetic §9.1 batches — script deleted after run)
→ [normal] first-batch status=warming_up  after 600 flows status=active drift_state=stable drift_detected=False
  attack_ratio_recent=0.0  events=0
  feature PSI: [(1, 0.0042, 'stable'), (4, 0.0084, 'stable'), (5, 0.0079, 'stable'), (14, 0.0026, 'stable'), (44, 0.0, 'stable')]
  KS: {'status': 'stable', 'stat': 0.016, 'p_value': 1.0, 'drift_signal': False}
→ [attack] drift fired on attack batch #5  detector=PSI
  event detail: "attack_ratio 1.00; PSI drifted on 3 slots (Total Fwd Bytes, Total Bwd Bytes, Flow Bytes/s)"
  drift_state=drift drift_detected=True attack_ratio_recent=0.18
  DDM_pseudo_error: drift (error_rate 1.0) · KS_Test: drift (p=0.0)
→ [consume] first=True second=None      (consume-once works)
→ [events] before 2 more attack batches=1 after=1   (latched — no event spam)
→ [restore] samples_processed=690, events=1, drift_state=drift   (state round-trips)
→ [reset_reference] drift_state=stable samples_since_retrain=500
→ [detect_drift] lazy singleton + injectable OK
→ [corrupt] fresh start ok   (corrupt drift_state.json tolerated)
→ ALL CHECKS PASSED
```

Second scenario — identical feature distributions, labels flip to DoS (isolates ADWIN/PH from PSI):
```
→ FIRED at attack batch 65 -> ADWIN
  detail: "attack_ratio 1.00; ADWIN attack_ratio estimation jumped to 0.82 (width 80.0)"
  drift_state: drift
```

## Outputs produced

- `get_status()` emits every §8 `/concept-drift` field verbatim: `status` (warming_up|active), `drift_detected`, `drift_state` (stable|warning|drift), `samples_processed`, `samples_processed_since_retrain`, `last_drift_timestamp`, `attack_ratio_recent`, `detector_algorithms` {ADWIN_attack_ratio, PageHinkley, DDM_pseudo_error, KS_Test}, `labrooms_features_drift` (slots 1/4/5/14/44, PSI score + stable|minor_shift|drifted), `drift_events` (cap 20, newest first).
- Drift decision = `ADWIN(attack_ratio) OR PageHinkley OR ≥2 PSI slots drifted` — PSI fires fastest in practice (~batch 5 when features differ); ADWIN fires at ~batch 65 on a pure label flip; PageHinkley (threshold 50) is the slow backstop.
- On drift: fired detectors reset, ref←recent histograms rotate, event latched (`_drift_active`) until `reset_reference()`/`reset()`.
- `drift_state.json`: counters, event log, pending event, latch, per-slot ref/recent windows, DDM + PageHinkley internals, ADWIN estimations (record-only). Atomic tmp+rename write; every drift event, reset, and every 25th batch.
- Threading: `threading.Lock` around all mutation; `_fire_drift`/`_persist` run under the caller's lock — no nested acquisition.

## Deviations from spec

1. **`drift_state` is latched.** Spec didn't define when `drift` clears. Chosen: stays `"drift"` until `reset_reference()` (post-promotion) or `reset()` — the unresolved condition keeps alerting, and no repeat events fire while latched.
2. **Drift events suppressed while one is active** (`decision and not _drift_active`) — satisfies "at most one event per batch" without spamming the log for a still-unresolved drift.
3. **ADWIN internals don't round-trip** (River objects unserializable). Estimations/widths persist for the record; detectors restart fresh on boot — everything else (windows, counters, events, PH/DDM internals, latch) restores.
4. **`warning_level` is the live DDM threshold** (`p_min + 2·s_min`), not a constant — contract example value 0.05 was illustrative.
5. **`PageHinkley` uses River defaults** (threshold=50, mode="both") — spec named no params.
6. **Added helpers** `drift_detected` property, `set_default_monitor()`, `get_default_monitor()` — needed so `detect_drift()` can serve both constructor-injection (TASK-08) and lazy-singleton use.

## Handoff notes for dependent tasks

- For **TASK-08**: instantiate with `STATE_DIR / "drift_state.json"`; `mkdir` is handled inside `_persist()`. `process_batch()` never raises on malformed records (guards on `raw_features` type/length, non-finite values, missing labels). Keep it inside the guarded try/except in `predict()` anyway.
- For **TASK-08/TASK-14**: `status` is `"warming_up"` until `samples_since_reset >= window` (500). `KS_Test.stat/p_value` and `DDM.warning_level` are `null` until enough data — UI must tolerate nulls.
- For **TASK-04/adapter**: call `consume_drift_event()` in `maybe_trigger()`; on promotion call `reset_reference()` — that clears the drift latch AND resets DDM flags (they go stale otherwise since normal batches skip pseudo-error updates).
- For **TASK-14**: `drift_events[]` entries = `{timestamp, signal, detector, samples_processed, detail}` — `detector` ∈ `ADWIN|PageHinkley|PSI`.
- Note: `detect_drift()` returns the **latched** drift flag, not a per-batch check.
- ADWIN(0.002) fires slowly (~65 batches) on pure-ratio drift; PageHinkley slower (~126). The demo's real drift signal is PSI — attack features always differ from normal traffic.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `LiveDriftMonitor` shipped at `ml/src/drift/live_monitor.py`; instantiate `LiveDriftMonitor(STATE_DIR/"drift_state.json")`, wire `set_default_monitor()` if api.py calls `detect_drift()`. `drift_state` latches `drift` until `reset_reference()`/`reset()`.
- CONTEXT fact: in River 0.26.1 `ADWIN.drift_detected` is per-update (not latching); `PageHinkley` internals are `_sum_increase/_min_increase/_sum_decrease/_max_decrease/_x_mean` (restorable via setattr).
- CONTEXT deviation: `drift_state`/`drift_detected` latch until `reset_reference()` — spec left clearing undefined; chosen for demo legibility.
- Open issue: none.
- TRACKER row status: `done` — "LiveDriftMonitor shipped + verified in-process; both PSI and ADWIN drift paths fire; state round-trips"
