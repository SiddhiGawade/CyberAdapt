# CyberAdapt — Demo Runbook (presenter copy)

> **The live concept-drift → auto-retrain → promotion demo, rehearsed and
> timed.** Every command below was run end-to-end twice on 2026-10-04
> (TASK-17 rehearsal). Timings quoted are **measured**, not estimated.
>
> Extends the root `README.md` "How to Run" — that doc gets the stack up;
> this doc is the *performance script*.
>
> **Story in one line (§7.6):** *"The model detected that the world changed
> and healed itself — nobody retrained anything."*

---

## 0. Mechanics you MUST internalize before presenting

These four rules decide whether the demo works. Skim the failure playbook
(§5) once before showtime.

1. **Warm-up gate.** The drift monitor reports `status:"warming_up"` until
   it has seen **≥500 flows**. Drift cannot latch while warming up — at the
   presentation cadence (4 flows/s) that's ~125 s of baseline. This is why
   Act 1 exists; do not shorten it below 500 flows.
2. **Priming before drift.** Auto-promotion needs a buffer of **≥200 labeled
   flows, ≥30 non-Normal, ≥2 classes** *before the first drift event fires*.
   Normal traffic alone fills the buffer with `high_confidence` Normal labels
   only — if drift fires on an all-Normal buffer the adapter records
   `skipped — insufficient buffer` and the story stalls. That's why the
   `seed dos 90` step (the attack reveal) runs **before** `attack_campaign`.
3. **The skipped-event latch.** A *skipped* drift event **holds the drift
   latch** — no further auto-events fire until a retrain *completes*
   (promoted **or** rejected, either runs `reset_reference()`) or you hit
   `/admin/reset`. A skipped event is not a crash, but it silently suppresses
   later events — the #1 "why did nothing happen" cause.
4. **Buffer composition → gate outcome.** On a normal-heavy buffer retrains
   promote deterministically (delta gates are ≥ −0.01). On an
   attack-dominated buffer (≳3.7 k tagged attack labels) retrains can be
   **honestly REJECTED** (`gate_emerged_recall` + `gate_normal_fpr` fail on
   the chronological validation tail). Both outcomes are demo gold — script
   which one you want (see Act 2 step 3).

**Bonus mechanics (for Q&A):** PSI is the fast detector and always wins the
event latch first; the history row will read `PSI drift alert (feature_psi)`,
not "ADWIN drift". ADWIN/PageHinkley `drift_signal` is a **single-batch
flicker** — invisible at the dashboard's 3 s polling; only catchable in a
terminal at ≤1 s polling during a sharp transition (rehearsal caught
`ADWIN=True` at cooldown decay, `PH=True` ~130 flows later).

---

## 1. T-minus setup (~10 min before the audience arrives)

Five terminals. Commands are **Windows PowerShell**; run from repo root
unless noted. Repo root:

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project"
```

### 1.1 Port check — reuse, don't restart

```powershell
netstat -ano | findstr "LISTENING" | findstr ":27017 :5000 :5001 :3000"
```

Expected: 4 LISTENING lines if the stack is up. **Shared-stack rule:** if a
port is already listening, reuse that service — never kill a service you
didn't start. Start only what's missing, in this order.

### 1.2 Terminal 1 — MongoDB :27017

```powershell
& "C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe" `
    --dbpath "$env:USERPROFILE\mongodb-data" --bind_ip localhost --port 27017
```

Leave open all session. (`mongod` is not a Windows service on this box.)

### 1.3 Terminal 2 — Node API :5000

```powershell
cd server
npm run dev
```

Expected: `CyberAdapt API listening on port 5000`.
Requires `server/.env` with `ML_API_URL=http://localhost:5001` (already set).

### 1.4 Terminal 3 — Flask ML API :5001  ← `DEMO_MODE=1` is mandatory

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project"
.venv\Scripts\Activate.ps1
$env:MODEL_PATH="ml/artifacts/models/champion_model.joblib"
$env:PREPROCESSOR_PATH="ml/artifacts/models/preprocessor.joblib"
$env:DEMO_MODE="1"          # REQUIRED or /admin/reset returns 403
$env:PORT="5001"
python -m ml.api
```

Expected: `Starting CyberAdapt ML Inference API on port 5001`.
Without `MODEL_PATH`/`PREPROCESSOR_PATH` the API looks in `ml/artifacts/`
(nonexistent) and boots unready.

### 1.5 Terminal 4 — Dashboard :3000

```powershell
cd client
npm run dev
```

Expected: Vite ready. **Open `http://localhost:3000` — NOT `127.0.0.1:3000`**
(Vite binds IPv6 `[::1]` on this box; `127.0.0.1` refuses). Log in as
`admin@acme-test.local` / `Test@1234`. Open tabs: **Live Traffic**,
**Concept Drift**, **Adaptation**, **Evaluation**.

### 1.6 Terminal 5 — driver shell (runs all generators/check scripts)

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project"
.venv\Scripts\Activate.ps1
$env:SENSOR_KEY="ca_live_5d1483088f28ea9b364ad89d30adf66f797fc7004d4c5543523a6ac0b3391b6a"
```

> If ingest returns 401/403 the DB was re-seeded — run
> `node server/scripts/seed-dev.js` (in `server/`), copy the new
> `ca_live_…` key into `$env:SENSOR_KEY`, **and** update `SENSOR_KEY` on
> line 37 of `ml/scripts/check_adaptation_api.py` (it's hardcoded; the
> `seed` command uses it, not the env var).

### 1.7 Pre-flight sanity + clean slate

```powershell
# 1) Flask healthy, model loaded
Invoke-RestMethod http://127.0.0.1:5001/health
#   → @{status=operational; model_ready=True; ...}

Invoke-RestMethod http://127.0.0.1:5001/model-info | Select-Object version
#   → version = v1 (or vN if promoted before — reset fixes that)

# 2) Clean slate — wipes drift state, buffer, history, eval window,
#    reloads the ORIGINAL v1 artifacts
python ml/scripts/check_adaptation_api.py reset
#   → [reset] -> HTTP 200 {"status":"reset","cleared":["active_model",
#      "drift_state","buffer","history","model_artifacts","eval_window"]}
#     (`active_model` only appears in the list the FIRST time — it's dynamic)

python ml/scripts/check_adaptation_api.py status
#   → version=v1 in_progress=False buffer=0/5000 (0.0%) labels=[ro:0 hc:0 tag:0]
#     hist=0 last_event=None | drift_state=stable n=0 ... atk_ratio=0.0000
```

Use `127.0.0.1` (not `localhost`) for API checks — `localhost`→`::1` adds
~2 s/request against IPv4-bound Flask on this box. The check scripts
already use `127.0.0.1`.

**Housekeeping (optional):** delete stale `adaptive_champion_vN.joblib` /
`adaptive_preprocessor_vN.joblib` files in `ml/artifacts/state/` from prior
runs — cosmetic only.

---

## 2. The 4-act script (~8–9 min wall, §7 narrative)

| Act | Beats | Wall time |
|---|---|---|
| 1 — Baseline | normal traffic → stable, warm-up→active | ~2.5 min |
| 2 — Reveal | DoS seed → drift ~0.9 s → auto-promotion <1 s → FORCE demo | ~2 min |
| 3 — Campaign | mixed attack wave → 2nd auto-promotion, floods, PSI peaks | ~4 min |
| 4 — Recovery | benign traffic + evaluation metrics | ~1 min |

> **Timing note:** all numbers measured in TASK-17 Run 2 (spec cadence).
> Faster variant in §3 if you need a ~6 min cut.

### ACT 1 — "Steady state" (§7.2)

**Step 1.** Driver terminal:

```powershell
python sensor/normal_traffic.py --interval 2 --batch-size 8 --duration 140
```

Expected: `[Batch NNNN] OK Sent 8 flows -> HTTP 202` ~every 2 s;
finish line `560 flows / 140.0 s (4.0 flows/s), 0 errors`.

**Step 2.** While it runs — **Live Traffic** tab: every row green
`Normal Traffic`, conf ≥0.99.

**Step 3.** **Concept Drift** tab: `status` flips `warming_up → active` at
n≈500–552; `drift_state: stable`; all detector cards green; PSI table
~0.00–0.10 (measured max 0.0976).

**Step 4.** **Adaptation** tab: buffer `current_size` climbing toward ~560,
`label_sources.high_confidence` == current_size (untagged normals earn
high-confidence pseudo-labels — §5.4 of the design).

> **SAY:** *"This is the Labrooms production app in steady state — sensors
> stream flows, the model calls everything Normal with >99% confidence, and
> the drift monitor sees a stable world: PSI scores near zero."*

### ACT 2 — "The world changes" (§7.3–7.4)

> **Priming choreography — DO NOT REORDER.** This step is both the attack
> reveal **and** the buffer primer: 90 `LBL::DoS`-tagged flows land in the
> buffer as `flow_id_tag` labels *and* fire the drift that consumes them.
> If you run `attack_campaign` first, its warmup phase fires drift on an
> all-Normal buffer → `skipped` → latch held → the demo looks dead.

**Step 1.** Driver terminal:

```powershell
python ml/scripts/check_adaptation_api.py seed dos 90 30
```

Expected output (measured Run 2, @ n=620):

```
[seed dos] +30 via ingest -> HTTP 202 accepted=30
    version=v1 ... labels=[ro:0 hc:560 tag:30] | drift_state=warning n=590 ...
[seed dos] +30 via ingest -> HTTP 202 accepted=30
    version=v1 ... drift_state=drift n=620 ... atk_ratio=1.0000
    (within the same second →)
    version=v2 hist=1 last_event=promotion ... drift_state=stable/warning
```

**Measured:** drift event **≈0.9 s** after attack start (n=620, PSI ≥3
slots); auto-promotion **v1→v2 <1 s later** (daemon retrain ~0.13 s);
buffer at trigger **620** (560 hc + 60 tag); all **4 gates PASS**; champion
macro-F1 0.47 → candidate 1.0, DoS recall 1.0.

**Step 2.** **Concept Drift** tab: red DRIFT banner, `drift_events` shows
`PSI drift alert (feature_psi)`, `attack_ratio_recent` → 1.00.

**Step 3.** **Adaptation** tab: `champion_version v2`, new PROMOTED history
row, all 4 gates green, `last_event: promotion`.

**Step 4 — FORCE demo (script this deliberately):** while the buffer is
still normal-heavy, press **FORCE RETRAIN** on the Adaptation page (or CLI:
`python ml/scripts/check_adaptation_api.py proxytriggerx2` — Node+JWT path).

Expected: press 1 → `202 accepted` → **v2→v3** (deterministic promote on a
normal-heavy buffer); press 2 → `409 busy` → proves
`adaptation_in_progress` server-side. (If you press FORCE *late*, after the
campaign, expect an honest REJECTED row instead — equally good talking
point, different slide. Pick one.)

> **SAY:** *"Watch the drift score spike as the attack wave hits — PSI
> latched a drift event under a second in."* → *"The drift event triggered
> an automatic retrain on the labeled buffer; the candidate passed all four
> quality gates, so the platform promoted it — version bump v1→v2, no human
> touched anything."*

**Step 5.** Wait ~60 s (auto-retrain cooldown — observed `skipped —
cooldown active (44s remaining)` on the next event otherwise).

### ACT 3 — "Sustained attack" (§7.3 continued)

**Step 1.** Driver terminal:

```powershell
python sensor/attack_campaign.py --scenario mixed --rate 12 --batch-size 6
```

Expected: `2,880 flows / ~241 s, 0 errors` — 6 phases (warmup 30 s → dos /
bruteforce / sqli / exfil 45 s each → cooldown 30 s), phase banners print
`═══ PHASE: <name> ═══`.

**Step 2 — narrate the beats as they land (measured Run 2):**

| When | What happens | Where to look |
|---|---|---|
| ~15 s in (warmup) | **2nd auto-promotion v3→v4** — warmup normals come from a different generator → PSI catches the *covariate shift* (`attack_ratio 0.00`) | Adaptation: PROMOTED row #2; ConceptDrift: new event |
| ~30 s (dos phase) | next PSI event consumed but `skipped — cooldown active (~44s remaining)`; **latch stays `drift`** | Adaptation `last_event: skipped` |
| attack phases | `attack_ratio_recent → 1.00`; PSI peaks **s1≈9, s5≈12, s14≈7, s44≈10** | ConceptDrift PSI table + Live Traffic flood |
| attack phases | Live Traffic: 100% DoS → Brute Force → Web Attacks (measured 540/540 per phase); Overview red attack banner | Live Traffic / Overview tabs |
| cooldown decay | ADWIN `drift_signal` flickers True for ~1 batch — terminal only: `python ml/scripts/check_drift_api.py poll 1` | terminal, not the 3 s UI |

> **SAY:** *"The campaign's opening phase is benign traffic from a
> different generator — watch the monitor catch even that distribution
> change and promote again. Now the real DoS wave: attack ratio pins at
> 1.0, PSI on the byte-rate features hits 9–12 — two orders of magnitude
> above baseline."*
>
> **If asked "why didn't the next drift event promote?":** *"Cooldown
> protection — one auto-retrain per 60 s; the event was recorded as skipped
> and the latch holds until a retrain completes."*

### ACT 4 — "Recovery + proof" (§7.5)

**Step 1.** Driver terminal — tagged benign traffic for honest metrics:

```powershell
python sensor/normal_traffic.py --lbl-tag --interval 2 --batch-size 8 --duration 25
```

Expected: ~100 flows, `LBL::Normal_Traffic::` ids → ground-truth rows in
the eval window.

> **Honesty note:** if the last drift event was *skipped* (latch held), no
> "world healed" events fire — that is correct latch behavior, narrate it.
> If the last retrain completed (promoted/rejected), recovery normals can
> fire fresh PSI events.

**Step 2.** **Evaluation** tab: accuracy ~1.000, confusion matrix diagonal
(row-0 off-diagonal = honest false positives), per-class rows for
DoS/Brute Force/Web Attacks/Normal, `pre_post_adaptation` strip.

> **Pre/post caveat:** check this page **immediately after a promotion** —
> the window is the last 500 labeled rows, so `pre` slides out of view
> ~500 rows after `last_adaptation`. Right after the bump, measured split
> was pre {f1 1.0, n 440} / post {f1 1.0, n 60}.

**Step 3.** CLI snapshot for the record:

```powershell
python ml/scripts/check_evaluation_api.py snap
python ml/scripts/check_adaptation_api.py status
# → version=v4 hist=3 ... (Run 2 end state: auto v2 · manual v3 · auto v4)
```

> **SAY:** *"Predictions stayed correct under the new champion — the model
> detected that the world changed and healed itself."*

**Step 4 — optional robustness flex (30 s):** in Terminal 3, Ctrl+C Flask →
generators still get `202` (fire-and-forget: ingest never depends on ML),
Node GET proxies return `503` → dashboards show ML-offline. Restart Flask
(same env vars) → champion restored to latest `vN` via `active_model.json`,
drift + eval state intact (buffer intentionally resets).

**Post-demo:** leave state for Q&A, or return to clean with
`python ml/scripts/check_adaptation_api.py reset`.

---

## 3. Timing reference — measured (TASK-17, live stack)

| Metric | Run 1 (fast cadence) | Run 2 (spec cadence — this script) |
|---|---|---|
| Baseline traffic | 1,888 fl / 60 s @ 31.5 f/s | **560 fl / 140 s @ 4.0 f/s** |
| `warming_up→active` | n≈500 | n≈552 |
| **time-to-drift after attack start** | ≈0.8 s | **≈0.9 s** |
| **drift event → promotion** | <1 s (daemon ≈0.13 s) | **<1 s** |
| attack-seed start → v2 wall | ~1.4 s | **~1.5 s** |
| **buffer at first trigger** | 1,948 | **620** (range 620–1,948) |
| Promotions in full arc | v1→v2 auto, v2→v3 auto | v1→v2 auto, v2→v3 FORCE, v3→v4 auto |
| Gates on normal-heavy buffer | 4/4 PASS (f1 0.49→1.0) | 4/4 PASS |
| FORCE on attack-heavy buffer | REJECTED (WA recall 0.37<0.70, FPR 0.60>0.05) | — |
| Mixed campaign | 2,880 fl / 241 s | 2,880 fl / ~241 s |
| Per-phase label accuracy | 540/540 attack each; normals ~98% | identical |
| PSI peaks | s1 9.32, s5 12.09, s14 5.73, s44 10.24 | s1 8.97, s5 12.01, s14 7.31, s44 10.24 |
| FORCE ×2 (Node+JWT) | 202 → 409 | 202 → 409 |

**Compressed cut (~6 min):** baseline at
`--interval 0.5 --batch-size 16 --duration 60` (1,888 flows, Run-1 proven),
skip the FORCE beat, keep everything else.

---

## 4. Failure playbook

| Symptom | Cause | Fix / narrate |
|---|---|---|
| No drift event during Act 2 | `status` still `warming_up` (<500 flows) — baseline cut short | Check `check_drift_api.py once` → `status=…`; extend normal_traffic until `active`, then re-seed |
| Drift fired, `last_event=skipped — insufficient buffer` | Buffer was all-Normal at fire time — priming step skipped/reordered | **Latch is now held** → FORCE a manual retrain (`proxytrigger`) once the campaign has filled ≥30 non-Normal tags — promotion clears the latch — or `/admin/reset` and restart the arc |
| Later drift events never appear | A *skipped* event holds the latch; auto-events suppressed until a completed retrain or reset | By design — narrate: "the latch holds so we don't spam retrains"; FORCE or reset to clear |
| History row shows REJECTED | Attack-dominated buffer → `gate_emerged_recall`/`gate_normal_fpr` honestly veto the candidate | **Not a failure** — show the red gates: "the platform refused to ship a model that would hurt detection." Champion unchanged |
| FORCE → `409 busy` | A retrain is already running (they take ~0.15–0.5 s) | Expected — this IS the busy-path proof |
| FORCE → `422 insufficient` | Buffer <200 labeled / <30 non-Normal / <2 classes | Wait for more traffic, retry |
| Flask process dies | — | Ingest keeps returning **202** (fire-and-forget — narrate the decoupling); Node GETs → `503`, UI shows ML-offline. Restart Flask → boot restores `vN` via `active_model.json`; drift/eval state persists, buffer intentionally resets |
| Demo needs a mid-run do-over | — | `python ml/scripts/check_adaptation_api.py reset` → v1, n=0, buffer 0 → restart at Act 1 |
| `127.0.0.1:3000` refused in browser | Vite binds `[::1]` on this box | Use `http://localhost:3000` |
| API checks time out / feel laggy | `localhost:5001` → ::1 costs ~2 s/req | Use `127.0.0.1` (check scripts already do) |
| Generators get 401/403 | Sensor key revoked / DB re-seeded | `node server/scripts/seed-dev.js` → new key → `$env:SENSOR_KEY` + line 37 of `check_adaptation_api.py` |
| ADWIN/PH cards never show `drift_signal=True` | Single-batch flicker, invisible at 3 s polling | Expected — PSI owns the latch; run `check_drift_api.py poll 1` in a terminal during cooldown decay to catch it, or skip the claim |
| `npm run build` chunk warning | >500 kB bundle — pre-existing | Non-issue, ignore |

---

## 5. Screenshot checklist

- [ ] **Live Traffic** — green `Normal Traffic` rows at conf ≥0.99 (Act 1)
- [ ] **Concept Drift** — `active` + `stable`, all detectors green, PSI ~0 (Act 1)
- [ ] **Adaptation** — buffer `current_size`/`label_sources.high_confidence` climbing (Act 1)
- [ ] **Live Traffic** — red flood: DoS → Brute Force → Web Attacks, `attack_ratio 1.00` (Act 2–3)
- [ ] **Concept Drift** — red DRIFT banner + events list row `PSI drift alert (feature_psi)` (Act 2)
- [ ] **Concept Drift** — PSI table peaks (slot 1 ≈9, slot 5 ≈12, slots 14/44 ≈7–10) (Act 3)
- [ ] **Adaptation** — `champion_version` bump + PROMOTED row + 4/4 green gates (Act 2, then Act 3)
- [ ] **Adaptation** — RETRAINING badge / second FORCE → `409 busy` (Act 2)
- [ ] **Adaptation** — REJECTED row with red `gate_emerged_recall`/`gate_normal_fpr` (bonus, attack-heavy FORCE) 
- [ ] **Overview** — attack alert banner during campaign phases (Act 3)
- [ ] **Evaluation** — accuracy card ~1.0 + 7×7 matrix + per-class rows (Act 4)
- [ ] **Evaluation** — pre/post F1 strip **immediately** post-promotion (window slides after ~500 rows)
- [ ] **Filesystem** — `ml/artifacts/state/adaptive_champion_vN.joblib` + `active_model.json` (promotion artifacts)
- [ ] **Robustness (bonus)** — generator 202s continuing + Node 503s while Flask is down; restored `vN` after restart

---

*Sources: TASK-17 rehearsal handoff (all measured numbers, ×2 runs), master
plan §7 narrative + §8 contracts, CONTEXT.md merged mechanics. Authoring
date: 2026-10-04.*
