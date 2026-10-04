# TASK-07 — Frontend `api.post()` Helper (`client/src/api.js`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T01–T07) |
| **Depends on** | none |
| **Input handoffs** | none |
| **Files you may touch** | `client/src/api.js` only |
| **Files you must NOT touch** | all `client/src/pages/*`, everything else |
| **Goal** | A `post(path, body)` helper with identical auth/base-URL handling to the existing `get` — TASK-15's FORCE button needs it |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `client/src/api.js` — how `get` handles the `/api` base (axios or fetch), JWT header injection, error returns (`res.data`? `null` on failure?)
3. `client/src/pages/LiveTraffic.jsx` (or wherever `api.get` is used) — usage convention

## Build

- Add `post(path, body)` hitting the same `/api`-proxied base with the JWT
  header — copy `get`'s auth handling verbatim.
- Preserve whatever convention `get` uses: if it returns `res.data`, post
  should resolve `{status, data}` or `res.data` — **document the exact return
  shape in your handoff** so TASK-15 can read status codes for 202/409/422.
  If `get` swallows HTTP error statuses, `post` must NOT — the FORCE button
  needs the real status code. Return enough to distinguish them.
- Keep exports consistent with the existing module shape.

## Do NOT

- No new npm packages.
- Don't refactor `get` or other exports.
- Don't touch any page components.

## Verification

```bash
cd client && npx eslint src/api.js    # or the project's lint setup
node -e "..." or a tiny vite-node check that post() issues a POST with the
# Authorization header to /api/... — a code-review + lint pass is acceptable
# if the dev server isn't running (note which you did)
```

## Finish protocol

- `handoffs/TASK-07_api-js-post.md` — **state the exact return shape of
  `post()`** (TASK-15 depends on it).
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] `api.post(path, body)` exists, JWT-authed, real status codes reachable
- [ ] Lint/build passes for the file
- [ ] Handoff states the exact return shape
