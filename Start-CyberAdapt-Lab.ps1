param(
  [int]$NormalCount = 10,
  [int]$AttackCount = 5,
  [string]$CaptureInterface
)

$ErrorActionPreference = 'Stop'

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  $scriptPath = $MyInvocation.MyCommand.Path
  $hostExecutable = (Get-Process -Id $PID).Path
  $elevatedArguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -NormalCount {1} -AttackCount {2}' -f `
    $scriptPath, $NormalCount, $AttackCount
  if ($CaptureInterface) {
    $elevatedArguments += ' -CaptureInterface "' + $CaptureInterface + '"'
  }
  Start-Process -FilePath $hostExecutable -Verb RunAs `
    -ArgumentList $elevatedArguments `
    -WorkingDirectory (Split-Path -Parent $scriptPath) | Out-Null
  Write-Host 'Accepted the UAC prompt to continue in one elevated PowerShell window.'
  return
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogRoot = Join-Path $env:TEMP ("CyberAdapt-lab-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$Processes = New-Object System.Collections.Generic.List[System.Diagnostics.Process]
$MongoServiceStarted = $false
$StartedMongoProcess = $null
$SavedEnvironment = @{}

function Test-TcpPort {
  param([string]$HostName, [int]$Port)
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $result = $client.BeginConnect($HostName, $Port, $null, $null)
    if (-not $result.AsyncWaitHandle.WaitOne(300)) { return $false }
    $client.EndConnect($result)
    return $true
  } catch {
    return $false
  } finally {
    $client.Dispose()
  }
}

function Wait-HttpReady {
  param([string]$Url, [string]$Description, [int]$TimeoutSeconds = 60)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
      return $response
    } catch {
      Start-Sleep -Milliseconds 750
    }
  }
  throw "$Description did not become ready at $Url. See logs in $LogRoot"
}

function Start-LabProcess {
  param(
    [string]$Name,
    [string]$Executable,
    [string[]]$Arguments,
    [string]$WorkingDirectory
  )
  $stdout = Join-Path $LogRoot "$Name.stdout.log"
  $stderr = Join-Path $LogRoot "$Name.stderr.log"
  $argumentString = ($Arguments | ForEach-Object {
    '"' + $_.Replace('"', '\"') + '"'
  }) -join ' '
  $process = Start-Process -FilePath $Executable `
    -ArgumentList $argumentString `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru
  $Processes.Add($process)
  Write-Host "Started $Name (PID $($process.Id)); logs: $stdout"
  return $process
}

function Set-LabEnvironment {
  param([string]$Name, [string]$Value)
  if (-not $SavedEnvironment.ContainsKey($Name)) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
  }
  [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

function Restore-LabEnvironment {
  param([string]$Name)
  if ($SavedEnvironment.ContainsKey($Name)) {
    [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], 'Process')
  }
}

try {
  if ($NormalCount -lt 0 -or $NormalCount -gt 1000) {
    throw 'NormalCount must be between 0 and 1000.'
  }
  if ($AttackCount -lt 0 -or $AttackCount -gt 250) {
    throw 'AttackCount must be between 0 and 250.'
  }

  $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
  if (-not $nodeCommand) { throw 'Node.js was not found on PATH. Install Node.js 18 or later.' }
  $node = $nodeCommand.Source
  $python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
  $serverEntry = Join-Path $ProjectRoot 'server\server.js'
  $seedEntry = Join-Path $ProjectRoot 'server\scripts\seed-dev.js'
  $targetEntry = Join-Path $ProjectRoot 'server\scripts\cyberadapt-test-target.js'
  $driverEntry = Join-Path $ProjectRoot 'server\scripts\cyberadapt-test-driver.js'
  $sensorEntry = Join-Path $ProjectRoot 'sensor\sensor.py'
  $viteEntry = Join-Path $ProjectRoot 'client\node_modules\vite\bin\vite.js'
  $expressManifest = Join-Path $ProjectRoot 'server\node_modules\express\package.json'
  $modelPath = Join-Path $ProjectRoot 'ml\artifacts\models\champion_model.joblib'
  $preprocessorPath = Join-Path $ProjectRoot 'ml\artifacts\models\preprocessor.joblib'

  foreach ($requiredPath in @(
    $python, $serverEntry, $seedEntry, $targetEntry, $driverEntry,
    $sensorEntry, $viteEntry, $expressManifest, $modelPath, $preprocessorPath
  )) {
    if (-not (Test-Path $requiredPath)) {
      throw "Required project file is missing: $requiredPath. Install project dependencies or restore the model artifacts first."
    }
  }

  $interfaceJson = & $python -c "import json; from scapy.all import get_if_list; print(json.dumps(get_if_list()))" 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw 'Scapy is unavailable in .venv. Run .venv\Scripts\python.exe -m pip install scapy requests.'
  }
  $interfaces = @($interfaceJson | ConvertFrom-Json)
  if (-not $CaptureInterface) {
    if ($interfaces -contains '\Device\NPF_Loopback') {
      $CaptureInterface = '\Device\NPF_Loopback'
    } else {
      $loopbackAdapter = $null
      if (Get-Command Get-NetAdapter -ErrorAction SilentlyContinue) {
        $loopbackAdapter = Get-NetAdapter -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -like '*Npcap*Loopback*' } |
          Select-Object -First 1
      }
      if ($loopbackAdapter) {
        $adapterPath = '\Device\NPF_{' + $loopbackAdapter.InterfaceGuid.ToString() + '}'
        if ($interfaces -contains $adapterPath) {
          $CaptureInterface = $adapterPath
        }
      }
    }
  }
  if (-not $CaptureInterface -or $interfaces -notcontains $CaptureInterface) {
    $available = $interfaces -join "`n  "
    throw "Npcap loopback capture interface was not found. Install Npcap with loopback support. Available Scapy interfaces:`n  $available`nThen run: .\Start-CyberAdapt-Lab.ps1 -CaptureInterface '<interface>'"
  }

  foreach ($port in @(5000, 5001, 3000, 5055)) {
    if (Test-TcpPort -HostName '127.0.0.1' -Port $port) {
      throw "Port $port is already in use. Stop the existing CyberAdapt process before starting this lab."
    }
  }

  New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
  $mongoData = Join-Path $env:LOCALAPPDATA 'CyberAdapt\mongodb-data'
  New-Item -ItemType Directory -Force -Path $mongoData | Out-Null

  if (-not (Test-TcpPort -HostName '127.0.0.1' -Port 27017)) {
    $mongoService = Get-Service -Name 'MongoDB' -ErrorAction SilentlyContinue
    if ($mongoService) {
      if ($mongoService.Status -ne 'Running') {
        Start-Service -Name 'MongoDB'
        $MongoServiceStarted = $true
      }
    } else {
      $mongodCommand = Get-Command mongod.exe -ErrorAction SilentlyContinue
      if (-not $mongodCommand) {
        throw 'MongoDB is not running and neither a MongoDB service nor mongod.exe was found.'
      }
      $StartedMongoProcess = Start-LabProcess -Name 'mongodb' `
        -Executable $mongodCommand.Source `
        -Arguments @('--dbpath', $mongoData, '--bind_ip', '127.0.0.1', '--port', '27017') `
        -WorkingDirectory $ProjectRoot
    }
    $mongoDeadline = (Get-Date).AddSeconds(45)
    while (-not (Test-TcpPort -HostName '127.0.0.1' -Port 27017) -and (Get-Date) -lt $mongoDeadline) {
      Start-Sleep -Milliseconds 500
    }
    if (-not (Test-TcpPort -HostName '127.0.0.1' -Port 27017)) {
      throw 'MongoDB did not start on 127.0.0.1:27017.'
    }
  }

  Write-Host 'Creating or refreshing the local development sensor key...'
  Push-Location (Join-Path $ProjectRoot 'server')
  try {
    $seedOutput = & $node $seedEntry 2>&1
    $seedExitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  if ($seedExitCode -ne 0) {
    throw "Development seeding failed: $($seedOutput -join ' ')"
  }
  $seedText = $seedOutput -join "`n"
  $keyMatch = [regex]::Match($seedText, 'ca_live_[a-fA-F0-9]{32,}')
  if (-not $keyMatch.Success) {
    throw "Seed script completed but did not return a sensor key: $seedText"
  }
  $sensorKey = $keyMatch.Value

  Set-LabEnvironment -Name 'MODEL_PATH' -Value 'ml/artifacts/models/champion_model.joblib'
  Set-LabEnvironment -Name 'PREPROCESSOR_PATH' -Value 'ml/artifacts/models/preprocessor.joblib'
  Set-LabEnvironment -Name 'PORT' -Value '5001'
  Start-LabProcess -Name 'ml-api' -Executable $python `
    -Arguments @('-m', 'ml.api') -WorkingDirectory $ProjectRoot | Out-Null
  Restore-LabEnvironment -Name 'MODEL_PATH'
  Restore-LabEnvironment -Name 'PREPROCESSOR_PATH'
  Restore-LabEnvironment -Name 'PORT'
  $mlHealth = Wait-HttpReady -Url 'http://127.0.0.1:5001/health' -Description 'ML API'
  if (-not $mlHealth.model_ready) { throw 'ML API started but its trained model is not ready.' }

  Set-LabEnvironment -Name 'PORT' -Value '5000'
  Start-LabProcess -Name 'backend' -Executable $node `
    -Arguments @($serverEntry) -WorkingDirectory (Join-Path $ProjectRoot 'server') | Out-Null
  Restore-LabEnvironment -Name 'PORT'
  Wait-HttpReady -Url 'http://127.0.0.1:5000/api/health' -Description 'Node backend' | Out-Null

  Start-LabProcess -Name 'dashboard' -Executable $node `
    -Arguments @($viteEntry, '--host', '127.0.0.1', '--port', '3000', '--strictPort') `
    -WorkingDirectory (Join-Path $ProjectRoot 'client') | Out-Null
  Wait-HttpReady -Url 'http://127.0.0.1:3000' -Description 'Dashboard' | Out-Null

  Start-LabProcess -Name 'local-target' -Executable $node `
    -Arguments @($targetEntry) -WorkingDirectory $ProjectRoot | Out-Null
  Wait-HttpReady -Url 'http://127.0.0.1:5055/health' -Description 'Local HTTP target' | Out-Null

  Set-LabEnvironment -Name 'SENSOR_KEY' -Value $sensorKey
  Set-LabEnvironment -Name 'INGEST_URL' -Value 'http://127.0.0.1:5000/api/telemetry/ingest'
  Set-LabEnvironment -Name 'INTERFACE' -Value $CaptureInterface
  Set-LabEnvironment -Name 'CAPTURE_FILTER' -Value 'ip and host 127.0.0.1 and port 5055'
  Start-LabProcess -Name 'packet-sensor' -Executable $python `
    -Arguments @($sensorEntry) -WorkingDirectory $ProjectRoot | Out-Null
  Restore-LabEnvironment -Name 'SENSOR_KEY'
  Restore-LabEnvironment -Name 'INGEST_URL'
  Restore-LabEnvironment -Name 'INTERFACE'
  Restore-LabEnvironment -Name 'CAPTURE_FILTER'

  Start-Sleep -Seconds 2
  $driverArguments = @($driverEntry, '--normal-count', "$NormalCount", '--attack-count', "$AttackCount")
  & $node @driverArguments
  if ($LASTEXITCODE -ne 0) { throw 'Local traffic driver failed. Inspect its output and the service logs.' }

  Start-Sleep -Seconds 4
  $drift = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/concept-drift' -TimeoutSec 5
  Write-Host ''
  Write-Host "Traffic sent. ML samples processed: $($drift.samples_processed); drift state: $($drift.drift_state)."
  Write-Host 'Open http://127.0.0.1:3000 and sign in with admin@acme-test.local / Test@1234.'
  Write-Host "Service logs: $LogRoot"
  Write-Host 'The local target returns safe test responses; this is not an exploit or proof of detection accuracy.'
  Write-Host 'Press Ctrl+C to stop the services started by this launcher.'
  Start-Process 'http://127.0.0.1:3000'

  while ($true) {
    foreach ($process in $Processes) {
      $process.Refresh()
      if ($process.HasExited) {
        throw "A lab process exited unexpectedly (PID $($process.Id)). Check logs at $LogRoot."
      }
    }
    Start-Sleep -Seconds 2
  }
} catch {
  Write-Error $_
  exit 1
} finally {
  foreach ($name in $SavedEnvironment.Keys) {
    [Environment]::SetEnvironmentVariable($name, $SavedEnvironment[$name], 'Process')
  }
  foreach ($process in $Processes) {
    try {
      $process.Refresh()
      if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
      }
    } catch {
      Write-Warning "Could not stop lab process PID $($process.Id): $_"
    }
  }
  if ($StartedMongoProcess) {
    try {
      $StartedMongoProcess.Refresh()
      if (-not $StartedMongoProcess.HasExited) {
        Stop-Process -Id $StartedMongoProcess.Id -Force -ErrorAction SilentlyContinue
      }
    } catch {
      Write-Warning "Could not stop MongoDB PID $($StartedMongoProcess.Id): $_"
    }
  }
  if ($MongoServiceStarted) {
    Stop-Service -Name 'MongoDB' -ErrorAction SilentlyContinue
  }
}
