param([int]$Port = 18080)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按 README 创建 .venv 并安装后端依赖。' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'dist/index.html'))) { throw '请先运行 pnpm install 和 pnpm build。' }
$env:DEMO_MODE = 'true'
Write-Host "本机演示地址：http://127.0.0.1:$Port；按 Ctrl+C 停止。"
& $pythonPath -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
