# 一鍵恢復可開發、可驗證狀態（全新 clone 或換機後跑這支）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "已建立 venv"
}

.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -q pytest pytest-asyncio

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️ 已建立 .env，請填入 TELEGRAM_BOT_TOKEN 等密鑰（存在密碼管理器）"
}
if (-not (Test-Path "cookies.txt")) {
    Write-Host "⚠️ 缺 cookies.txt（IG 登入態）：從瀏覽器匯出 Netscape 格式，參考 cookies.txt.example"
}

# 煙霧測試
.\.venv\Scripts\python.exe -m pytest tests -q
Write-Host "init OK — 服務由 mission-control 管理（reels-summarizer, port 8001），不要在這裡手動常駐"
