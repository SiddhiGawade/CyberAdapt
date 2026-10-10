$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

Write-Host 'Starting CyberAdapt services...'
docker compose up -d mongo ml-api backend dashboard
if ($LASTEXITCODE -ne 0) {
    throw 'Could not start CyberAdapt services. Check that Docker Desktop is running.'
}

Write-Host "`nCreating a development account and sensor key..."
docker compose --profile tools run --rm seed
if ($LASTEXITCODE -ne 0) {
    throw 'Seeding failed. Check the backend and MongoDB logs with: docker compose logs backend mongo'
}

$sensorKey = Read-Host "`nPaste the ca_live_ sensor key printed above"
if ([string]::IsNullOrWhiteSpace($sensorKey) -or -not $sensorKey.StartsWith('ca_live_')) {
    throw 'A valid sensor key starting with ca_live_ is required.'
}

Write-Host "`nSending 10 mixed feature examples through the backend..."
python sensor/direct_feature_injector.py --key $sensorKey --scenario mixed --count 10 --mode backend
if ($LASTEXITCODE -ne 0) {
    throw 'Feature submission failed. Confirm Python and the requests package are available.'
}

Write-Host "`nDone. Open the dashboard at http://localhost:3000"
Write-Host 'To inspect service logs, run: docker compose logs --tail 50 backend ml-api'
