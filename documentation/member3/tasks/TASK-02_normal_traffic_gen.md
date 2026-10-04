# TASK-02 — Normal Traffic Generator (`sensor/normal_traffic.py`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T01–T07) |
| **Depends on** | none |
| **Input handoffs** | none |
| **Files you may touch** | `sensor/normal_traffic.py` (new) only |
| **Files you must NOT touch** | `simulate_attacks.py`, `mock_sensor.py`, `server/`, everything else |
| **Goal** | A sustained benign-traffic generator — the demo's "before" state and the buffer's `high_confidence` label source |

---

## Read first

1. `documentation/member3/CONTEXT.md` — sensor key may already be listed in §A
2. `00_MASTER_PLAN.md` — §4 (slot map), §5.4 (why Normal labels matter), §7 (narrative)
3. `sensor/mock_sensor.py` — copy its CLI/loop conventions (`--key`, `--url`, `--interval`, `--batch-size`, `requests.Session`, `X-Sensor-Key` header)
4. `sensor/simulate_attacks.py::build_labrooms_flow` — the exact 52-slot layout (copy + extend; keep the script standalone)

## Why this task exists

`simulate_attacks.py` fires 5 flows once — useless as a baseline.
`mock_sensor.py` emits uniform-random junk the model labels inconsistently.
We need **controlled benign profiles** that the champion reliably labels
`Normal Traffic` with no rule override firing.

## Build — `sensor/normal_traffic.py`

Emulates ordinary users browsing the Labrooms site. Per flow (52-slot vector,
same contract as `build_labrooms_flow`):

| Slot | Distribution (benign) |
|---|---|
| 1 duration µs | `random.lognormvariate(12.0, 0.6)` clamped 5 ms–900 ms |
| 2/3 fwd/bwd pkts | `1` (HTTP req/resp), occasionally `2` |
| 4 fwd bytes | `random.randint(180, 2600)` |
| 5 bwd bytes | `random.randint(400, 80_000)` |
| 6/7 | same distribution as slot 4 |
| 14 bytes/s | derived: `(fwd_bytes + bwd_bytes) / duration_s` — compute, don't invent |
| 44 status | `200` w.p. 0.93, `304` 0.03, `404` 0.03, `301` 0.01 |

- CLI: `--key` (required), `--url` (default `http://localhost:5000/api/telemetry/ingest`),
  `--interval` (default 2 s), `--batch-size` (default 8), `--duration`
  (optional total seconds, else run until Ctrl+C), `--jitter` (± fraction on interval).
- `sensor_id = "normal-traffic-gen"`. Print one line per batch like mock_sensor.
- `requests` + stdlib only, no new deps. KeyboardInterrupt → print summary, exit 0.
- Keep it under ~250 lines; docstring header in the existing sensor style.
- Optional `--lbl-tag` to prefix `LBL::Normal_Traffic::` on flow_ids (default
  off for normal traffic — the §5.4 high-confidence rule already labels it;
  having the flag aids experiments).

**Acceptance bar:** flows must be labeled `Normal Traffic` by the live
pipeline with zero rule overrides — verify, don't assume.

## Do NOT

- Don't modify `simulate_attacks.py` or `mock_sensor.py` (README references them).
- Don't touch `server/` — ingest already accepts this shape.
- No real credentials/targets in the file — `--key` is a CLI arg.

## Verification (needs live stack — shared-stack rule §5.7)

```bash
# Reuse a running stack if ports 5000/5001 are up; otherwise start mongod,
# server (npm run dev), Flask (python -m ml.api) — see CONTEXT.md §A.
# If no sensor key exists yet: cd server && node scripts/seed-dev.js → copy the ca_live_… key
python sensor/normal_traffic.py --key "ca_live_…" --duration 60
# Then check GET /api/telemetry/recent-flows (needs JWT login) or Mongo directly:
#   ≥ 90% of your flows labeled "Normal Traffic", zero rule-override labels
```

If the stack genuinely cannot run in your environment, verify offline: POST a
batch to `/predict`-equivalent logic or at minimum assert vector shape/slot
populations — and mark the handoff `partial` with what's unverified.

Record actual label counts in the handoff — "sends traffic" is not
acceptance, "classified as intended" is.

## Finish protocol

- Write `handoffs/TASK-02_normal-traffic.md` from the template — paste the
  label-count evidence; if you minted a sensor key, put `ca_live_…` under
  "Merge suggestions" so CONTEXT.md §A gets it.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] `normal_traffic.py` runs the full CLI contract above
- [ ] ≥90% `Normal Traffic` labels over a 60 s live run (or partial + reason)
- [ ] Ctrl+C exits cleanly with summary; no stack-trace spam on conn errors
- [ ] Handoff written with evidence
