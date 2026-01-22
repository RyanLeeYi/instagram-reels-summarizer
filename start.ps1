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
Write-Host "[1/4] Checking Ollama..." -ForegroundColor Yellow
$ollamaProcess = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaProcess) {
    Write-Host "      Starting Ollama..." -ForegroundColor Gray
    Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}
Write-Host "      Ollama OK" -ForegroundColor Green

# Pre-warm Roam Research MCP server (optional, for Claude Code integration)
Write-Host "[2/4] Pre-warming MCP server..." -ForegroundColor Yellow
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
Write-Host "[3/4] Checking venv..." -ForegroundColor Yellow
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "      Error: Virtual environment not found!" -ForegroundColor Red
    Write-Host "      Run: python -m venv .venv" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "      Venv OK" -ForegroundColor Green

# Start service
Write-Host "[4/4] Starting FastAPI..." -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Running at http://localhost:8000" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
