# 一鍵恢復可開發、可驗證狀態（全新 clone 或換機後跑這支）
$ErrorActionPreference = "Stop"
# pip 失敗一律由 $LASTEXITCODE 判定：讓 pwsh 7.4+ 自動把 native 非零轉成終止錯誤的話，
# 第一個裝不起來的套件就會中斷腳本，只列得出一個（F20 要求列出所有失敗的）
$PSNativeCommandUseErrorActionPreference = $false
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "已建立 venv"
}

function Find-FailedRequirements {
    # pip 批次安裝失敗時的輸出不保證指名是哪幾條，逐條重跑才問得出來
    param([string]$File)

    $failed = @()
    foreach ($line in Get-Content $File) {
        $req = $line.Split("#")[0].Trim()
        if (-not $req) { continue }
        & $python -m pip install -q $req
        if ($LASTEXITCODE -ne 0) { $failed += $req }
    }
    if ($failed.Count -eq 0) {
        $failed += "(逐條重裝都成功，批次失敗多半是套件間相依衝突，請看上方 pip 輸出)"
    }
    return $failed
}

$failed = @()

& $python -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { $failed += Find-FailedRequirements "requirements.txt" }

& $python -m pip install -q pytest pytest-asyncio
if ($LASTEXITCODE -ne 0) { $failed += @("pytest", "pytest-asyncio") }

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "init 失敗：以下套件無法安裝"
    foreach ($pkg in $failed) { Write-Host "  - $pkg" }
    Write-Host "環境尚未恢復完成，先解決上列套件再重跑 init.ps1"
    exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[warn] 已建立 .env，請填入 TELEGRAM_BOT_TOKEN 等密鑰（存在密碼管理器）"
}
if (-not (Test-Path "cookies.txt")) {
    Write-Host "[warn] 缺 cookies.txt（IG 登入態）：從瀏覽器匯出 Netscape 格式，參考 cookies.txt.example"
}

# 煙霧測試
& $python -m pytest tests -q
Write-Host "init OK — 服務由 mission-control 管理（reels-summarizer, port 8001），不要在這裡手動常駐"
