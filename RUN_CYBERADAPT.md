# Run CyberAdapt Locally (Windows PowerShell)

This guide starts CyberAdapt, an intentionally vulnerable local OWASP Juice
Shop target, an OWASP ZAP scanner, and the packet sensor. The sensor captures
the scan traffic and sends unlabeled packet-flow features through the normal
ingest and model-inference path. The target is published on localhost only.

## Docker launch (recommended on Windows)

Docker runs the sensor and test target in a shared Linux network namespace, so
the sensor can capture the target's packets without installing Npcap on
Windows. Docker Desktop must be installed and running, and the trained model
artifacts listed below must exist. The first run builds the local images and
may take several minutes.

From the repository root, run:

```powershell
.\Start-CyberAdapt-DockerLab.ps1
```

The script starts MongoDB, the backend, ML API, dashboard, Juice Shop, and
packet sensor; creates a development sensor key; runs a time-bounded OWASP ZAP
active scan against Juice Shop; and checks that newly captured flows reach ML
inference. Open the dashboard at `http://127.0.0.1:3000`; Juice Shop is at
`http://127.0.0.1:5055`. Press **Ctrl+C** to stop the containers. MongoDB and
ML state are kept in Docker volumes.

The scan is restricted to this local, intentionally vulnerable test target.
Its web-vulnerability findings are not the same as CyberAdapt's packet-model
predictions. Model predictions are generated from captured packet features;
the scanner does not send labels to the model. Scan reports are written to
`docker-reports\zap-report.html` and `docker-reports\zap-report.json`.

## Test drift with synthetic features

To test drift independently of packet capture, keep the Docker services running
and open a second PowerShell window in the repository root. Pause the packet
sensor so it cannot add traffic to the test baseline, then generate a sensor
key and run the dedicated drift test:

```powershell
docker compose stop sensor
docker compose --profile tools run --rm seed
python sensor/test_drift_injection.py --reset
```

Paste the newly printed `ca_live_...` key when prompted. The script sends 500
unlabeled baseline feature vectors followed by 500 synthetic short-duration,
high-forward-byte vectors through the normal backend ingest and ML inference
path. It waits for each batch to reach inference and reports the live PSI
values and drift event. `--reset` clears the ML demo's drift, adaptation, and
evaluation state so the test starts with a clean baseline; it does not delete
stored telemetry. The vectors are synthetic and do not represent real packets
or prove attack classification. No trusted labels are supplied, so this test
does not request model retraining.

Restart live packet capture afterwards if needed:

```powershell
docker compose start sensor
```

Optional: adjust the active scan's hard timeout (1–5 minutes):

```powershell
.\Start-CyberAdapt-DockerLab.ps1 -ScanTimeoutMinutes 5
```

The scanner applies active tests after spidering; a timeout can stop it before
the HTML/JSON report is complete. Captured traffic already sent to CyberAdapt
is retained, and the launcher reports whether ML inference processed it.

## Run the bounded local load test

The Juice Shop/ZAP security scan and this load test are separate. Keep the
Docker lab running, open a second PowerShell window in the repository root,
and run:

```powershell
docker compose run --build --rm --no-deps load-test --requests 200 --concurrency 4 --rate 5 --duration-seconds 60
```

This sends at most 200 plain homepage requests to local Juice Shop, up to four
at once, with a maximum rate of five per second and a one-minute limit. The
script hard-restricts the target to the local lab, sends no exploit payloads,
and does not send labels to the model. It prints the inference sample count,
model-derived attack ratio, and drift state before and after the test. This is
a controlled DoS-like load test from one machine—not a DDoS attack—and it
cannot guarantee an attack prediction.

You can lower the request count or rate, but the script rejects values above
its safety limits (5,000 requested requests, five concurrent requests, ten requests per
second, and 60 seconds). Previous ZAP scans and reports are separate and are
not overwritten by this test.

To inspect the stack manually:

```powershell
docker compose ps
docker compose logs -f sensor
docker compose logs -f backend ml-api
```

## Native safe-fixture launch (Npcap required)

The older native launcher starts the canned-response test fixture; it does
not run the OWASP Juice Shop/ZAP security scan. Use the Docker launch above
for the intentionally vulnerable target and active scan. The native fixture
captures Windows loopback packets directly and requires Npcap with loopback
capture enabled.

Before running it the first time:

- Install Npcap with its loopback capture option enabled.
- Install Node.js 18+, MongoDB, and the project's Node/Python dependencies.
- Ensure the trained model artifacts listed below exist.
- Accept the launcher's UAC prompt so Npcap can capture packets.

Use one command from the repository root:

```powershell
Set-Location "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
.\Start-CyberAdapt-Lab.ps1
```

Optional: change the number of local requests:

```powershell
.\Start-CyberAdapt-Lab.ps1 -NormalCount 50 -AttackCount 10
```

The launcher chooses the Npcap loopback interface automatically when it can.
If your adapter has a different Scapy interface name, pass it explicitly:

```powershell
.\Start-CyberAdapt-Lab.ps1 -CaptureInterface "\Device\NPF_{YOUR-ADAPTER-GUID}"
```

The launcher stops only the processes and MongoDB service it started. An
already-running MongoDB service is left running. It refuses to start if the
application ports it needs are already occupied and fails early if Npcap
loopback capture is not available. No tunnel or external target is used.

## Manual multi-terminal alternative

The sections below describe the native setup manually for troubleshooting.
Install Npcap with loopback capture enabled before starting the packet sensor.

Set this as the project root in the commands below:

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
```

If your repository is in a different folder, replace that path with its actual
location.

## One-time setup

### 1. Check required tools and model files

The project requires Node.js 18 or later, Python 3.10 or later, and MongoDB.
The Flask API expects the trained model artifacts in:

```text
ml\artifacts\models\champion_model.joblib
ml\artifacts\models\preprocessor.joblib
```

Check they exist:

```powershell
Test-Path "$Project\ml\artifacts\models\champion_model.joblib"
Test-Path "$Project\ml\artifacts\models\preprocessor.joblib"
```

Both commands should return `True`.

### 2. Install backend dependencies and configure its environment

```powershell
Set-Location "$Project\server"
npm install
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `server\.env` and make sure it has local values equivalent to:

```env
PORT=5000
MONGO_URI=mongodb://127.0.0.1:27017/cyberadapt
JWT_SECRET=replace_with_a_long_random_local_secret
JWT_EXPIRES_IN=24h
ML_API_URL=http://localhost:5001
```

Use the same MongoDB URI for the seed script and backend. Do not commit `.env`
or share the sensor key.

### 3. Set up the Python ML environment

Run once from the repository root:

```powershell
Set-Location "$Project"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r ml\requirements.txt
python -m pip install scapy requests
```

For live Windows packet capture, also install Npcap with its loopback capture
option enabled. Scapy alone does not install the Windows packet-capture driver.

If PowerShell blocks virtual-environment activation, run this in that terminal
and retry activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 4. Install frontend dependencies

```powershell
Set-Location "$Project\client"
npm install
```

## Start the full stack

### Terminal 1 — MongoDB

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
New-Item -ItemType Directory -Force "$env:USERPROFILE\mongodb-data"
& "C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe" `
  --dbpath "$env:USERPROFILE\mongodb-data" --bind_ip 127.0.0.1 --port 27017
```

Leave it open. MongoDB should report that it is listening on port `27017`.
If `mongod.exe` is not found, install MongoDB or configure an Atlas URI in
`server\.env` instead.

### Terminal 2 — Seed the development account and start the backend

First, from the repository root, create the development account and sensor key:

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
Set-Location "$Project\server"
node scripts/seed-dev.js
```

Copy the newly printed sensor key privately. The seed script generates a new
key every time it runs; use the latest key for the test target. Then start the
backend in this terminal:

```powershell
npm run dev
```

Leave it open. The backend listens on port `5000`.

### Terminal 3 — Flask ML API

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
Set-Location "$Project"
.\.venv\Scripts\Activate.ps1
$env:MODEL_PATH = "ml/artifacts/models/champion_model.joblib"
$env:PREPROCESSOR_PATH = "ml/artifacts/models/preprocessor.joblib"
$env:PORT = "5001"
python -m ml.api
```

Leave it open. Check in another terminal or browser:

```powershell
Invoke-RestMethod http://127.0.0.1:5001/health
```

The response should show `"status": "operational"` and `"model_ready": true`.

### Terminal 4 — React dashboard

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
Set-Location "$Project\client"
npm run dev
```

Open the local URL printed by Vite, usually `http://localhost:3000`, and sign
in with the development credentials printed by the seed script:

```text
admin@acme-test.local
Test@1234
```

The dashboard's Live Traffic, Concept Drift, Adaptation, and Evaluation pages
show the test results.

### Terminal 5 — Local HTTP target

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
Set-Location "$Project"
node server/scripts/cyberadapt-test-target.js
```

Leave it open. Expected startup output includes:

```text
[test target] Listening only on http://127.0.0.1:5055
```

If port `5055` is already in use, do not start a duplicate. Check whether the
existing process is the earlier version of this test target. Stop it with
Ctrl+C in its original terminal and restart the updated script; the earlier
version generated application-layer telemetry directly and is not the packet
capture target described here.

```powershell
Invoke-RestMethod http://127.0.0.1:5055/health
```

Inspect which process owns the port before stopping anything:

```powershell
$connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 5055 -State Listen
$connection | Select-Object LocalAddress, LocalPort, OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" |
  Select-Object ProcessId, Name, CommandLine
```

Stop a process only after confirming that it is an old CyberAdapt test target.

### Terminal 6 — Capture loopback packets and send features

Install Npcap with its loopback adapter if it is not already installed. Run
this terminal as Administrator and use the Scapy interface name for the
Npcap Loopback Adapter. The usual name is `\Device\NPF_Loopback`; if that
does not work, list the available interfaces with:

```powershell
Set-Location "$Project"
.\.venv\Scripts\python.exe -c "from scapy.all import get_if_list; print('\n'.join(get_if_list()))"
```

Set the sensor key, local ingest endpoint, loopback interface, and a narrow
capture filter so this test only captures packets for the local target:

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
Set-Location "$Project"
.\.venv\Scripts\Activate.ps1
$env:SENSOR_KEY = "PASTE_THE_LATEST_SENSOR_KEY_HERE"
$env:INGEST_URL = "http://127.0.0.1:5000/api/telemetry/ingest"
$env:INTERFACE = "\Device\NPF_Loopback"
$env:CAPTURE_FILTER = "ip and host 127.0.0.1 and port 5055"
python sensor/sensor.py
```

The sensor creates packet-flow-v1 vectors from packets it captures. It sends
no expected attack label; the model predicts from the captured flow features.

### Terminal 7 — Send the local traffic scenarios

Check health first:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://127.0.0.1:5001/health
Invoke-RestMethod http://127.0.0.1:5055/health
```

Then send the small test:

```powershell
$Project = "C:\Users\arav sunil mahind\Downloads\ARAV MAHIND\Projects\CyberAdapt 2.0\CyberAdapt"
Set-Location "$Project"
node server/scripts/cyberadapt-test-driver.js
```

The driver sends 10 baseline requests and 5 requests for each of three
attack-signal scenarios, with a 250 ms delay between requests. They are real
HTTP packets on loopback, but the server returns canned responses: this is a
safe local traffic exercise, not an exploit or an actual denial-of-service
attack. The packet sensor—not the target—converts the observed packets into
52-feature flows and sends them to CyberAdapt. Confirm batch delivery in the
sensor terminal and check Live Traffic for model predictions.

## Optional longer unlabeled traffic run

Run this only after the smoke test succeeds:

```powershell
node server/scripts/cyberadapt-test-driver.js --normal-count 500 --attack-count 50
```

This sends 500 baseline requests, then 50 requests for each response scenario.
The local target still binds only to loopback. The sensor captures their real
packets and sends unlabeled features to the model. This can exercise inference
and feature-distribution drift monitoring, but cannot establish classification
accuracy or provide trusted samples for supervised retraining. A drift alert
means the observed prediction/feature distribution changed; it does not prove
an attack or confirm concept drift without independent labels.

Automatic supervised retraining requires separately verified labels from a
trusted source. Never use the model's own predictions as ground-truth labels.

## What the local scenarios mean

| Test route | Response | Purpose |
|---|---:|---|
| `/test/normal` | 200 | Baseline-like HTTP sample |
| `/test/dos-signal` | 504 | Safe response-status signal |
| `/test/auth-denied` | 401 | Submits fake, invalid credentials to a test-only endpoint; no real accounts |
| `/test/server-error` | 500 | Canned server-error signal; no exploit is sent |

These are canned-response scenarios, not real exploits. In this runbook the
packet sensor captures their actual network packets, but it does not capture
the scenario name or any ground-truth labels. The server binds only to
loopback; do not expose it with ngrok.

## Troubleshooting

### MongoDB says connection refused

MongoDB is not listening. Start Terminal 1 and make sure `server\.env` uses
`mongodb://127.0.0.1:27017/cyberadapt`.

### Backend seed says `ECONNREFUSED`

Start MongoDB first. Run `node scripts/seed-dev.js` from `server\`, and check
that the seed script and backend load the same `server\.env`.

### Ingest returns HTTP 403: invalid or revoked sensor key

The key set in Terminal 5 is invalid or stale. Stop the test target with
Ctrl+C, run `node scripts/seed-dev.js` once from `server\`, then restart the
target with the newly printed key. Do not repeatedly seed unless you need a
new key.

### Test driver flush returns HTTP 502

Read the delivery error printed in Terminal 5:

- `ECONNREFUSED`: backend is not running at port `5000`.
- `Invalid or revoked sensor key`: use the latest sensor key.
- ML is unavailable: ingestion can still be accepted, but predictions require
  the Flask service on port `5001`.

### Port 5055 is already in use

The test target may already be running. Check
`Invoke-RestMethod http://127.0.0.1:5055/health`; if it returns `ready`, do not
launch a second target.

### Frontend reports a Tailwind/PostCSS plugin error

The client build has previously encountered a Tailwind/PostCSS configuration
mismatch. Run `npm install` from `client\` and try `npm run dev` again. If the
error remains, keep the APIs and test target running and use the exact error
message to troubleshoot the client separately.

## Stop the project

Press **Ctrl+C** in each terminal you started. Stop the local test target,
dashboard, ML API, backend, and MongoDB when finished. Do not stop processes
you did not start.
