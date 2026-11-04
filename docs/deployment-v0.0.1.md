# v0.0.1 发布与另一台 Windows 服务器部署

仓库：<https://github.com/fidigit/finanncial_data>。版本：`v0.0.1`。

参考“马克埋点文档对话问答”项目的发布方法：代码提交到main、创建注释标签、推送后核对远端提交；服务器单独保管账号库、配置和业务文件。当前项目需要额外构建React前端，因此不能直接照抄另一个项目的 `pip install -e .`。

## 一、发布内容与数据边界

GitHub包含应用源码、依赖锁定文件、测试、版本记录和部署说明。`参考数据.csv`、`data/`、`backups/`、真实 `.env`、数据库和业务截图均被忽略。

现有中文BD账号、梁梓珊账号、密码哈希、个人主题、开关状态、服务计发规则、单笔确认及审计记录位于当前SQLite的 `data/app.db`。只克隆GitHub不会自动带上这些记录。测试使用临时生成的虚构CSV，不依赖真实导出文件。

## 二、先在原电脑导出运行数据

在本项目目录运行PowerShell（本地服务可以继续运行，工具用SQLite在线备份API生成一致快照）：

```powershell
cd 'D:\工作代码\AI用于商务人效分析'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv\Scripts\python.exe .\scripts\backup_state.py --output ".\backups\transfer-v0.0.1-$stamp"
if ($LASTEXITCODE -ne 0) { throw '运行数据备份失败，停止迁移' }
```

通过你可控的文件传输方式，将生成目录内的 `app.db`、`参考数据.csv`、`manifest.json` 放到新服务器的 `D:\financial-transfer-v0.0.1`。不要把这个目录上传GitHub。真实源库凭证另行在服务器环境变量中配置；如已使用自定义SQLite路径，备份命令须加 `--database 实际数据库路径`；MySQL场景使用README的MySQL备份恢复方法。

## 三、新服务器首次部署

前提：Windows服务器已安装Git、Python 3.12（`py -3.12`可用）、Node.js 22.12+与npm。下面选择 `D:\finanncial_data` 为新目录；若更改路径，后续 `cd` 同步更改。不要在已有部署目录重复克隆或覆盖原数据库。

```powershell
cd D:\
git clone https://github.com/fidigit/finanncial_data.git
if ($LASTEXITCODE -ne 0) { throw '克隆失败，请先完成GitHub登录或仓库授权' }
cd D:\finanncial_data
git switch --detach v0.0.1
if ($LASTEXITCODE -ne 0) { throw '切换版本失败' }

py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw '创建Python环境失败' }
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }

npm install --global pnpm@11.25.0
if ($LASTEXITCODE -ne 0) { throw '安装pnpm失败，请检查Node版本与安装权限' }
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
pnpm build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }

$transferDir = 'D:\financial-transfer-v0.0.1'
if (!(Test-Path -LiteralPath "$transferDir\app.db")) { throw '请先传输账号与业务数据库' }
if (!(Test-Path -LiteralPath "$transferDir\参考数据.csv")) { throw '请先传输参考数据CSV' }
New-Item -ItemType Directory -Path .\data -Force | Out-Null
if (Test-Path -LiteralPath '.\data\app.db') { throw '目标数据库已存在，禁止直接覆盖，请先备份核对' }
Copy-Item -LiteralPath "$transferDir\app.db" -Destination '.\data\app.db'
Copy-Item -LiteralPath "$transferDir\参考数据.csv" -Destination '.\参考数据.csv'

git describe --tags --exact-match HEAD
# 应输出 v0.0.1

$env:DEMO_MODE = 'true'
$dbFile = (Join-Path (Get-Location).Path 'data\app.db').Replace('\', '/')
$env:DATABASE_URL = "sqlite:///$dbFile"
$env:REFERENCE_CSV_PATH = Join-Path (Get-Location).Path '参考数据.csv'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 18080
```

这是复制当前基础版运行状态的部署方式。`DEMO_MODE=true` 与原数据库一致，因为库中仍有初始演示记录；它不会覆盖已有账号密码。不要直接切到false使用该混合演示库，正式模式会拒绝检测到演示数据的数据库。需要生产MySQL时按README用独立空库部署，并另行安排账号及已确认业务数据迁移。

保持服务终端运行，另一台电脑访问 `http://服务器局域网IP:18080`。必要时由服务器管理员在Windows防火墙放行TCP 18080。局域网以外访问应另行配置HTTPS反向代理与访问控制，不直接暴露演示环境到公网。

在另一PowerShell窗口验证：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/api/health
# status 为 ok，version 为 0.0.1
```

登录后检查现有9个业务账号、BD本人范围开关、参考数据行数、服务规则和单笔确认备注。MySQL/MaxCompute凭证不在仓库或数据库配置中，以服务器环境变量单独设置。

## 四、以后更新，保留账号和确认记录

先在原服务终端按Ctrl+C停止服务。在服务器项目目录执行，先备份，再切换到明确发布的标签；不执行清空数据卷、硬重置或删除运行数据。

```powershell
cd D:\finanncial_data
git status --short
# 若存在本机修改的源码，先核对，不要直接覆盖。

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv\Scripts\python.exe .\scripts\backup_state.py --output ".\backups\before-update-$stamp"
if ($LASTEXITCODE -ne 0) { throw '备份失败，停止更新' }

git fetch origin --tags
if ($LASTEXITCODE -ne 0) { throw '获取版本失败' }
git switch --detach v0.0.1
# 以后发布新版本时，将这里换成已存在的目标标签。
if ($LASTEXITCODE -ne 0) { throw '切换版本失败' }
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
pnpm build
if ($LASTEXITCODE -ne 0) { throw '构建失败，暂不启动' }
git describe --tags --exact-match HEAD

$env:DEMO_MODE = 'true'
$dbFile = (Join-Path (Get-Location).Path 'data\app.db').Replace('\', '/')
$env:DATABASE_URL = "sqlite:///$dbFile"
$env:REFERENCE_CSV_PATH = Join-Path (Get-Location).Path '参考数据.csv'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 18080
```

Git只更新代码，不会覆盖忽略的 `data/app.db`、CSV或配置；未来涉及数据库结构变更的版本，应遵守该版本迁移说明，不能仅靠切换标签代替迁移或恢复。

## 五、Docker / MySQL部署

仍可使用项目现有 `Dockerfile`、`compose.yaml`、`.env.example`；详见README。当前机器未提供Docker环境，首次镜像构建、实际MySQL和新服务器局域网访问仍需在目标机器验证。GitHub推送成功不等于已在另一台服务器部署。
