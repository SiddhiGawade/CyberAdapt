# HANDOFF — TASK-03 — Attack Campaign Generator

| | |
|---|---|
| **Task** | TASK-03 — `sensor/attack_campaign.py` |
| **Status** | `done` |
| **Wave** | A (parallel) |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- `sensor/attack_campaign.py` — sustained 6-phase attack campaign generator; emits randomized LBL::-tagged 52-slot flow envelopes to `/api/telemetry/ingest` (ingest mode) plus optional mild real-HTTP side effects against `--target` (live mode).

## Files modified

- none (only `sensor/attack_campaign.py` created, per spec)

## Interface surface shipped

```python
# CLI (all spec flags + one extra, --scale):
#   --key (or SENSOR_KEY env)  --url (or INGEST_URL env)
#   --mode ingest|live   --target <labrooms-url>   --scenario mixed|dos|bruteforce|sqli|exfil
#   --rate 6.0   --batch-size 6   --scale 1.0   --no-lbl-tag

PHASE_SECONDS = {"warmup": 30, "dos": 45, "bruteforce": 45, "sqli": 45, "exfil": 45, "cooldown": 30}
SCENARIOS     = {"mixed": [warmup,dos,bruteforce,sqli,exfil,cooldown], "<x>": [warmup,<x>,cooldown]}

# Emitted flow_ids (ground truth, master plan §5.4):
#   warmup/cooldown → LBL::Normal_Traffic::web-<rand4>
#   dos             → LBL::DoS::slowloris-<rand4>
#   bruteforce      → LBL::Brute_Force::login-<rand4>
#   sqli            → LBL::Web_Attacks::sqli-<rand4>
#   exfil           → LBL::Web_Attacks::exfil-<rand4>   (see Deviations)
#   --no-lbl-tag    → "<phase>-<rand8>"  (untagged)
# sensor_id per batch = f"attack-campaign-{phase}"
```

## Verification run

Stack (shared-stack rule: ports were free, I started these and left them up):
`mongod --dbpath %USERPROFILE%\mongodb-data` (:27017) · `python -m ml.api` with
`MODEL_PATH`/`PREPROCESSOR_PATH`→`ml/artifacts/models/` + `DEMO_MODE=1` (:5001) ·
`npm run dev` in `server/` (:5000). Fresh sensor key minted via `node scripts/seed-dev.js`.

```
$ python sensor/attack_campaign.py --key "ca_live_5d14…" --scenario mixed
  Scenario  : mixed  (warmup → dos → bruteforce → sqli → exfil → cooldown)
  Mode      : ingest   Rate: 6.0 flows/s   Batch: 6   LBL tags: on
═══ PHASE: warmup — 30 s ═══   → 180 flows, 180 accepted, 0 errors
═══ PHASE: dos — 45 s ═══      → 270 flows, 270 accepted, 0 errors
═══ PHASE: bruteforce — 45 s ═══ → 270 flows, 270 accepted, 0 errors
═══ PHASE: sqli — 45 s ═══     → 270 flows, 270 accepted, 0 errors
═══ PHASE: exfil — 45 s ═══    → 270 flows, 270 accepted, 0 errors
═══ PHASE: cooldown — 30 s ═══ → 180 flows, 180 accepted, 0 errors
  elapsed: 240.2 s   exit code 0
```

Per-phase labels (Mongo aggregate on run window, `sensorId`=`attack-campaign-<phase>`):

```
attack-campaign-bruteforce     Brute Force        270
attack-campaign-cooldown       Brute Force          6   ← model FP on normal envelopes
attack-campaign-cooldown       Normal Traffic     174
attack-campaign-dos            DoS                270
attack-campaign-exfil          Web Attacks        270
attack-campaign-sqli           Web Attacks        270
attack-campaign-warmup         Brute Force          4   ← model FP on normal envelopes
attack-campaign-warmup         Normal Traffic     176
LBL-tagged in window: 1440   (every emitted flow carried a LBL:: id)
```

Live `GET /api/telemetry/recent-flows` sample during dos phase:
`{"sensorId":"attack-campaign-dos","flowId":"LBL::DoS::slowloris-e1ac","threatLabel":"DoS","threatConfidence":0.985}`

Side checks:
```
$ --scenario dos --scale 0.15 --rate 10        → warmup/dos/cooldown, 170 flows, 0 errors, dos→DoS 70/70
$ --mode live --target http://localhost:5000    → "live target reachable"; 9 real requests sent, 0 failed
$ --mode live --target http://localhost:59999   → "⚠ target … unreachable — continuing to emit flows" once; runs clean
$ KeyboardInterrupt mid-run (SIGINT raised)     → "⏹ Ctrl+C — stopping campaign" + full summary + return 0
$ --no-lbl-tag                                  → flow_ids like "warmup-51f0aa2b" (untagged)
```

## Outputs produced

- 1,440 flows ingested + ML-labeled in the mixed run (all 6 phases, 0 ingest errors).
- Attack phases scored their intended label at 100%: DoS 270/270, Brute Force 270/270, Web Attacks 540/540 (sqli+exfil).
- Normal envelopes scored ~97% Normal; ~2–3% landed "Brute Force" as raw-model false positives (honest — LBL tag still carries truth).
- Sensor key minted: `ca_live_5d1483088f28ea9b364ad89d30adf66f797fc7004d4c5543523a6ac0b3391b6a` (company `acme-test.local`).

## Deviations from spec

1. **Extra CLI flag `--scale`** (phase-duration multiplier, default 1.0) — needed for smoke tests / rehearsal; full runs unaffected.
2. **Exfil flows tagged `LBL::Web_Attacks::exfil-…`** — `TARGET_CLASSES` has no "Exfiltration" class, and the exfil envelope (bwd 15–150 MB) trips `ml/api.py` rule 2 → label "Web Attacks". Tagging Web_Attacks keeps the LBL ground truth consistent with what the pipeline actually scores; `LBL::Exfiltration::*` would be an unresolvable class and fall through to the rule label anyway.
3. **UTF-8 stdout reconfigure at import** — Windows cp1252 consoles crash on `═`/`→`/`⚠`/`⏹` banner glyphs; guarded `sys.stdout.reconfigure(errors="replace")` added (script would not run at all without it).
4. File is ~345 lines vs "<~300" guideline — kept for readability (docstring + live-effects class); all spec features present.
5. sqli envelope keeps status 500 always (payload/duration/bytes are randomized instead) — a 403 would be caught by the Brute Force rule before the Web-Attacks rule fires, mixing labels inside the phase.

## Handoff notes for dependent tasks

- For TASK-04/05: LBL tags land in `TelemetryLog.flowId` exactly as `LBL::<Class_Name>::<desc>-<rand4>` — class uses underscores→spaces mapping per §5.4. `attack-campaign-exfil` docs carry `Web_Attacks` tags on purpose.
- For TASK-11/12: at default `--rate 6` a mixed run puts ~270 labeled attack samples per phase into the buffer in ~45 s — well over `MIN_ATTACK`/`MIN_BUFFER` needs; attack_ratio ≈ 1.0 during phases 2–5.
- Normal envelopes are not guaranteed "Normal Traffic" labels — the raw model FP'd ~2–3% into Brute Force. The `LBL::Normal_Traffic` tag is the reliable truth.
- Live-mode dribble sockets only support `http://` targets (warns + skips otherwise).
- Windows: real console Ctrl+C → KeyboardInterrupt → clean summary + exit 0 (verified by raising SIGINT in-process). Synthetic `GenerateConsoleCtrlEvent(CTRL_BREAK)` to a detached process group kills without raising — a Windows/CPython quirk, not script behavior; demo from a real terminal.
- Stack left running: mongod :27017, Flask :5001 (DEMO_MODE=1), Node :5000.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: Sensor key in use → `ca_live_5d1483088f28ea9b364ad89d30adf66f797fc7004d4c5543523a6ac0b3391b6a` (minted via seed-dev.js, company acme-test.local).
- CONTEXT fact: `sensor/attack_campaign.py` shipped — 6-phase `--scenario mixed`, `sensor_id=attack-campaign-<phase>`, LBL tags on all flows; exfil phase scores+tags `Web_Attacks` (no Exfiltration class exists).
- CONTEXT fact: ~2–3% of normal-envelope flows get raw-model label "Brute Force" — LBL tag is the reliable ground truth.
- CONTEXT deviation: TASK-03 added non-spec CLI flag `--scale` (phase-duration multiplier) for quick runs.
- Open issue: none.
- TRACKER row status: `done` — "6-phase campaign verified on live stack: 1,440 flows, attack phases labeled 100% correct (DoS/Brute Force/Web Attacks), LBL tags on all flow_ids."
