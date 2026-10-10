# CyberAdapt Local Pipelines

This guide has the commands for the three local test paths. Run commands from
the repository root in PowerShell, with Docker Desktop running.

## 1. Real local traffic and packet capture

This starts the local Juice Shop target, captures its network packets with the
Docker sensor, sends extracted features through the backend to the ML API, and
runs a time-limited OWASP ZAP scan against that local target.

```powershell
.\Start-CyberAdapt-DockerLab.ps1
```

Open the dashboard at <http://127.0.0.1:3000>. The local target is at
<http://127.0.0.1:5055>. Press **Ctrl+C** in the launcher window to stop the
lab. The launcher checks that the trained model artifacts exist before
starting.

This is real local packet capture and scanner traffic, but not a true
distributed DDoS. ZAP's web security findings and the model's flow predictions
are separate results. Neither drift detection nor model retraining is
guaranteed by this run.

## 2. Direct feature injection

This bypasses packet capture and sends ten synthetic 52-feature examples
through the backend and ML inference path.

```powershell
.\Run-CyberAdapt-FeatureDemo.ps1
```

The script starts MongoDB, the ML API, backend, and dashboard; runs the
development seed; asks you to paste the newly printed `ca_live_...` key; then
sends the examples. The key is entered interactively rather than saved in the
script. Open the dashboard at <http://localhost:3000>.

To see backend and model logs from another PowerShell window:

```powershell
docker compose logs --tail 50 backend ml-api
```

## 3. Feature-distribution drift test

This sends a 500-vector baseline followed by a 500-vector shifted profile
through the backend and ML API. It tests the live feature-drift monitor without
generating network packets.

Stop packet capture first so unrelated traffic does not affect the baseline,
then run the seed and test:

```powershell
docker compose up -d mongo ml-api backend
docker compose stop sensor
docker compose --profile tools run --rm seed
python sensor/test_drift_injection.py --reset
```

Paste the newly printed `ca_live_...` key when prompted. The test waits for
both batches to reach inference and prints the drift state, PSI feature values,
and latest event. It returns a failure if the shifted vectors do not result in
a drift event.

`--reset` clears the ML demo's drift, adaptation, and evaluation state and
reloads the original model; it does not delete stored telemetry. The injected
vectors have no labels. This tests input-feature distribution drift, not
verified attack detection, and does not request supervised model retraining.
Start the packet sensor again when the test is over if needed:

```powershell
docker compose start sensor
```

## Notes

- The first pipeline requires the model files
  `ml\artifacts\models\champion_model.joblib` and
  `ml\artifacts\models\preprocessor.joblib`.
- The feature-injection and drift-test scripts require Python with the
  project's `requests` package installed.
- A backend HTTP 202 means flows were accepted; the scripts also wait for
  inference where needed. If a test fails, inspect the service logs:

  ```powershell
  docker compose logs --tail 100 backend ml-api sensor
  ```

- These local tests are for systems you own or are authorized to test. They
  are not evidence of production detection accuracy or real-world DDoS
  protection.
