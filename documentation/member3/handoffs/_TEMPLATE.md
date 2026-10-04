# HANDOFF — TASK-NN — <short title>

> Copy this template to `handoffs/TASK-NN_<slug>.md` (same slug as your task
> file). Fill EVERY field — this file is the only thing dependent agents know
> about your work. Replace TASK-NN everywhere.

| | |
|---|---|
| **Task** | TASK-NN — <title> |
| **Status** | `done` / `partial` / `blocked` |
| **Wave** | A / B / C1 / C2 / D |
| **Date** | YYYY-MM-DD |
| **Depends on (handoffs read)** | TASK-XX, TASK-YY — or "none" |

---

## Files created

- `path/to/new_file.py` — one-line description

## Files modified

- `path/to/existing.py` — what changed, one line

## Interface surface shipped

*(Exact names/signatures other tasks will call — copy real code lines.
Dependent tasks build against THIS, not the plan.)*

```python
# e.g. class LiveDriftMonitor: process_batch(records) -> dict ...
```

## Verification run

*(Paste REAL commands + outputs. "It should work" is not verification.)*

```
$ <command>
→ <actual output>
```

## Outputs produced

*(Artifacts, endpoints verified, numbers observed — e.g., "buffer filled to
1,420; promotion v1→v2 in 38 s; PSI slot-1 spiked to 0.41".)*

## Deviations from spec

`none` — or: what changed vs the task spec/master plan and why.

## Handoff notes for dependent tasks

*(What the NEXT agents must know — gotchas, actual field names if they differ,
things that surprised you, unfinished edges.)*

- For TASK-XX: …

## Merge suggestions → CONTEXT.md / TRACKER.md

*(Parallel-wave agents: the orchestrator copies these into CONTEXT.md §C/D/E
and your TRACKER.md row. Sequential agents: still fill this as a summary —
then also update CONTEXT.md + TRACKER.md yourself.)*

- CONTEXT fact: …
- CONTEXT deviation: …
- Open issue: …
- TRACKER row status: `done` — "one-line outcome"
