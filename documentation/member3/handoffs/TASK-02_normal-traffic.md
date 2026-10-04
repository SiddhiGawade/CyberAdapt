# HANDOFF — TASK-02 — Normal Traffic Generator

> Copy this template to `handoffs/TASK-NN_<slug>.md` (same slug as your task
> file). Fill EVERY field — this file is the only thing dependent agents know
> about your work. Replace TASK-NN everywhere.

| | |
|---|---|
| **Task** | TASK-02 — Normal Traffic Generator (`sensor/normal_traffic.py`) |
| **Status** | `done` |
| **Wave** | A — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- `sensor/normal_traffic.py` — sustained benign-traffic generator (215 lines,
  `requests` + stdlib only). Emulates users browsing the Labrooms site; emits
  52-slot vectors with the same 10 populated slots as
  `simulate_attacks.build_labrooms_flow`.

## Files modified

- none

## Interface surface shipped

```python
# sensor/normal_traffic.py
SENSOR_ID = "normal-traffic-gen"
def build_normal_flow(flow_id: str) -> list      # -> 52 floats, slots [0,1,2,3,4,5,6,7,14,44] populated
def make_flow_id(lbl_tag: bool) -> str           # "src:sport->dst:dport-6", optional "LBL::Normal_Traffic::" prefix
def main() -> int                                # argparse CLI, returns 0 on clean exit
```

CLI (all flags verified live):

```
python sensor/normal_traffic.py --key "ca_live_..." [--url ...] [--interval 2]
                                [--batch-size 8] [--duration SECS] [--jitter 0.25] [--lbl-tag]
# env fallbacks: SENSOR_KEY, INGEST_URL (same convention as mock_sensor.py)
# POSTs {sensor_id, batch_timestamp(ms), flow_count, flows:[{flow_id, features[52]}]}
# with X-Sensor-Key header to /api/telemetry/ingest
```

Per-flow slot profile (as spec'd):

| Slot | Value |
|---|---|
| 1 duration µs | `random.lognormvariate(12.0, 0.6)` clamped [5 000, 900 000] |
| 2/3 fwd/bwd pkts | 1 (90%) / 2 (10%) |
| 4 fwd bytes | `randint(180, 2600)` |
| 5 bwd bytes | `randint(400, 80_000)`; **404-flows: `randint(150, 1500)`** (see deviations) |
| 6/7 | `= fwd_bytes` (slot-4 distribution, matches reference impl) |
| 14 bytes/s | derived `(fwd+bwd)/duration_s` |
| 44 status | 200/.93, 304/.03, 404/.03, 301/.01 |

## Verification run

Live stack: mongod :27017 + Node :5000 + Flask :5001 were all DOWN at task
start; a parallel wave-A agent brought mongod+Flask up at ~11:28:45 (my own
`mongod` attempt hit `DBPathInUse` — reused the running instance per §5.7,
killed nothing). Node :5000 came up shortly after. Sensor key minted via
`node scripts/seed-dev.js` (the key baked into `simulate_attacks.py` is revoked
— returns 403).

Offline profile check (20 000 generated flows — slot bounds + every
rule-override predicate from `ml/api.py::_detect_labrooms_app_layer_anomaly`
asserted safe):

```
$ .venv/Scripts/python.exe -c "...20k-flow assertion harness..."
populated slots: [0, 1, 2, 3, 4, 5, 6, 7, 14, 44]
status counts: {200.0: 18597, 301.0: 205, 404.0: 609, 304.0: 589}
max 404 bytes/s: 76745
dur range ok, all rule-override assertions passed for 20000 flows
```

60 s live run (final, fixed script):

```
$ .venv/Scripts/python.exe sensor/normal_traffic.py --key "ca_live_2d69…" --duration 60
[Batch 0001] OK  Sent 8 flows -> HTTP 202  (accepted: 8)
… (30 batches total, every one HTTP 202 / accepted: 8) …
--------------------------------------------------------
  Normal Traffic Generator - summary
  Elapsed        : 60.0s
  Batches OK/err : 30 / 0
  Flows accepted : 240  (4.0 flows/s)
--------------------------------------------------------
EXITCODE=0
```

Label-count evidence (queried MongoDB directly per spec — `TelemetryLog`
aggregate on `sensorId:"normal-traffic-gen"`, last 75 s = this run only):

```
$ cd server && node -e "...aggregate threatLabel..."
docs: 240
   {"_id":"Normal Traffic","n":240,"avgConf":0.99699,"minConf":0.99297,"maxConf":0.99981}
Normal Traffic: 240 / 240 = 100.0%
attack-label docs (rule-override evidence): 0
```

→ **100 % "Normal Traffic" (bar: ≥90 %), zero rule-override labels, min
confidence 0.993 ≥ 0.90** → every flow qualifies as a §5.4 `high_confidence`
pseudo-label. (First 60 s run, pre-ASCII-fix, had identical results:
256/256 Normal Traffic, avgConf 0.997.)

Ctrl+C path (no PTY on Windows — exercised via patched `time.sleep` raising
`KeyboardInterrupt` after batch 2):

```
[Batch 0002] OK  Sent 8 flows -> HTTP 202  (accepted: 8)
Interrupted by user (Ctrl+C).
…summary printed…  main() returned 0   EXITCODE=0
```

Connection-error path (`--url http://localhost:59999/…`): single
`[Batch 0001] ERR  Connection error: …` line, no stack trace, summary, exit 0.

`--lbl-tag` smoke test: flow_ids stored as
`LBL::Normal_Traffic::192.168.1.25:51853->10.10.10.21:443-6` → labeled
`Normal Traffic`. Default remains OFF.

## Outputs produced

- 240+256+56 flows in `TelemetryLog` under `sensorId:"normal-traffic-gen"`,
  100 % labeled `Normal Traffic`, confidence range 0.993–0.9998.
- Working sensor key minted (see Merge suggestions).

## Deviations from spec

1. **404-status flows are rate-guarded.** Spec asked for 404 w.p. 0.03, but
   `ml/api.py` rule 3 fires `Brute Force` whenever `status==404 AND
   Flow Bytes/s > 100_000`. With spec'd ranges (up to 82 600 B in as little
   as 5 ms → ~16 MB/s), ~3 % of flows would have produced rule overrides.
   Fix: 404 flows draw a realistic small error page (`bwd_bytes`
   150–1 500 B) and duration is floored so `bytes/s ≤ 80 000` (max needed
   ≈51 ms, always inside the 900 ms clamp). Worst observed 404 rate:
   76 745 B/s — provably below the trip line. All other slots unchanged.
2. **ASCII-only console output.** Windows cp1252 console raises
   `UnicodeEncodeError` on `±`/`─`/`—` prints — crashed the summary of the
   first 60 s run (flows unaffected; crash was in the final print only).
   All banner/help/summary output is now ASCII.
3. `batch_timestamp` sent as epoch **ms** (int) matching
   `simulate_attacks.py`; `mock_sensor.py` sends float seconds — schema is
   `Number`, both accepted.

## Handoff notes for dependent tasks

- For TASK-03 (attack campaign): same ingest envelope + `X-Sensor-Key`
  header; the minted key below works. **Mind the symmetric trap**: spec'd
  status codes that hit rule overrides are fine for attacks (that's the
  point), but `simulate_attacks.py`'s emoji prints (`⚔️🚀🤖❌`) will crash
  under a cp1252 console — keep campaign output ASCII.
- For TASK-11/12/13 (verify e2e): the `high_confidence` pseudo-label path is
  empirically hot — Normal flows arrive with conf ≥0.99, so the adapter
  buffer will fill with `high_confidence` Normal labels quickly. To get a
  "pure Normal" baseline window, filter on `sensorId:"normal-traffic-gen"`.
- Generator cadence at defaults: 8 flows / 2 s = 4 flows/s → ~240 flows per
  demo minute; `--interval 0.5 --batch-size 16` gives 32 flows/s if a faster
  buffer fill is needed.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT §A "Sensor key in use":
  `ca_live_2d69feba1bb75b5b6223595b83e3b9f13dac05b4c2259e21f4bf77db217a0657`
  (minted 2026-10-04 via `server/scripts/seed-dev.js`; the `DEFAULT_KEY`
  hardcoded in `simulate_attacks.py` is revoked → 403).
- CONTEXT fact: model artifacts live at `ml/artifacts/models/` —
  Flask needs `MODEL_PATH`/`PREPROCESSOR_PATH` env vars pointing there
  (`ml/artifacts/champion_model.joblib` default path does NOT exist).
- CONTEXT fact: `ml/api.py` Brute-Force rule also fires on `status==404 AND
  bytes/s>100k` — generators emitting error statuses must rate-guard.
- CONTEXT fact: keep sensor-script console output ASCII — cp1252 consoles
  `UnicodeEncodeError` on `±`/`─`/emoji prints.
- CONTEXT deviation: TASK-02 404-flow byte/rate guard + ASCII-only output
  (see Deviations above).
- TRACKER row status: `done` — "normal_traffic.py shipped; 60 s live run
  240/240 (100 %) Normal Traffic, zero rule overrides, clean Ctrl+C/error exits"
