param(
  [ValidateRange(1, 5)]
  [int]$ScanTimeoutMinutes = 5
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Docker = Get-Command docker.exe -ErrorAction SilentlyContinue
$PreviousSensorKey = [Environment]::GetEnvironmentVariable('SENSOR_KEY', 'Process')
$StackStarted = $false

function Test-LabReady {
  param([string]$Url, [string]$Description, [int]$TimeoutSeconds = 180)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
      return $response
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "$Description did not become ready at $Url. Check `docker compose logs`."
}

try {
  if (-not $Docker) { throw 'Docker CLI was not found. Install and start Docker Desktop first.' }
  if (Get-Command docker.exe -ErrorAction SilentlyContinue) {
    $existingContainers = & $Docker.Source compose ps -q 2>$null
    if ($LASTEXITCODE -eq 0 -and $existingContainers) {
      throw 'This Compose project already has containers running. Stop or inspect them before starting another lab run.'
    }
  }
  foreach ($artifact in @(
    'ml\artifacts\models\champion_model.joblib',
    'ml\artifacts\models\preprocessor.joblib'
  )) {
    if (-not (Test-Path (Join-Path $ProjectRoot $artifact))) {
      throw "Required trained model artifact is missing: $artifact"
    }
  }

  Push-Location $ProjectRoot
  try {
    & $Docker.Source info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is unavailable. Start Docker Desktop and retry.' }
    & $Docker.Source compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration validation failed.' }

    Write-Host 'Building and starting CyberAdapt containers...'
    $StackStarted = $true
    & $Docker.Source compose up -d --build mongo ml-api backend dashboard target
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed while building or starting the services.' }

    $mlHealth = Test-LabReady -Url 'http://127.0.0.1:5001/health' -Description 'ML API'
    if (-not $mlHealth.model_ready) { throw 'The ML API started without loading its trained model.' }
    Test-LabReady -Url 'http://127.0.0.1:5000/api/health' -Description 'Backend' | Out-Null
    Test-LabReady -Url 'http://127.0.0.1:3000' -Description 'Dashboard' | Out-Null
    Test-LabReady -Url 'http://127.0.0.1:5055/' -Description 'OWASP Juice Shop' | Out-Null

    $seedOutput = & $Docker.Source compose run --rm seed 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Development seed failed: $($seedOutput -join ' ')" }
    $seedText = $seedOutput -join "`n"
    $keyMatch = [regex]::Match($seedText, 'ca_live_[a-fA-F0-9]{32,}')
    if (-not $keyMatch.Success) { throw 'Seed script completed without returning a sensor key.' }

    [Environment]::SetEnvironmentVariable('SENSOR_KEY', $keyMatch.Value, 'Process')
    & $Docker.Source compose up -d --no-deps --force-recreate sensor
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the packet sensor container.' }

    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'docker-reports') | Out-Null
    $samplesBeforeScan = (Invoke-RestMethod -Uri 'http://127.0.0.1:5001/concept-drift' -TimeoutSec 5).samples_processed
    Write-Host "Running OWASP ZAP active scan against local Juice Shop (hard limit: $ScanTimeoutMinutes minute(s))."
    Write-Host 'The target is intentionally vulnerable and published only on 127.0.0.1:5055.'
    $scanTimeout = "$($ScanTimeoutMinutes)m"
    & $Docker.Source compose run --rm --no-deps zap timeout `
      --signal=TERM --kill-after=15s $scanTimeout zap-full-scan.py `
      -t http://target:3000 -m 1 -T 5 -I `
      -r /zap/wrk/zap-report.html -J /zap/wrk/zap-report.json
    $zapExitCode = $LASTEXITCODE
    $scanTimedOut = $zapExitCode -eq 124 -or $zapExitCode -eq 137
    $reportExists = Test-Path (Join-Path $ProjectRoot 'docker-reports\zap-report.html')
    if (-not $reportExists -and -not $scanTimedOut) {
      throw "OWASP ZAP did not produce its report. Exit code: $zapExitCode"
    }
    if ($scanTimedOut) {
      Write-Warning 'The active scan reached its time limit. Captured flows are still evaluated, but ZAP may not have completed its report.'
    } elseif ($zapExitCode -ne 0) {
      Write-Warning "OWASP ZAP exited with code $zapExitCode; this can indicate findings. Review docker-reports\zap-report.html."
    }

    $deadline = (Get-Date).AddSeconds(60)
    $drift = $null
    do {
      Start-Sleep -Seconds 2
      $drift = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/concept-drift' -TimeoutSec 5
    } while ($drift.samples_processed -le $samplesBeforeScan -and (Get-Date) -lt $deadline)
    if ($drift.samples_processed -le $samplesBeforeScan) {
      & $Docker.Source compose logs --tail 30 sensor
      throw 'No newly captured scan flows reached ML inference within 60 seconds. Review the sensor logs above.'
    }
    Write-Host ''
    Write-Host "ML samples processed: $($drift.samples_processed); drift state: $($drift.drift_state)."
    Write-Host 'Dashboard: http://127.0.0.1:3000 (admin@acme-test.local / Test@1234)'
    Write-Host 'Intentionally vulnerable target: http://127.0.0.1:5055'
    if ($reportExists) {
      Write-Host 'OWASP ZAP report: docker-reports\zap-report.html'
    }
    Write-Host 'ZAP findings are web-application results; model predictions are separate and are not supplied with attack labels.'
    Write-Host 'Press Ctrl+C to stop the containers. MongoDB data and ML state are kept in Docker volumes.'
    Start-Process 'http://127.0.0.1:3000'

    while ($true) {
      Start-Sleep -Seconds 2
    }
  } finally {
    Pop-Location
  }
} catch {
  Write-Error $_
  exit 1
} finally {
  [Environment]::SetEnvironmentVariable('SENSOR_KEY', $PreviousSensorKey, 'Process')
  if ($StackStarted) {
    Push-Location $ProjectRoot
    try {
      & $Docker.Source compose down
      if ($LASTEXITCODE -ne 0) { Write-Warning 'Some CyberAdapt containers could not be stopped cleanly.' }
    } finally {
      Pop-Location
    }
  }
}
