# TASK-03 — Attack Campaign Generator (`sensor/attack_campaign.py`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T01–T07) |
| **Depends on** | none |
| **Input handoffs** | none |
| **Files you may touch** | `sensor/attack_campaign.py` (new) only |
| **Files you must NOT touch** | `simulate_attacks.py`, `mock_sensor.py`, `server/`, everything else |
| **Goal** | A sustained, phased attack campaign — pushes ADWIN over threshold and fills the adaptation buffer with `LBL::`-tagged attack samples |

---

## Read first

1. `documentation/member3/CONTEXT.md` — sensor key may be listed in §A
2. `00_MASTER_PLAN.md` — §4 (slots), §5.4 (`LBL::` tag convention), §7 (narrative)
3. `sensor/simulate_attacks.py` — the four attack vector shapes (Slowloris/DoS, exfil, brute force, SQLi/web) — copy + extend; keep standalone
4. `sensor/mock_sensor.py` — CLI conventions

## Build — `sensor/attack_campaign.py`

A **timed campaign** of attack waves. Two modes:

**`--mode ingest` (default, reliable):** emits attack-profile flows straight to
`/api/telemetry/ingest` — like `simulate_attacks.py` but sustained,
parameterized, phased.

**`--mode live` (showmanship):** additionally fires real HTTP requests at
`--target <labrooms-url>` while emitting matching flow vectors — slow requests
with long-held connections (threads + `requests` with dribbled headers), login
`POST` brute-force bursts, SQLi query strings (`/search?q=' OR 1=1--`), one
large download. Real requests are audience effect; emitted vectors are what the
pipeline scores. If `--target` unreachable → warn once, keep emitting flows.

**Campaign phases** (`--scenario mixed`, default):

```
1. warmup     30 s — normal-only trickle (baseline settles)
2. dos        45 s — Slowloris: duration 30–90 s, tiny bytes, status 504
3. bruteforce 45 s — duration 1–20 ms, fwd_bytes 1–4 k, status 401/403, high bytes/s
4. sqli       45 s — fwd_bytes 8–25 k, status 500, moderate duration
5. exfil      45 s — bwd_bytes 15–150 MB, status 200, duration ~1 s
6. cooldown   30 s — back to normal trickle
```

`--scenario dos|bruteforce|sqli|exfil` runs a single attack phase between
warmup/cooldown (shorter demo option).

- **Randomize parameters per flow** inside each phase's envelope — constant
  vectors look fake and give ADWIN a trivial step function.
- CLI: `--key`, `--url`, `--target` (live mode), `--scenario`, `--rate`
  (flows/sec, default 6), `--batch-size`, `--no-lbl-tag`.
- `sensor_id = f"attack-campaign-{phase}"` — the dashboard's sensor column
  tells the story.
- **Ground-truth tagging:** every flow_id prefixed `LBL::<CLASS>::<desc>-<rand>`
  (`LBL::DoS::slowloris-a3f9`, `LBL::Brute_Force::login-b7c2`) — §5.4;
  TASK-04/05 consume these labels. `--no-lbl-tag` disables (pure pseudo-label
  experiment).
- Phase banner on transitions (`═══ PHASE: dos — 45 s ═══`) + final summary
  (flows/phase, HTTP results, elapsed). Ctrl+C → summary + exit 0.
- `requests` + stdlib only; < ~300 lines; existing sensor docstring style.

## Do NOT

- Don't modify `simulate_attacks.py`/`mock_sensor.py`.
- No real credentials/targets in the file.
- Don't make live mode's HTTP requests aggressive beyond the listed patterns —
  this is a demo against a lab app.

## Verification (needs live stack — shared-stack rule §5.7)

```bash
python sensor/attack_campaign.py --key "ca_live_…" --scenario mixed
# → during phases 2–5: GET /api/telemetry/recent-flows shows DoS / Brute Force /
#   Web Attacks labels matching the active phase
# → Ctrl+C mid-run exits cleanly with summary
# → spot-check emitted flow_ids carry LBL:: tags
```

Record actual per-phase label counts in the handoff.

## Finish protocol

- `handoffs/TASK-03_attack-campaign.md` from template — per-phase label evidence.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.** If you minted a
  key, put it in "Merge suggestions".

## Definition of done

- [ ] 6-phase mixed scenario runs; each phase's flows get intended labels
      (DoS / Brute Force / Web Attacks)
- [ ] `LBL::` tags present in emitted flow_ids (and `--no-lbl-tag` works)
- [ ] Single-scenario mode works (`--scenario dos`)
- [ ] Ctrl+C clean, connection-error handling sane
- [ ] Handoff written with evidence
