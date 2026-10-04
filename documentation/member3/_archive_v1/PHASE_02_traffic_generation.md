# PHASE 02 — Traffic Generation Suite

| | |
|---|---|
| **Goal** | Two reusable generators: a benign "normal browsing" stream and a sustained multi-wave **attack campaign** — the demo's traffic story |
| **Depends on** | nothing (may run parallel to Phase 01; needed before Phase 03 verification & Phase 06 demo) |
| **Enables** | Drift firing (Phase 01 proof), adaptation buffer fill (Phase 03), the live demo (Phase 06) |
| **Est. scope** | 2 new files in `sensor/`, no existing-file edits |

---

## Read first

1. `documentation/member3/00_MASTER_PLAN.md` — §4 (slots), §5.4 (`LBL::` tag), §7 (narrative)
2. `documentation/member3/TRACKER.md`
3. `sensor/simulate_attacks.py` — reuse `build_labrooms_flow()` semantics verbatim (same slot layout; copy or import it — prefer copying + extending so it stays standalone)
4. `sensor/mock_sensor.py` — CLI/loop conventions (`--key`, `--url`, `--interval`, `--batch-size`, `requests.Session`, `X-Sensor-Key` header)

## Why this phase exists

`simulate_attacks.py` fires **one** batch of 5 flows — enough for a screenshot,
not enough to push ADWIN over threshold or fill an adaptation buffer.
`mock_sensor.py` emits uniformly-random junk (durations 0–30 s, up to 750 KB
payloads) — the model labels it inconsistently, so it's useless as a "normal
baseline" for the demo. We need **controlled profiles**.

## Build

### 1. `sensor/normal_traffic.py` — benign stream generator

Emulates ordinary users browsing the Labrooms site. Per flow (52-slot vector,
same contract as `build_labrooms_flow`):

| Slot | Distribution (benign) |
|---|---|
| 1 duration µs | lognormal-ish: `random.lognormvariate(12.0, 0.6)` clamped 5 ms–900 ms |
| 2/3 fwd/bwd pkts | `1` (HTTP req/resp) — occasionally 2 |
| 4 fwd bytes | `random.randint(180, 2600)` (normal request size) |
| 5 bwd bytes | `random.randint(400, 80_000)` (page/asset response) |
| 6/7 | same as slot 4 |
| 14 bytes/s | derived: `(fwd+bwd)/(duration_s)` — compute, don't invent |
| 44 status | `200` w.p. 0.93, `304` 0.03, `404` 0.03, `301` 0.01 |

CLI: `--key`, `--url`, `--interval` (default 2 s), `--batch-size` (default 8),
`--duration` (optional total seconds, else infinite), `--jitter`.
`sensor_id = "normal-traffic-gen"`. Print one line per batch like mock_sensor.

Must produce flows the champion labels **Normal Traffic** and no rule
override fires — that's the acceptance bar (verify, don't assume).

### 2. `sensor/attack_campaign.py` — sustained scenario runner

Runs a **timed campaign** of attack waves against the Labrooms environment.
Two modes:

**`--mode ingest` (default, reliable):** emits attack-profile flows straight to
`/api/telemetry/ingest`, exactly like `simulate_attacks.py` but sustained,
parameterized, and phased.

**`--mode live` (showmanship):** additionally fires real HTTP requests at
`--target <labrooms-url>` while emitting the matching flow vectors —
slow-ish requests with long-held connections (threads + `requests` with
dribbled headers), login `POST` brute-force bursts, SQLi-looking query strings
(`/search?q=' OR 1=1--`), and one large download. The real requests are for
audience effect; the emitted vectors are what the pipeline scores. If
`--target` unreachable, warn once and continue emitting flows.

**Campaign phases** (`--scenario mixed`, default):

```
1. warmup     30 s  — normal-only trickle (lets baseline settle)
2. dos        45 s  — Slowloris profile: duration 30–90 s, tiny bytes, status 504
3. bruteforce 45 s  — duration 1–20 ms, fwd_bytes 1–4 k, status 401/403, high bytes/s
4. sqli       45 s  — fwd_bytes 8–25 k, status 500, moderate duration
5. exfil      45 s  — bwd_bytes 15–150 MB, status 200, duration ~1 s
6. cooldown   30 s  — back to normal trickle
```

Attack vector builders = the four shapes in `simulate_attacks.py` but with
**randomized parameters per flow** inside each phase's envelope (randomize
duration/bytes/status within range — constant vectors look fake and give ADWIN
a trivial step function; slight variance is more realistic).

CLI: `--key`, `--url`, `--target` (live mode), `--scenario mixed|dos|bruteforce|sqli|exfil`,
`--rate` (flows/sec, default 6), `--batch-size`, `--no-lbl-tag`.
`sensor_id = f"attack-campaign-{phase}"` so the dashboard's sensor column tells
the story.

**Ground-truth tagging:** prefix every flow_id `LBL::<CLASS>::<desc>-<rand>`
(`LBL::DoS::slowloris-a3f9`, `LBL::Brute Force`→`LBL::Brute_Force::`) —
master plan §5.4; phases 03/04 use these labels for buffer/eval. `--no-lbl-tag`
disables (pure pseudo-label experiment).

Print a phase banner on transitions (`═══ PHASE: dos — 45 s ═══`) and a final
summary (flows sent per phase, HTTP results, elapsed).

### 3. Shared notes

- Both scripts: `requests`, stdlib only, no new deps. Follow mock_sensor's CLI
  style and `X-Sensor-Key` header.
- KeyboardInterrupt → print summary, exit 0.
- Keep scripts under ~250 lines each; docstring header in the existing style.

## Do NOT

- Don't modify `simulate_attacks.py` or `mock_sensor.py` — they're referenced in README.
- Don't touch `server/` — ingest already accepts what these send.
- Don't put real credentials/targets in the files — `--target`/`--key` are CLI args.

## Verification

```bash
# Terminal A: stack running (mongod, node :5000, flask :5001)
# Normal generator — 60 s
python sensor/normal_traffic.py --key "ca_live_…" --duration 60
# → GET /api/telemetry/recent-flows (or dashboard): labels = Normal Traffic
# → spot-check 30 flows: ≥28 Normal Traffic, zero rule-override labels

# Attack campaign — full scenario (~4 min)
python sensor/attack_campaign.py --key "ca_live_…" --scenario mixed
# → during phases 2–5, recent-flows shows DoS/Brute Force/Web Attacks labels
# → if Phase 01 done: GET /concept-drift flips to drift during 'dos'
# → Ctrl+C mid-run exits cleanly with summary
```

Record actual label counts in the tracker — "sends traffic" is not acceptance,
"classified as intended" is.

## Definition of done

- [ ] `normal_traffic.py` → ≥90% Normal labels over a 60 s run
- [ ] `attack_campaign.py` runs the 6-phase scenario, each phase's flows get
      the intended threat labels (DoS/Brute Force/Web Attacks)
- [ ] `LBL::` tags present in emitted flow_ids
- [ ] Both scripts Ctrl+C-clean, no stack trace spam on connection errors
- [ ] TRACKER.md updated
