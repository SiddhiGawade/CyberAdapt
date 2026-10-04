# HANDOFF — TASK-07 — Frontend `api.post()` Helper

> Copy this template to `handoffs/TASK-NN_<slug>.md` (same slug as your task
> file). Fill EVERY field — this file is the only thing dependent agents know
> about your work. Replace TASK-NN everywhere.

| | |
|---|---|
| **Task** | TASK-07 — Frontend `api.post()` helper (`client/src/api.js`) |
| **Status** | `done` |
| **Wave** | A — parallel |
| **Date** | 2026-10-04 |
| **Depends on (handoffs read)** | none |

---

## Files created

- *(none — verification harness was a temp file, deleted after use)*

## Files modified

- `client/src/api.js` — kept existing `post` byte-identical; added an additive
  `api.postWithStatus(url, body)` export (api.js:40-55) so callers can read the
  real numeric status (202/409/422) without try/catch.

## Interface surface shipped

*(Exact names/signatures other tasks will call — copy real code lines.
Dependent tasks build against THIS, not the plan.)*

```js
// client/src/api.js — module exports `api` (named + default). JWT is read
// from localStorage key 'ca_token' → 'Authorization: Bearer <token>';
// base is '/api' (Vite dev proxy). Content-Type: application/json always.

api.get(url)            // resolves parsed JSON body on 2xx;
                        // throws Error on !res.ok → err.status, err.data

api.post(url, body?)    // POST; body optional (api.post('/x') sends no body —
                        // JSON.stringify(undefined) === undefined).
                        // resolves parsed JSON body on ANY 2xx (incl. 202) —
                        // numeric status NOT exposed on success.
                        // throws Error on !res.ok → err.status (e.g. 409/422),
                        // err.data = parsed error body.

api.postWithStatus(url, body?)   // POST, identical auth/base handling.
                        // NEVER throws on HTTP error statuses — resolves:
                        //   { status: <number>, ok: <bool>, data: <parsed body|{}> }
                        // Only transport-level failures (no response at all)
                        // reject, with a plain fetch TypeError (no .status).
```

## Verification run

*(Paste REAL commands + outputs. "It should work" is not verification.)*

Code-level verification (no eslint/lint config exists in `client/package.json`;
dev server not required). Temp `.mjs` harness stubbed `localStorage` +
`fetch`, imported the real `src/api.js`, asserted behavior — since deleted.

```
$ node .tmp-task07-verify.mjs
PASS: post() resolves parsed body on 202
PASS: post() hits the /api-proxied base
PASS: post() issues method POST
PASS: post() injects JWT Authorization header
PASS: post() sends Content-Type: application/json
PASS: post(url) with no body sends no request body
PASS: post() 409 → thrown err.status=409 + err.data
PASS: post() 422 → thrown err.status=422 + err.data
PASS: postWithStatus → { status:202, ok:true, data } without throwing
PASS: postWithStatus → { status:409, ok:false, data } without throwing
PASS: postWithStatus → { status:422, ok:false, data } without throwing
PASS: postWithStatus injects JWT Authorization header
PASS: postWithStatus hits the /api-proxied base
— ALL CHECKS PASSED —

$ npx vite build            (client/) — build-level check
✓ 2183 modules transformed. ✓ built in 14.60s   (pre-existing >500 kB chunk warning only)
```

## Outputs produced

- `api.postWithStatus` verified to surface 202/409/422 as a plain resolved
  value; `api.post` verified to surface 409/422 via `err.status`/`err.data`.
- `vite build` compiles the file cleanly (2183 modules, no errors).

## Deviations from spec

`api.post(url, body)` already existed in `api.js` (auth callers use it) and
already copies `get`'s handling verbatim — errors are NOT swallowed (they
throw with `.status`/`.data`). Returning `{status, data}` from `post` would
have broken 4 existing call sites (`AuthContext.jsx`, `SensorSetup.jsx`) that
destructure the resolved body directly, and pages are off-limits. So: `post`
left byte-identical (resolves `data` on 2xx), and the spec's alternative
`{status, data}` shape was shipped additively as `api.postWithStatus` —
auth/header/base logic copied verbatim from `request()`.

## Handoff notes for dependent tasks

- **For TASK-15 (FORCE ADAPTATION button)** — two supported patterns:
  ```js
  // Option A — recommended: numeric status directly, no try/catch
  const { status, data } = await api.postWithStatus('/telemetry/adaptation/trigger');
  if (status === 202) /* "Adaptation queued"; data.status === 'accepted' */;
  else if (status === 409) /* "retrain already running"; data.status === 'busy' */;
  else if (status === 422) /* insufficiency reason lives in data */;

  // Option B — plain post(): resolved ⇒ 202 (the endpoint's ONLY success
  // code per §8); non-2xx throws Error with err.status + err.data
  try { await api.post('/telemetry/adaptation/trigger'); /* → 202 queued */ }
  catch (e) { /* e.status 409|422; e.data = response body */ }
  ```
  Trigger takes **no body** — call with just the URL; `post`/`postWithStatus`
  then send no request body (verified).
- For anyone calling `POST /api/telemetry/admin/reset` (TASK-16/rehearsal):
  same helpers; success is **200** there (not 202), 403 if `DEMO_MODE` unset —
  with `api.post` that's resolve-vs-`e.status===403`; `postWithStatus` returns
  `{status:200|403}` directly.
- `err.data` / `data` is `{}` when the body isn't JSON (never `undefined`).

## Merge suggestions → CONTEXT.md / TRACKER.md

- CONTEXT fact: `client/src/api.js` — `api.post(url,body?)` resolves parsed
  body on 2xx, throws `Error{status,data}` on !ok; new `api.postWithStatus`
  resolves `{status, ok, data}` for every HTTP status (for 202/409/422 reads).
- CONTEXT fact: `api.post(url)` may be called with no body — nothing is sent.
- CONTEXT deviation: api.post already existed pre-TASK-07; `{status,data}`
  shape shipped as additive `postWithStatus` instead of changing `post`
  (existing auth callers would break).
- Open issue: none.
- TRACKER row status: `done` — "post() kept verbatim (err.status on 409/422);
  postWithStatus added for direct 202/409/422 reads; build + stubbed-fetch
  harness all green"
