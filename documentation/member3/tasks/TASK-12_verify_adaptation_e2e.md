# TASK-12 — Verify Adaptation E2E (live stack)

| | |
|---|---|
| **Wave** | C1 — **sequential** (after T11; shares the same live Flask state) |
| **Depends on** | T09, T11 |
| **Input handoffs** | `handoffs/TASK-09_*.md`, `handoffs/TASK-11_*.md` |
| **Files you may touch** | `ml/scripts/` (check scripts only) |
| **Files you must NOT touch** | `ml/api.py`, `ml/src/*`, `server/`, `client/` — verify-only; report bugs precisely, don't patch (see T11 note) |
| **Goal** | Prove the full adaptation loop on live traffic: buffer fills → drift auto-triggers retrain → gates → promotion v2 → hot-swap → persistence → reset |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. Your input handoffs — trigger semantics, cooldown, `active_model.json` behavior as shipped
3. `00_MASTER_PLAN.md` — §5.5, §8 (`/adaptation`, trigger, reset contracts)

## Protocol

```bash
# Clean slate: POST /admin/reset (DEMO_MODE=1 flask)
# 1. BUFFER — normal_traffic.py ≥60 s → GET /adaptation:
#    buffer.current_size grows, label_sources.high_confidence climbs
# 2. TRIGGER — attack_campaign.py (mixed or dos) → drift fires →
#    watch GET /adaptation: adaptation_in_progress true→false →
#    retraining_history gains entry: trigger mentions drift/ADWIN,
#    gates_passed all true → champion_version "v2"
#    → ml/artifacts/models/adaptive_champion_v2.joblib +
#      adaptive_preprocessor_v2.joblib + state/active_model.json exist
# 3. HOT-SWAP — GET /model-info shows v2 + adaptive path; /predict on an
#    attack vector still labels correctly under new champion
# 4. MANUAL — POST /adaptation/trigger (Flask direct AND via Node proxy
#    with JWT) → 202; immediate second → 409 busy
# 5. NEGATIVE — fresh reset + tiny buffer → trigger → 422 insufficient;
#    (if craftable: weak candidate → recorded rejection, champion unchanged)
# 6. PERSISTENCE — restart Flask → /adaptation still v2 + history
# 7. RESET — POST /admin/reset → v1, empty buffer, cleared drift
```

Record measured numbers: buffer size at trigger, time-to-promotion, candidate
vs champion F1 from the gate report, version bump.

## Finish protocol (sequential — update shared files)

- `handoffs/TASK-12_verify-adaptation.md` — numbers + contract audit.
- Append `CONTEXT.md` §C/§A; set TRACKER.md rows.

## Definition of done

- [ ] Auto-trigger on drift → promotion v1→v2 observed (or honest rejection documented with reason)
- [ ] Manual trigger via Flask + Node proxy; 409/422 paths verified
- [ ] Boot restore + `/admin/reset` verified
- [ ] `/adaptation` audited against §8 field-by-field
- [ ] Handoff with measured numbers; CONTEXT.md + TRACKER.md updated
