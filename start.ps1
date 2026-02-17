# Instagram Reels Summarizer Startup Script
# ==========================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Instagram Reels Summarizer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Change to project directory
Set-Location $PSScriptRoot

# Check if Ollama is running
Write-Host "[1/5] Checking Ollama..." -ForegroundColor Yellow
$ollamaProcess = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaProcess) {
    Write-Host "      Starting Ollama..." -ForegroundColor Gray
    Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}
Write-Host "      Ollama OK" -ForegroundColor Green

# Pre-warm Roam Research MCP server (optional, for Claude Code integration)
Write-Host "[2/5] Pre-warming MCP server..." -ForegroundColor Yellow
$mcpLogFile = "$env:TEMP\roam-mcp.log"
$existingMcp = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        $cmdLine -like "*roam-research-mcp*"
    } catch {
        $false
    }
}

if ($existingMcp) {
    Write-Host "      MCP server already running" -ForegroundColor Green
} else {
    # Check if npx is available
    $npxPath = Get-Command npx -ErrorAction SilentlyContinue
    if ($npxPath) {
        Write-Host "      Starting MCP server in background..." -ForegroundColor Gray
        # Start MCP server in background, redirect output to log file
        $mcpJob = Start-Job -ScriptBlock {
            param($logFile)
            & npx -y roam-research-mcp 2>&1 | Out-File -FilePath $logFile -Append
        } -ArgumentList $mcpLogFile
        
        # Wait a bit for it to initialize
        Start-Sleep -Seconds 5
        
        # Check if job is still running (means server started successfully)
        if ($mcpJob.State -eq "Running") {
            Write-Host "      MCP server started (log: $mcpLogFile)" -ForegroundColor Green
        } else {
            Write-Host "      MCP server may have issues, check log" -ForegroundColor Yellow
        }
    } else {
        Write-Host "      npx not found, skipping MCP (install Node.js for Claude Code sync)" -ForegroundColor Yellow
    }
}

# Check virtual environment
Write-Host "[3/5] Checking venv..." -ForegroundColor Yellow
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "      Error: Virtual environment not found!" -ForegroundColor Red
    Write-Host "      Run: python -m venv .venv" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "      Venv OK" -ForegroundColor Green

# Start Chrome CDP for NotebookLM automation
Write-Host "[4/5] Starting Chrome CDP..." -ForegroundColor Yellow
$envContent = Get-Content ".\.env" -ErrorAction SilentlyContinue
$nlmEnabled = ($envContent | Where-Object { $_ -match "^NOTEBOOKLM_ENABLED\s*=\s*true" }) -ne $null

if ($nlmEnabled) {
    # Check if Chrome CDP is already running on port 9222
    $cdpPort = 9222
    $cdpRunning = $false
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:$cdpPort/json/version" -TimeoutSec 2 -ErrorAction Stop
        $cdpRunning = $true
    } catch {
        $cdpRunning = $false
    }

    if ($cdpRunning) {
        Write-Host "      Chrome CDP already running on port $cdpPort" -ForegroundColor Green
    } else {
        # Find Chrome executable
        $chromePath = $null
        $chromePaths = @(
            "C:\Program Files\Google\Chrome\Application\chrome.exe",
            "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
        )
        foreach ($p in $chromePaths) {
            if (Test-Path $p) { $chromePath = $p; break }
        }

        if ($chromePath) {
            $chromeProfile = "$env:USERPROFILE\.chrome-cdp-notebooklm"
            Write-Host "      Starting Chrome with CDP on port $cdpPort..." -ForegroundColor Gray
            Write-Host "      Profile: $chromeProfile" -ForegroundColor Gray
            Write-Host "      First time: Please login to Google in this Chrome window" -ForegroundColor Gray
            Start-Process -FilePath $chromePath -ArgumentList @(
                "--remote-debugging-port=$cdpPort",
                "--user-data-dir=`"$chromeProfile`"",
                "--no-first-run",
                "--no-default-browser-check",
                "https://notebooklm.google.com"
            )
            Start-Sleep -Seconds 3

            # Verify CDP is up
            try {
                $response = Invoke-RestMethod -Uri "http://localhost:$cdpPort/json/version" -TimeoutSec 5 -ErrorAction Stop
                Write-Host "      Chrome CDP OK (port $cdpPort)" -ForegroundColor Green
            } catch {
                Write-Host "      Chrome CDP may not be ready, will retry at upload time" -ForegroundColor Yellow
            }
        } else {
            Write-Host "      Chrome not found, NotebookLM upload will be skipped" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "      NotebookLM disabled, skipping" -ForegroundColor Gray
}

# Start service
Write-Host "[5/5] Starting FastAPI..." -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Running at http://localhost:8000" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
