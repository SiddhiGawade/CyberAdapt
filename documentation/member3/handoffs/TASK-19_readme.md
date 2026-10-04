# HANDOFF — TASK-19 — README Update

| | |
|---|---|
| **Task** | TASK-19 — README Update |
| **Status** | `done` |
| **Wave** | D — **parallel** (with T18, after T17) |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | TASK-17 (final verified state), CONTEXT.md |

---

## Files created

- `documentation/member3/handoffs/TASK-19_readme.md` — this handoff

## Files modified

- `README.md` (root, only file touched) — flipped the four static placeholders
  to live, added the two generator scripts to "Send telemetry", and updated
  the API-reference tables to match. ~5 surgical edits, no restructuring.

## Interface surface shipped

n/a — documentation-only task. New README user-facing commands:

```bash
python sensor/normal_traffic.py --key "ca_live_YOUR_KEY" --interval 2 --batch-size 8 --duration 140
python sensor/attack_campaign.py --key "ca_live_YOUR_KEY" --scenario mixed --rate 12 --batch-size 6
```

(Both flags verified against the scripts' `argparse` definitions —
`sensor/normal_traffic.py:118-125`, `sensor/attack_campaign.py:319-334` — and
against T17's proven commands.)

## Verification run

Documentation edit — verified by inspection: all claims cross-checked against
CONTEXT.md §C and TASK-17 handoff. Specifics:

```
$ grep "add_argument" sensor/normal_traffic.py sensor/attack_campaign.py
→ --key/--url/--interval/--batch-size/--duration/--jitter/--lbl-tag  (normal)
→ --key/--url/--mode/--target/--scenario/--rate/--batch-size/--scale/--no-lbl-tag (campaign)

$ grep "adaptation/trigger|admin/reset" server/routes/telemetry.js
→ router.post('/adaptation/trigger', auth, …)  :261   (JWT, literal status passthrough)
→ router.post('/admin/reset',        auth, …)  :280   (JWT, DEMO_MODE enforced Flask-side)
```

## Outputs produced

README sections now read:

- **"✅ Working end-to-end"** — three new bullets after "Flask inference API":
  live drift monitoring (ADWIN/Page-Hinkley/DDM + PSI/KS on the ingest stream),
  drift-triggered gated retrain + hot-swap (`POST /adaptation/trigger` →
  202/409/422; `POST /admin/reset` under `DEMO_MODE=1`; `active_model.json`
  boot restore), rolling pseudo-labeled evaluation with pre/post split.
- **Dashboard table** — Concept Drift / Adaptation / Evaluation rows now
  describe live data (per-detector flags, gates, FORCE button, pre/post split);
  Explainability marked "(static placeholder)". Covers spec item 4 (dashboard
  pages poll live data).
- **"⚠️ placeholders"** — rewritten to cover only `/explain` (SHAP/LIME).
- **"⬜ Not yet implemented"** — dropped the two now-shipped items (live drift
  detection, drift-triggered retraining); SHAP/LIME + production deployment remain.
- **"Send telemetry" (§5)** — added `sensor/normal_traffic.py` and
  `sensor/attack_campaign.py` blocks with one-line usage + comment each, in the
  existing style.
- **API Reference** — Node table gains the `POST /api/telemetry/{adaptation/trigger,admin/reset}`
  JWT proxy row; Flask table splits `/explain` (static) from the three live GETs
  and adds `POST /adaptation/trigger` + `POST /admin/reset` rows.

## Deviations from spec

- Spec estimated "~10-line diff"; actual diff is ~40 lines touched. Justified:
  "README reflects live implementation accurately" required (a) the placeholder
  paragraph rewrite, (b) removing the two shipped items from "Not yet
  implemented", and (c) updating both API-reference tables — all in the same
  voice, no restructuring. The four content flips the spec enumerates are all
  present.
- Spec listed "KS" among detectors; README says "ADWIN / Page-Hinkley / DDM on
  pseudo-labels, PSI + KS on feature slots" — matches shipped
  `LiveDriftMonitor` (CONTEXT §B/C: PSI is feature-slot KS's sibling; both run).

## Handoff notes for dependent tasks

- For TASK-18 (demo runbook): README now documents `normal_traffic.py` /
  `attack_campaign.py` usage and the `/adaptation/trigger` + `/admin/reset`
  endpoints — the runbook can cite these verbatim.
- README.md is **untracked in git** (`??` in `git status`) — the file predates
  git tracking of it; no diff against HEAD exists.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: README.md updated (TASK-19) — placeholders flipped to live:
  ADWIN/PH/DDM + PSI/KS drift monitoring on ingest, drift-triggered gated
  retrain + hot-swap (`POST /adaptation/trigger`, `POST /admin/reset` under
  `DEMO_MODE=1`, `active_model.json` boot restore), rolling pseudo-labeled
  evaluation w/ pre/post split, dashboard pages poll live data; only `/explain`
  remains static. `sensor/normal_traffic.py` + `sensor/attack_campaign.py`
  documented under "Send telemetry"; API tables list Node POST proxies +
  Flask POST routes.
- Open issue: none.
- TRACKER row status: `done` — "README flipped static→live (drift monitor,
  gated retrain+hot-swap, rolling eval, live dashboard); generator scripts +
  POST endpoints documented; ~40-line surgical diff, no restructuring"
