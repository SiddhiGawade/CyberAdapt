# TASK-13 — Verify Evaluation E2E (live stack)

| | |
|---|---|
| **Wave** | C1 — **sequential** (after T12; same live Flask state) |
| **Depends on** | T10, T12 |
| **Input handoffs** | `handoffs/TASK-10_*.md`, `handoffs/TASK-12_*.md` |
| **Files you may touch** | `ml/scripts/` (check scripts only) |
| **Files you must NOT touch** | `ml/api.py`, `ml/src/*`, `server/`, `client/` — verify-only |
| **Goal** | Prove `/evaluation` reflects the live stream: rolling metrics move with traffic, pre/post-adaptation split populates after promotion, persistence + reset work |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. Your input handoffs
3. `00_MASTER_PLAN.md` — §8 `/evaluation` contract

## Protocol

```bash
# Continuing from T12's state (a v2 promotion already happened is ideal)
# 1. normal_traffic.py ≥30 s → GET /evaluation:
#    accuracy high, confusion matrix mostly diagonal row 0, window.size grows,
#    latency_p95_ms present
# 2. attack_campaign.py short phase → per_class_metrics gains attack rows;
#    watch f1_macro respond
# 3. pre_post_adaptation.last_adaptation set (from T12's promotion);
#    pre/post f1_macro + samples both populated — record actual delta
# 4. Restart Flask → window metrics survive (eval_window.jsonl)
# 5. /admin/reset → window cleared; <30 new samples → insufficient_data:true
# 6. Contract audit vs §8 field-by-field (class_names order, 7×7 matrix)
```

## Finish protocol (sequential — update shared files)

- `handoffs/TASK-13_verify-evaluation.md` — numbers + contract audit.
- Append `CONTEXT.md` §C/§A; set TRACKER.md rows.

## Definition of done

- [ ] Live metrics track traffic; `pre_post_adaptation` populated post-promotion
- [ ] Restart persistence + `insufficient_data` after reset verified
- [ ] §8 contract audited field-by-field
- [ ] Handoff with measured numbers; CONTEXT.md + TRACKER.md updated
