param(
    [int]$Port = 8501,
    [switch]$SkipInstall,
    [switch]$InitLocalConfig,
    [switch]$NoSampleData,
    [switch]$SkipRefresh,
    [switch]$ForceRefresh,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSCommandPath
Set-Location -LiteralPath $ProjectRoot

$VenvDir = Join-Path $ProjectRoot ".venv"
$script:VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$DashboardPath = Join-Path $ProjectRoot "job_pipeline\dashboard.py"
$SearchScopePath = Join-Path $ProjectRoot "config\search_scope.yaml"
$DbPath = Join-Path $ProjectRoot "data\job_pipeline.sqlite"
$TodayStamp = Get-Date -Format "yyyyMMdd"
$TodayJobsReportPath = Join-Path $ProjectRoot "data\reports\daily_jobs_$TodayStamp.csv"
$Url = "http://localhost:$Port"

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-LocalPython {
    param([string[]]$Arguments)

    & $script:VenvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function New-LocalVenv {
    param([string]$Path)

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -m venv $Path
        if ($LASTEXITCODE -eq 0) {
            return
        }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        & $pyCommand.Source -3 -m venv $Path
        if ($LASTEXITCODE -eq 0) {
            return
        }
    }

    throw "Could not create .venv. Install Python 3, then run this launcher again."
}

function Test-LocalPort {
    param([int]$Port)

    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($client) {
            $client.Close()
        }
    }
}

function Test-DashboardImports {
    & $script:VenvPython -c "import streamlit, pandas, yaml"
    return ($LASTEXITCODE -eq 0)
}

function Start-BrowserWhenReady {
    param(
        [string]$Url,
        [int]$Port
    )

    $safeUrl = $Url.Replace("'", "''")
    $command = @"
`$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt `$deadline) {
    `$client = `$null
    try {
        `$client = [System.Net.Sockets.TcpClient]::new()
        `$async = `$client.BeginConnect('127.0.0.1', $Port, `$null, `$null)
        if (`$async.AsyncWaitHandle.WaitOne(500, `$false)) {
            `$client.EndConnect(`$async)
            Start-Process '$safeUrl'
            break
        }
    }
    catch {
    }
    finally {
        if (`$client) {
            `$client.Close()
        }
    }
    Start-Sleep -Milliseconds 700
}
"@

    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-Command",
        $command
    ) -WindowStyle Hidden | Out-Null
}

if (-not (Test-Path -LiteralPath $DashboardPath)) {
    throw "Dashboard file not found: $DashboardPath"
}

if (Test-LocalPort -Port $Port) {
    Write-Step "Dashboard is already running"
    Write-Host "Opening $Url"
    Start-Process $Url
    exit 0
}

if (-not (Test-Path -LiteralPath $script:VenvPython)) {
    Write-Step "Creating local Python virtual environment"
    New-LocalVenv -Path $VenvDir
}

if ($CheckOnly) {
    Write-Step "Launcher check passed"
    Write-Host "Project: $ProjectRoot"
    Write-Host "Python:  $script:VenvPython"
    Write-Host "URL:     $Url"
    exit 0
}

if (-not $SkipInstall) {
    if (-not (Test-DashboardImports)) {
        Write-Step "Installing dashboard dependencies"
        Invoke-LocalPython @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-LocalPython @("-m", "pip", "install", "-r", $RequirementsPath)
    }
}

if ($InitLocalConfig) {
    Write-Step "Creating local config files"
    Invoke-LocalPython @("-m", "job_pipeline.setup_wizard", "--init")
}

if (-not $NoSampleData) {
    if (-not (Test-Path -LiteralPath $DbPath)) {
        Write-Step "Creating sample dashboard data"
        Invoke-LocalPython @("-m", "job_pipeline.scheduler", "--run-once", "--sample")
    }
}

if (-not $SkipRefresh) {
    if ($ForceRefresh -or -not (Test-Path -LiteralPath $TodayJobsReportPath)) {
        Write-Step "Refreshing today's job data"
        Invoke-LocalPython @("-m", "job_pipeline.scheduler", "--run-once", "--mode", "normal")
    }
    else {
        Write-Step "Today's job data already exists"
        Write-Host "Report: $TodayJobsReportPath"
    }
}

Write-Step "Starting Local Job Pipeline dashboard"
Write-Host "URL: $Url"
Write-Host "Leave this window open while you use the dashboard."
Write-Host "Press Ctrl+C in this window to stop the local service."

$env:PYTHONPATH = $ProjectRoot
$env:STREAMLIT_SERVER_HEADLESS = "true"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
Start-BrowserWhenReady -Url $Url -Port $Port
Invoke-LocalPython @("-m", "streamlit", "run", $DashboardPath, "--server.port", "$Port", "--server.headless", "true", "--browser.gatherUsageStats", "false")
