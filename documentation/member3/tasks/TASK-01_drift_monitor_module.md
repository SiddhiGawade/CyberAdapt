# TASK-01 — Drift Monitor Module (`ml/src/drift/live_monitor.py`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T02–T07) |
| **Depends on** | none |
| **Input handoffs** | none |
| **Files you may touch** | `ml/src/drift/live_monitor.py` (new) only |
| **Files you must NOT touch** | `ml/api.py`, `ml/src/drift/detectors.py`, everything else — wiring is TASK-08 |
| **Goal** | A self-contained `LiveDriftMonitor` class implementing the §9.2 interface — streaming drift detection over `/predict` batches |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `00_MASTER_PLAN.md` — §4 (feature slots), §5.2–5.3 (state + signals), §8 (`/concept-drift` contract), §9.1–9.2 (frozen interface)
3. `ml/src/drift/detectors.py` — reuse `ADWINDriftDetector` where sensible; do NOT rewrite it
4. River: `from river.drift import ADWIN, PageHinkley`; `detector.update(x)`; `.drift_detected` property

## Build — `ml/src/drift/live_monitor.py`

`LiveDriftMonitor` per master plan §9.2 — singleton owned by `ml/api.py`
(TASK-08 instantiates it; you only write the module).

**Signals (§5.3):**
- `attack_ratio` per batch → `ADWIN(delta=0.002)` AND `PageHinkley`. Batch-level (per-flow on a binary burst double-fires; batch ratio is smooth and demo-legible).
- `mean_confidence` per batch → second `ADWIN(delta=0.01)` — **warning-only**, never triggers drift.
- `pseudo_error` per flow → `1` where a rule-override's final label ≠ `model_raw_label`, else `0` → third `ADWIN` or DDM-style running error-rate, reported as `DDM_pseudo_error`. Batches with zero rule-overrides skip updating (no evidence).
- **Per-slot PSI** on slots `[1, 4, 5, 14, 44]`: `reference_counts` histogram (10 bins over log1p for 1/4/5/14; raw for 44) from the first `window` flows since reset, `recent_counts` over the last `window`. PSI = `Σ (ref% - rec%) * ln(ref%/rec%)`, eps=1e-4. Status: `<0.10 stable`, `0.10–0.25 minor_shift`, `>0.25 drifted`.
- **KS test**: `scipy.stats.ks_2samp(ref_bytes_per_sec, recent_bytes_per_sec)` on slot-14 raw values in two `deque(maxlen=window)`; `drift_signal = p_value < 0.05`.
- **Auto-baseline**: until `window` flows seen → top-level `status: "warming_up"`; PSI still computed.

**Drift decision (exactly §5.3):** `ADWIN(attack_ratio) OR PageHinkley OR ≥2 slots drifted`.
On drift: append to `drift_events` (cap 20, newest first), set
`last_drift_timestamp`, reset the fired ADWIN detectors (a fired ADWIN alerts
forever otherwise), rotate reference←recent histograms, and leave the event
consumable via `consume_drift_event()` (returns the event dict once, then
None until the next drift).

`get_status()` returns the **exact §8 `/concept-drift` contract** — field names
are law (the TASK-14 UI builds against them).

**Concurrency:** `threading.Lock` around all mutation (Flask is threaded).
O(window) per batch worst case — PSI on 500×5 is trivial.

**Persistence:** `_persist()` writes §5.2 `drift_state.json` (detector
estimations, `samples_processed`, `last_drift_timestamp`, `drift_events`,
histograms + deques as lists). Call it on every drift event and every
`reset_reference()`/`reset()`, plus cheaply (e.g., every N batches).
`_restore()` in `__init__`; tolerate missing/corrupt file → fresh start + log
warning.

Module-level `detect_drift()` wrapping the singleton's check — the team plan
lists `detect_drift()` as a Member-3 deliverable; keep the name. A module-level
`_default_monitor`/lazy singleton is fine since api.py isn't wired yet —
document how TASK-08 should instantiate (preferred: constructor injection, so
`detect_drift()` should operate on a module-level instance if one exists).

## Do NOT

- Don't touch `ml/api.py` or any existing file.
- No new dependencies beyond `river` + `scipy` (already installed).
- Don't trigger retraining — `consume_drift_event()` is the hand-off point.

## Verification (in-process — api.py not wired yet)

```bash
.venv\Scripts\activate
python -c "
from ml.src.drift.live_monitor import LiveDriftMonitor, detect_drift
from pathlib import Path
import tempfile, json
m = LiveDriftMonitor(Path(tempfile.mkdtemp())/'drift_state.json')
# build synthetic batch_records per §9.1 — normal batch (all Normal Traffic,
# conf 0.95, no overrides) x ~30 batches → get_status(): stable, warming_up→active
# then attack batches (label='DoS', rule_override=True, model_raw_label='Normal Traffic')
# → drift fires: drift_state='drift', drift_events populated, consume_drift_event() returns event once
# then reinstantiate from same path → samples_processed + events survived
"
```

Also sanity: `process_batch` returns a dict; two consecutive attack batches
produce ≤1 new event each; `detect_drift()` callable exists.

## Finish protocol

- Write `handoffs/TASK-01_drift-monitor.md` from `handoffs/_TEMPLATE.md` —
  list the exact shipped method signatures under "Interface surface shipped"
  (TASK-08 builds against it).
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.** Put updates in
  the handoff's "Merge suggestions".

## Definition of done

- [ ] `LiveDriftMonitor` matches §9.2 signatures exactly
- [ ] Attack-shaped batches produce a `drift_events` entry + `drift_state: "drift"`
- [ ] `get_status()` returns every §8 contract field
- [ ] State round-trips through `drift_state.json` (restore works)
- [ ] `detect_drift()` exists; `consume_drift_event()` consumes once
- [ ] Handoff written with interface surface + verification output
