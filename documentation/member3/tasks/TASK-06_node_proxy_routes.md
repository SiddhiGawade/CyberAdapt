# TASK-06 — Node POST Proxy Routes (`server/routes/telemetry.js`)

| | |
|---|---|
| **Wave** | A — **parallel** (runs alongside T01–T07) |
| **Depends on** | none — build to the §8 endpoint contracts (Flask side ships later in TASK-09; proxies forward regardless) |
| **Input handoffs** | none |
| **Files you may touch** | `server/routes/telemetry.js` only |
| **Files you must NOT touch** | everything else |
| **Goal** | Two JWT-authed POST proxies: `/api/telemetry/adaptation/trigger` and `/api/telemetry/admin/reset` → Flask `:5001` |

---

## Read first

1. `documentation/member3/CONTEXT.md`
2. `00_MASTER_PLAN.md` — §5.6 (endpoint list), §5.7 (Node stays a dumb proxy), §8 (contracts)
3. `server/routes/telemetry.js` — the existing GET-proxy pattern
   (`AbortController`, 3–5 s timeout, auth middleware, error passthrough)

## Build

Mirror the existing GET-proxy pattern **exactly**, but `router.post(...)`:

- `POST /api/telemetry/adaptation/trigger` → `POST {ML_API_URL}/adaptation/trigger`
- `POST /api/telemetry/admin/reset` → `POST {ML_API_URL}/admin/reset`

- No request body needed; forward `Content-Type: application/json`.
- Same JWT `auth` middleware as the other `/api/telemetry/*` routes.
- Pass status codes through: `res.status(resp.status).json(data)` — the UI
  distinguishes 202/409/422/403.
- Same `AbortController` timeout + `ML_API_URL` env resolution as siblings.
- Match code style (async/await, error shape on timeout/conn-refused).

## Do NOT

- Don't add drift/adaptation logic to Node — pure proxy (§5.1/§5.7).
- Don't touch the ingest route or `classifyAndAnnotate`.
- Don't add new npm dependencies.

## Verification

```bash
node --check server/routes/telemetry.js     # syntax
# If a stack is running (shared-stack rule): login → JWT →
#   curl -X POST -H "Authorization: Bearer <jwt>" http://localhost:5000/api/telemetry/adaptation/trigger
#   → expect passthrough status (202/409/422 once Flask side exists;
#     a clean 502/timeout error shape is acceptable BEFORE TASK-09 — note which you saw)
```

## Finish protocol

- `handoffs/TASK-06_node-proxies.md` from template.
- **Parallel wave — do NOT edit `CONTEXT.md`/`TRACKER.md`.**

## Definition of done

- [ ] Both POST routes exist, JWT-protected, status-passthrough
- [ ] `node --check` clean; pattern matches existing proxies
- [ ] Handoff written
