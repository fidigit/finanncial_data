param(
    [Parameter(Mandatory = $true)][string]$TransferDir,
    [ValidateRange(1, 65535)][int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$transferPath = (Resolve-Path -LiteralPath $TransferDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $transferPath 'manifest.json'))) { throw '迁移目录缺少manifest.json，请解压完整迁移包' }
if (Test-Path -LiteralPath (Join-Path $projectRoot 'data\app.db')) { throw '目标数据库已存在，停止首次恢复。已有部署请按文档原地升级，禁止覆盖账号库。' }
if (Test-Path -LiteralPath (Join-Path $projectRoot '参考数据.csv')) { throw '目标参考数据已存在，请核对后使用全新部署目录。' }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "端口$Port已占用，请停止旧服务或改用其他端口。" }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建Python3.12环境失败，请先安装Python3.12及py启动器' }
}
& $pythonPath -m pip install -r .\backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    npm install --global pnpm@11.25.0
    if ($LASTEXITCODE -ne 0) { throw '安装pnpm失败，请检查Node.js和npm环境' }
}
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
pnpm build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
& $pythonPath .\scripts\restore_state.py --input $transferPath
if ($LASTEXITCODE -ne 0) { throw '迁移包校验或恢复失败，禁止启动空账号库' }
$env:DEMO_MODE = 'true'
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $projectRoot 'data\app.db').Replace('\', '/')
$env:REFERENCE_CSV_PATH = Join-Path $projectRoot '参考数据.csv'
$env:BONUS_SOURCE_SAMPLES_PATH = Join-Path $projectRoot 'data\sales-source-samples.json'
Write-Host "已恢复现有账号、查询数据及配置。访问：http://服务器IP:$Port；按Ctrl+C停止。"
& $pythonPath -m uvicorn backend.app:app --host 0.0.0.0 --port $Port
if ($LASTEXITCODE -ne 0) { throw '服务退出，请检查上方启动错误' }
