[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$SkipMigrations,
    [switch]$SkipInstall,
    [switch]$NoBackend,
    [switch]$NoFrontend,
    [switch]$NoLaunch,
    [switch]$UseCurrentTerminal
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendVenvDir = Join-Path $backendDir "venv"
$backendPython = Join-Path $backendVenvDir "Scripts\python.exe"
$shellPath = (Get-Process -Id $PID).Path
$logDir = Join-Path $projectRoot ".dev-logs"
$preferredFrontendPort = 5173
$fallbackFrontendPorts = @(4173, 3000)
$isVsCodeSession = ($env:TERM_PROGRAM -eq "vscode") -or (-not [string]::IsNullOrWhiteSpace($env:VSCODE_PID))
$shouldUseCurrentTerminal = $UseCurrentTerminal -or $isVsCodeSession

function Write-Step {
    param([string]$Message)

    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed: $FilePath $($ArgumentList -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Ensure-FileFromExample {
    param(
        [string]$Path,
        [string]$ExamplePath
    )

    if (-not (Test-Path $Path)) {
        if (-not (Test-Path $ExamplePath)) {
            throw "Missing template file: $ExamplePath"
        }

        Copy-Item $ExamplePath $Path
        Write-Step "Created $Path from its example template"
    }
}

function Test-BackendDependencies {
    if (-not (Test-Path $backendPython)) {
        return $false
    }

    & $backendPython -c "import fastapi, uvicorn, psycopg" *> $null
    return $LASTEXITCODE -eq 0
}

function Wait-ForPostgresHealth {
    Write-Step "Waiting for PostgreSQL to report healthy status"

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $status = (& docker inspect -f "{{.State.Health.Status}}" agentic-rag-postgres 2>$null).Trim()
        if ($LASTEXITCODE -eq 0 -and $status -eq "healthy") {
            return
        }

        Start-Sleep -Seconds 2
    }

    throw "PostgreSQL did not become healthy within 60 seconds."
}

function Escape-SingleQuoted {
    param([string]$Value)

    return $Value.Replace("'", "''")
}

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )

    $escapedTitle = Escape-SingleQuoted $Title
    $escapedWorkingDirectory = Escape-SingleQuoted $WorkingDirectory
    $bootstrap = "`$Host.UI.RawUI.WindowTitle = '$escapedTitle'; Set-Location -LiteralPath '$escapedWorkingDirectory'; $Command"

    Start-Process -FilePath $shellPath -WorkingDirectory $WorkingDirectory -ArgumentList @(
        "-NoExit",
        "-Command",
        $bootstrap
    ) | Out-Null
}

function Stop-JobByName {
    param([string]$Name)

    $jobs = Get-Job -Name $Name -ErrorAction SilentlyContinue
    foreach ($job in $jobs) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

function Start-ServiceJob {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$LogPath
    )

    Stop-JobByName -Name $Name
    if (Test-Path $LogPath) {
        Remove-Item $LogPath -Force
    }

    Start-Job -Name $Name -ArgumentList $WorkingDirectory, $FilePath, $ArgumentList, $LogPath -ScriptBlock {
        param(
            [string]$WorkingDirectory,
            [string]$FilePath,
            [string[]]$ArgumentList,
            [string]$LogPath
        )

        Set-Location -LiteralPath $WorkingDirectory
        & $FilePath @ArgumentList *>&1 | Tee-Object -FilePath $LogPath -Append
    } | Out-Null
}

function Stop-ListeningProcess {
    param(
        [int]$Port,
        [string]$Name
    )

    $listeningProcessIds = @()

    try {
        $listeningProcessIds = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    }
    catch {
        $listeningProcessIds = @()
    }

    foreach ($processId in $listeningProcessIds) {
        if ($processId -eq $PID) {
            continue
        }

        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Step "Stopped existing $Name process on port $Port (PID $processId)"
        }
        catch {
            Write-Warning "Failed to stop process $processId on port $Port"
        }
    }
}

function Test-TcpPortAvailable {
    param([int]$Port)

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) {
            try {
                $listener.Stop()
            }
            catch {
            }
        }
    }
}

function Resolve-FrontendPort {
    $candidatePorts = @($preferredFrontendPort) + $fallbackFrontendPorts
    foreach ($port in $candidatePorts) {
        if (Test-TcpPortAvailable -Port $port) {
            return $port
        }
    }

    throw "Unable to find an available frontend port. Checked: $($candidatePorts -join ', ')"
}

Ensure-FileFromExample -Path (Join-Path $projectRoot ".env") -ExamplePath (Join-Path $projectRoot ".env.example")
Ensure-FileFromExample -Path (Join-Path $frontendDir ".env") -ExamplePath (Join-Path $frontendDir ".env.example")

if (-not $SkipDocker) {
    Require-Command "docker"
    Write-Step "Starting PostgreSQL with Docker Compose"
    Invoke-Checked -FilePath "docker" -ArgumentList @("compose", "up", "-d", "postgres") -WorkingDirectory $projectRoot
    Wait-ForPostgresHealth
}

if ((-not $NoBackend) -or (-not $SkipMigrations)) {
    Require-Command "python"
}

if (-not $NoFrontend) {
    Require-Command "npm"
}

$backendDepsReady = Test-BackendDependencies
if (-not $backendDepsReady) {
    if (-not (Test-Path $backendPython)) {
        Write-Step "Creating backend virtual environment"
        Invoke-Checked -FilePath "python" -ArgumentList @("-m", "venv", $backendVenvDir) -WorkingDirectory $projectRoot
    }

    if ($SkipInstall) {
        throw "Backend dependencies are missing and -SkipInstall was provided."
    }

    Write-Step "Installing backend dependencies"
    Invoke-Checked -FilePath $backendPython -ArgumentList @("-m", "pip", "install", "-r", (Join-Path $backendDir "requirements.txt")) -WorkingDirectory $projectRoot
}

if ((-not (Test-Path (Join-Path $frontendDir "node_modules"))) -and (-not $NoFrontend)) {
    if ($SkipInstall) {
        throw "Frontend dependencies are missing and -SkipInstall was provided."
    }

    Write-Step "Installing frontend dependencies"
    Invoke-Checked -FilePath "npm" -ArgumentList @("install") -WorkingDirectory $frontendDir
}

if (-not $SkipMigrations) {
    Write-Step "Applying database migrations"
    Invoke-Checked -FilePath $backendPython -ArgumentList @((Join-Path $backendDir "scripts\init_db.py")) -WorkingDirectory $projectRoot
}

if ($NoLaunch) {
    Write-Step "Setup completed without launching services"
    return
}

if ($shouldUseCurrentTerminal -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

if (-not $NoBackend) {
    Stop-ListeningProcess -Port 8000 -Name "backend"
    Write-Step "Launching backend API on http://localhost:8000"
    if ($shouldUseCurrentTerminal) {
        Start-ServiceJob `
            -Name "agentic-rag-backend" `
            -WorkingDirectory $backendDir `
            -FilePath $backendPython `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000") `
            -LogPath (Join-Path $logDir "backend.log")
    }
    else {
        $escapedBackendPython = Escape-SingleQuoted $backendPython
        Start-ServiceWindow -Title "Agentic RAG Backend" -WorkingDirectory $backendDir -Command "& '$escapedBackendPython' -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    }
}

if (-not $NoFrontend) {
    Stop-ListeningProcess -Port $preferredFrontendPort -Name "frontend"
    $frontendPort = Resolve-FrontendPort
    if ($frontendPort -ne $preferredFrontendPort) {
        Write-Warning "Port $preferredFrontendPort is unavailable. Falling back to frontend port $frontendPort."
    }
    Write-Step "Launching frontend on http://localhost:$frontendPort"
    if ($shouldUseCurrentTerminal) {
        Start-ServiceJob `
            -Name "agentic-rag-frontend" `
            -WorkingDirectory $frontendDir `
            -FilePath "npm" `
            -ArgumentList @("run", "dev", "--", "--host", "0.0.0.0", "--port", "$frontendPort", "--strictPort") `
            -LogPath (Join-Path $logDir "frontend.log")
    }
    else {
        Start-ServiceWindow -Title "Agentic RAG Frontend" -WorkingDirectory $frontendDir -Command "npm run dev -- --host 0.0.0.0 --port $frontendPort --strictPort"
    }
}

Write-Host ""
Write-Host "Project startup complete." -ForegroundColor Green
if (-not $NoBackend) {
    Write-Host "Backend:  http://localhost:8000"
}
if (-not $NoFrontend) {
    Write-Host "Frontend: http://localhost:$frontendPort"
}
if ($shouldUseCurrentTerminal) {
    Write-Host "Logs:     $logDir"
    Write-Host "Jobs:     Get-Job -Name agentic-rag-*"
    Write-Host "Tail:     Get-Content '$logDir\\backend.log' -Wait"
    Write-Host "Tail:     Get-Content '$logDir\\frontend.log' -Wait"
}
