# CyberAdapt Demo Command Manual

Windows PowerShell walkthrough for showing normal traffic, malicious traffic, concept drift, automatic model adaptation, and evaluation.

> Run all `python sensor/...` and `python ml/scripts/...` commands in **Terminal 5 — Driver**. Keep the four service terminals running.
>
> This demo sends generated telemetry into the local project. It does not generate real network attacks.

## 1. Open five PowerShell terminals

Repository root:

```powershell
E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project
```

Before starting, check which services are already running:

```powershell
netstat -ano | findstr "LISTENING" | findstr ":27017 :5000 :5001 :3000"
```

If a port is already listening, reuse that service. Do not start a duplicate or stop a service you did not start.

### Terminal 1 — MongoDB (:27017)

Run once per session and leave this terminal open:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\mongodb-data" | Out-Null
& "C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe" `
    --dbpath "$env:USERPROFILE\mongodb-data" --bind_ip localhost --port 27017
```

### Terminal 2 — Node API (:5000)

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project\server"
npm run dev
```

Leave it running. It should report that the CyberAdapt API is listening on port 5000. The server requires `server/.env` with `ML_API_URL=http://localhost:5001`.

### Terminal 3 — Flask ML API (:5001)

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project"
.venv\Scripts\Activate.ps1
$env:MODEL_PATH="ml/artifacts/models/champion_model.joblib"
$env:PREPROCESSOR_PATH="ml/artifacts/models/preprocessor.joblib"
$env:DEMO_MODE="1"
$env:PORT="5001"
python -m ml.api
```

Leave it running. `DEMO_MODE=1` is required for the demo reset command.

### Terminal 4 — Dashboard (:3000)

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project\client"
npm run dev
```

Open `http://localhost:3000` in the browser and sign in with the local test account. Open these tabs:

- Live Traffic
- Concept Drift
- Model Adaptation
- Evaluation

Use `localhost`, not `127.0.0.1`, for the dashboard.

### Terminal 5 — Driver

All generators and check scripts run from the repository root in this terminal:

```powershell
cd "E:\VIT 7th Semester 3rd Year BTech\SUBJECTS\AML\mini-project"
.venv\Scripts\Activate.ps1
$env:SENSOR_KEY="<paste your current ca_live sensor key here>"
```

Replace the placeholder with your valid sensor key. This environment variable only applies to this PowerShell window; set it again if you open a new driver terminal. Do not put the real key in this manual or in screenshots.

## 2. First-time setup only

Skip this section if dependencies and configuration are already set up.

- In `server/`, run `npm install` once.
- In `client/`, run `npm install` once.
- From the repository root, create/activate `.venv` if needed and run `pip install -r ml/requirements.txt`.
- Confirm `server/.env` points to MongoDB and the ML API. In particular, `ML_API_URL` should be `http://localhost:5001`.

If the database has no valid development sensor key, run this from Terminal 5 at the repository root:

```powershell
node server/scripts/seed-dev.js
```

Use the newly generated key in `$env:SENSOR_KEY`. If the adaptation seed check returns 401/403 after a key change, its configured `SENSOR_KEY` in `ml/scripts/check_adaptation_api.py` may also need to be updated to match. Do not paste the key into this manual.

## 3. Pre-flight and clean start

Run these commands in Terminal 5 after all services are running:

```powershell
Invoke-RestMethod http://127.0.0.1:5001/health
```

Confirm `status` is `operational` and `model_ready` is `True`.

Reset the demo state before a fresh presentation:

```powershell
python ml/scripts/check_adaptation_api.py reset
python ml/scripts/check_adaptation_api.py status
python ml/scripts/check_drift_api.py once
```

After reset, expect version `v1`, an empty buffer, zero drift samples, and `status=warming_up`. Reset clears the drift/adaptation/evaluation demo state, so use it before the demo if you want a clean run—not afterward if you want to preserve the results.

## 4. Demo sequence

### Act 1 — Normal traffic and baseline

In Terminal 5, run:

```powershell
python sensor/normal_traffic.py --lbl-tag --interval 2 --batch-size 8 --duration 140
```

Expect about 560 normal flows and successful `HTTP 202` responses.

While it runs, show **Live Traffic**. Normal rows should appear. After the generator finishes, check the monitor:

```powershell
python ml/scripts/check_drift_api.py once
```

Proceed only when the monitor reports `status=active` and has seen at least 500 samples. On **Concept Drift**, the expected baseline is `active` and `stable`, with PSI near baseline. No drift during normal traffic is expected.

On **Model Adaptation**, show the buffer filling with independently verified or simulator-tagged labels.

### Act 2 — DoS seed, drift detection, and automatic adaptation

Only after the normal baseline is active, run this in Terminal 5:

```powershell
python ml/scripts/check_adaptation_api.py seed dos 90 30
```

This sends 90 tagged DoS flows in three batches of 30. Keep the command output visible while checking the dashboard. The drift event should trigger the automatic retraining process; the candidate is then checked against the promotion gates.

Check:

- **Concept Drift:** drift banner/event history and changed PSI values.
- **Model Adaptation:** champion version and retraining history. A passing candidate is promoted; a failing candidate is rejected and the existing champion stays active.
- **Live Traffic:** DoS rows among the normal rows.

The rehearsed run promoted `v1` to `v2`. Exact version numbers can differ if you did not reset to `v1` before starting. The automatic adaptation is the drift-handling step; you do not need to press Force Adaptation for it to happen.

### Optional — Manual trigger and busy response

This is not required to show automatic drift handling. To demonstrate the manual retrain path, use the **Force Adaptation Step** button on the Model Adaptation page, or run:

```powershell
python ml/scripts/check_adaptation_api.py proxytriggerx2
```

The second trigger can return `409 busy` if a retrain is already in progress; that demonstrates the busy protection.

### Act 3 — Sustained mixed attack campaign

Wait about 60 seconds after the last completed retrain to allow its cooldown to expire. Then run this in Terminal 5:

```powershell
python sensor/attack_campaign.py --scenario mixed --rate 12 --batch-size 6
```

The campaign runs through warmup, DoS, brute force, SQL injection, exfiltration, and cooldown phases. It sends about 2,880 flows and takes about four minutes.

Show the dashboard during the campaign:

- **Live Traffic:** attack labels change with the campaign phases.
- **Concept Drift:** monitor status, event history, and PSI changes.
- **Model Adaptation:** any additional promotion, rejection, or cooldown skip.

A skipped event during cooldown is expected protection against retraining too frequently; it is not the same as an API request failing.

### Act 4 — Recovery traffic and evaluation

Run tagged normal traffic so the evaluation window receives labeled examples:

```powershell
python sensor/normal_traffic.py --lbl-tag --interval 2 --batch-size 8 --duration 25
```

Then collect the final API snapshots:

```powershell
python ml/scripts/check_evaluation_api.py snap
python ml/scripts/check_adaptation_api.py status
python ml/scripts/check_drift_api.py once
```

Show **Evaluation** for its metrics and confusion matrix. The measured values depend on the traffic and current rolling window. Check the pre/post-adaptation comparison soon after a promotion because newer samples can move older samples out of view.

## 5. Quick command checklist

Run these in **Terminal 5**, in this order:

```powershell
# Check Flask ML API
Invoke-RestMethod http://127.0.0.1:5001/health

# Reset to a clean v1 demo state
python ml/scripts/check_adaptation_api.py reset

# Act 1: normal baseline
python sensor/normal_traffic.py --lbl-tag --interval 2 --batch-size 8 --duration 140

# Confirm the monitor is active before injecting attacks
python ml/scripts/check_drift_api.py once

# Act 2: tagged DoS seed that triggers drift/adaptation
python ml/scripts/check_adaptation_api.py seed dos 90 30

# Optional: allow the retraining cooldown before the longer campaign
Start-Sleep -Seconds 60

# Act 3: sustained mixed attack campaign
python sensor/attack_campaign.py --scenario mixed --rate 12 --batch-size 6

# Act 4: tagged normal recovery traffic
python sensor/normal_traffic.py --lbl-tag --interval 2 --batch-size 8 --duration 25

# Capture final results
python ml/scripts/check_evaluation_api.py snap
python ml/scripts/check_adaptation_api.py status
```

**Order matters:** baseline traffic → `seed dos` → optional cooldown → `attack_campaign` → tagged recovery traffic. Do not start the campaign before the DoS seed; its warmup can trigger drift before the buffer has enough attack labels for adaptation.

## 6. Troubleshooting

| Symptom | What to do |
|---|---|
| `--key or SENSOR_KEY env var is required` | Set `$env:SENSOR_KEY` in Terminal 5, then rerun the generator. |
| Generator returns 401/403 | Check that the sensor key is current. If it was regenerated, update Terminal 5 and the adaptation check script's configured key if required. |
| Drift check still says `warming_up` | Continue normal traffic until the monitor has at least 500 samples. |
| Drift check says `n=0` after the baseline | Check that Terminal 3 is still running and healthy; accepted ingest requests alone do not confirm ML processing. |
| Event says `skipped — insufficient buffer` | The attack seed may have been skipped or run too late. Reset and repeat in the documented order. |
| Event says cooldown is active | Wait about 60 seconds after the last completed retrain before expecting another automatic retrain. |
| Dashboard does not open at `127.0.0.1:3000` | Use `http://localhost:3000`. |

## 7. One-line demo explanation

“Normal traffic establishes the baseline; the simulated attack shifts the feature distribution; the drift monitor detects that change; then the system retrains and promotes a candidate only if it passes the quality gates.”
