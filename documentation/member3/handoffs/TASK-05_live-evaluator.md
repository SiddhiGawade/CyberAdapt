# HANDOFF — TASK-05 — Live Evaluator Module

> Filled per `handoffs/_TEMPLATE.md`. Parallel wave — CONTEXT.md/TRACKER.md
> intentionally untouched; merge suggestions below.

| | |
|---|---|
| **Task** | TASK-05 — Live Evaluator Module (`ml/src/evaluation/live_evaluator.py`) |
| **Status** | `done` |
| **Wave** | A — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- `ml/src/evaluation/live_evaluator.py` — `LiveEvaluator`: rolling-window pseudo-labeled metrics, pre/post-adaptation split, `eval_window.jsonl` persistence. (~430 lines; no other repo files touched.)

## Files modified

- none

## Interface surface shipped

Exact signatures other tasks (TASK-10 wires) call against:

```python
# ml/src/evaluation/live_evaluator.py
class LiveEvaluator:
    def __init__(self, state_path: Path, window: int = 500): ...
    def record(self, records: List[dict], latency_ms: float) -> None:
        """Append pseudo-labeled rows only (§5.4 rule — same as adapter)."""
    def get_metrics(self) -> dict:
        """Exact §8 /evaluation contract; insufficient_data when <30 samples."""
    def reset(self) -> None: ...

# module-level helper (exported; mirrors §5.4 — identical to adapter logic):
def _resolve_pseudo_label(record: Dict[str, Any]) -> Optional[int]: ...
```

`get_metrics()` return shape (real, verified):

```python
{
  "dataset": "Live Labrooms stream (pseudo-labeled)",
  # "insufficient_data": True   # present ONLY when size < 30
  "window": {"size": int, "capacity": int, "since": "…Z" | None},
  "overall_metrics": {"accuracy", "precision_macro", "recall_macro",
                      "f1_macro", "latency_p95_ms"},
  "per_class_metrics": {cls: {"precision","recall","f1","support"} for cls in TARGET_CLASSES},
  "confusion_matrix": [[7x7 ints]],          # metrics.py confusion_matrix_raw
  "class_names": list(TARGET_CLASSES),
  "pre_post_adaptation": {
      "pre":  {"f1_macro": float, "samples": int},
      "post": {"f1_macro": float, "samples": int} | None,   # None only when never promoted
      "last_adaptation": str | None,
  },
}
```

`record()` consumes §9.1 `batch_record`s. Rows persisted per batch to
`eval_window.jsonl` (≤ `window` lines, tmp+replace write):

```python
{"ts": "<UTC ISO Z>", "ts_epoch": <float>, "y_true": <int>, "y_pred": <int>,
 "conf": <float|None>, "confidence": <float|None>, "version": <str>}
```

## Verification run

In-process (api.py not wired — verified with synthetic §9.1 records). Test
script written to `%TEMP%` (repo untouched). 45 checks, all PASS:

```
$ .venv\Scripts\python.exe %TEMP%\test_live_evaluator.py
== pseudo-label resolution (§5.4) ==
PASS - LBL:: tag -> DoS idx
PASS - LBL:: underscores -> spaces
PASS - LBL:: bad class -> falls through -> excluded
PASS - rule_override -> rule label
PASS - high-conf Normal -> Normal
PASS - conf 0.89 Normal -> excluded
PASS - conf None Normal -> excluded
PASS - attack no-rule -> excluded (not LBL, not rule)
PASS - LBL wins over rule_override
== insufficient_data path (10 labeled) ==
PASS - insufficient_data == True  / window.size==10 / accuracy zeroed /
       7x7 zero cm / latency_p95 recorded / pre_post last_adaptation null
PASS - unlabeled flows not recorded (50 unlabeled -> size 0)
== sufficient path (40 labeled, all correct) ==
PASS - no insufficient_data key / size==40 / accuracy==1.0 / f1==1.0 /
       latency_p95==4.2 / per_class f1 key remapped / support==30 /
       cm diag==40 / dataset label / window.since ends "Z"
PASS - all-wrong accuracy == 0.0
== pre/post adaptation split ==
PASS - last_adaptation == promo_ts / pre.samples==20 / post.samples==20 /
       pre.f1 (0.000) < post.f1 (1.000) / post.f1==1.0
PASS - never-promoted -> last_adaptation null, post null, pre==window(40)
PASS - missing adaptation_history.json tolerated
== eval_window.jsonl round-trip ==
PASS - jsonl 40 rows / re-instantiate -> size 40, metrics equal /
       split works post-restore / corrupt lines tolerated /
       window bound honored (60->30 deque + file) / dir state_path accepted /
       reset() clears deque + deletes file / 4-thread concurrent record -> 100 rows
ALL CHECKS PASSED
```

(Suppressed benign sklearn `UserWarning`s from `evaluate_predictions`
internals on single-class windows — no effect on outputs.)

## Outputs produced

- `LiveEvaluator` conforming to §9.4 on all branches: insufficient (<30) →
  `insufficient_data: true` + full zeroed contract skeleton; sufficient →
  full §8 contract; pre/post split via last `promoted:true` ts.
- `eval_window.jsonl` round-trips: append-per-batch, truncated to `window`
  lines, restored on boot, corruption-tolerant.

## Deviations from spec

1. **`state_path` interpretation** — §9.4 signature is ambiguous (file vs
   dir). Shipped: file path to `eval_window.jsonl` (matches §5.2's file table
   and the §9.2 `state_path` vs §9.3 `state_dir` naming distinction); a
   directory is *also* tolerated defensively (`<dir>/eval_window.jsonl`).
   `adaptation_history.json` is resolved as a sibling
   (`state_path.parent / "adaptation_history.json"`).
2. **Persisted row carries both `conf` and `confidence`** — task spec dict
   says `conf`, §5.2 file table says `confidence`; both keys written (same
   value) plus `ts_epoch` (float epoch) for a timezone-safe pre/post compare.
   Restore accepts either key.
3. **`version` defaults to `"v1"`** — §9.1 `batch_record` has no version
   field. Row uses `record.get("version") or record.get("model_version") or
   "v1"`. TASK-10 may add `"version"` to batch_records and it flows through.
4. **`window` block adds `capacity`** — extra key beyond §8 example;
   contract-tolerated and useful for UI progress display.
5. **No `roc_auc` key** — only scalar confidence is stored per row (no prob
   vectors); `evaluate_predictions` returns `roc_auc_macro=None` without
   `y_prob`. Spec allows omission.
6. **`insufficient_data` key only emitted when true** (verification requires
   it absent at ≥30 samples).

## Handoff notes for dependent tasks

- For TASK-10 (wire evaluation api): instantiate once at api boot —
  `_evaluator = LiveEvaluator(Path("ml/artifacts/state/eval_window.jsonl"))`;
  call `_evaluator.record(batch_records, latency_ms)` inside the guarded
  try/except in `predict()` (after `_adapter.observe/maybe_trigger`), and
  `_evaluator.reset()` from `/admin/reset`. Optionally add `"version"` to
  batch_records for per-version row tagging. `GET /evaluation` →
  `jsonify(_evaluator.get_metrics())`.
- For TASK-04 (adapter): the §5.4 rule is implemented by module-level
  `_resolve_pseudo_label(record) -> Optional[int]` — import it or mirror it
  exactly (LBL:: tag → rule_override → Normal@≥0.90 → else None). Priority:
  a malformed `LBL::` tag falls through to the next rule rather than
  excluding.
- For everyone: **latent bug in `metrics.py`** (not mine to fix, do not pass
  `y_prob`): line ~108 references `logger` which is never imported/defined in
  that file — a `NameError` inside the roc_auc `except` branch. Safe as long
  as `y_prob=None` (the evaluator never passes it).
- `evaluate_predictions` real keys confirmed: `accuracy`, `macro_precision`,
  `macro_recall`, `macro_f1`, `per_class_metrics{name:{precision,recall,
  f1_score,support}}` (**`f1_score` ≠ contract's `f1`** — remapped),
  `confusion_matrix_raw` (always 7×7 via `labels=`).
- `adaptation_history.json` shape (from `adaptive_engine.save_state()`): a
  JSON **list** of gate reports, `timestamp = datetime.now().isoformat()`
  (naive LOCAL time), `promoted: bool`. The evaluator's parser tolerates
  naive ISO, `Z`-suffixed ISO, and epochs.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `ml/src/evaluation/live_evaluator.py` shipped — `LiveEvaluator(state_path=…/eval_window.jsonl, window=500)`; `get_metrics()` returns exact §8 contract (+`insufficient_data` only when <30 labeled rows).
- CONTEXT fact: `eval_window.jsonl` rows = `{ts, ts_epoch, y_true, y_pred, conf, confidence, version}`; `version` defaults `"v1"` unless batch_record carries it.
- CONTEXT fact: §5.4 pseudo-label rule lives in module-level `_resolve_pseudo_label()` in live_evaluator.py — adapter should use/mirror it.
- CONTEXT deviation: `state_path` treated as the `eval_window.jsonl` FILE path (dir tolerated); `adaptation_history.json` read as its sibling.
- CONTEXT deviation: known latent bug — `metrics.py` uses undefined `logger` in roc_auc except-branch (harmless while y_prob=None).
- Open issue: none.
- TRACKER row status: `done` — "LiveEvaluator shipped + verified in-process: 45/45 checks (pseudo-labels, insufficient path, pre/post split, jsonl round-trip, thread-safety)."
