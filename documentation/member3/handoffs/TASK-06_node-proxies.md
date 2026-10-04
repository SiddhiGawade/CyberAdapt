# HANDOFF — TASK-06 — Node POST Proxy Routes

| | |
|---|---|
| **Task** | TASK-06 — Node POST proxy routes (`server/routes/telemetry.js`) |
| **Status** | `done` |
| **Wave** | A — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- `documentation/member3/handoffs/TASK-06_node-proxies.md` — this handoff

## Files modified

- `server/routes/telemetry.js` — appended two JWT-authed POST proxies under a new
  `ML ACTION PROXIES` section (lines ~258–295), before `module.exports`.

## Interface surface shipped

```js
// POST /api/telemetry/adaptation/trigger  →  POST {ML_API_URL}/adaptation/trigger
router.post('/adaptation/trigger', auth, async (req, res, next) => { /* fetch POST, 5 s AbortController, res.status(resp.status).json(data) */ });

// POST /api/telemetry/admin/reset  →  POST {ML_API_URL}/admin/reset
router.post('/admin/reset', auth, async (req, res, next) => { /* same shape */ });
```

- No request body forwarded; `Content-Type: application/json` header sent.
- **Status passthrough is literal** (`res.status(resp.status)`), unlike the GET
  siblings' `resp.ok ? 200 : 503` collapse — required so the UI sees 202/409/422/403.
- Timeout = **5000 ms** (POST sibling `classifyAndAnnotate` uses 5 s; GETs use 3 s).
- Catch path returns `503 { "error": "<fetch err.message>" }` — same error shape
  as all sibling proxies.

## Verification run

```
$ node --check server/routes/telemetry.js
→ SYNTAX OK   (node v24.14.1)

# Live stack test — started mongod (:27017) + node server.js (:5000) myself;
# Flask :5001 intentionally DOWN (TASK-09 hasn't shipped its endpoints).

$ POST /api/auth/login {admin@acme-test.local / Test@1234}
→ JWT issued

$ curl -X POST -H "Authorization: Bearer <jwt>" http://localhost:5000/api/telemetry/adaptation/trigger
→ HTTP 503   {"error":"fetch failed"}

$ curl -X POST -H "Authorization: Bearer <jwt>" http://localhost:5000/api/telemetry/admin/reset
→ HTTP 503   {"error":"fetch failed"}

$ curl -X POST http://localhost:5000/api/telemetry/adaptation/trigger   (no JWT)
→ HTTP 401   {"error":"Missing or malformed Authorization header"}
```

**Pre-TASK-09 observation:** with Flask unreachable, both routes return a clean
`503 {"error":"fetch failed"}` (Node fetch wraps ECONNREFUSED as "fetch failed").
That is the expected pre-TASK-09 error shape — not a 502. (If Flask were up but
the routes missing, `resp.json()` on Flask's HTML 404 would throw and land in the
same 503 catch.)

## Outputs produced

- Two live-verified endpoints: `/api/telemetry/adaptation/trigger`,
  `/api/telemetry/admin/reset` — JWT-enforced, proxying to `ML_API_URL`.

## Deviations from spec

`none` — routes mirror the sibling proxy pattern; only the passthrough uses
`resp.status` verbatim (per task spec) instead of `resp.ok ? 200 : 503`.

## Handoff notes for dependent tasks

- For TASK-07 (client `api.post()`): these endpoints are already mounted and
  JWT-protected; call them with `api.post('/telemetry/adaptation/trigger')` —
  no body needed. Surface `resp.status` to the UI; do not special-case non-200.
- For TASK-09 (Flask endpoints): contract reminders — `POST /adaptation/trigger`
  → 202 / 409 `{"status":"busy"}` / 422; `POST /admin/reset` → 200 / 403 when
  `DEMO_MODE` unset. Node passes the status through untouched.
- Gotcha: when Flask is down the error is `{"error":"fetch failed"}` (undici
  wraps the underlying ECONNREFUSED), HTTP 503.
- I left **mongod (:27017) and the Node API (:5000) running** — I started them
  for verification. Orchestrator/other agents may reuse (shared-stack rule).
- Seeded dev account exists: `admin@acme-test.local` / `Test@1234`, sensor key
  `ca_live_824ffa62c2ab8eb19ff87c9363b5178f4cb415d145b71cd1287645348cddd840`.

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact (§A, "Sensor key in use"): `ca_live_824ffa62c2ab8eb19ff87c9363b5178f4cb415d145b71cd1287645348cddd840` (from `seed-dev.js`, 2026-10-04).
- CONTEXT fact (§C): Node POST proxies return `503 {"error":"fetch failed"}` when Flask :5001 is down — undici wraps ECONNREFUSED; UI should treat 503 as "ML offline".
- CONTEXT fact (§C): mongod + Node :5000 were started by TASK-06 and left running; Flask :5001 was NOT running during this verification.
- CONTEXT deviation: none.
- Open issue: none.
- TRACKER row status: `done` — "Both POST proxies shipped + live-verified (JWT enforced, 503 clean error pre-TASK-09)."
