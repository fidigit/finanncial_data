# v0.0.6 GitHub发布与保留运行数据的部署

仓库：https://github.com/fidigit/finanncial_data 。固定版本：v0.0.6。以下沿用当前Windows服务器/PowerShell环境，端口默认8787，也可传入其他空闲端口。

## 迁移内容

GitHub仅保存源码、依赖锁、测试与文档。独立运行数据包包含：

| 文件 | 用途 | 恢复位置 |
| --- | --- | --- |
| app.db | 现有账号、密码哈希、停用状态、角色权限、主题、BD归类、查询数据源/数据集映射、年度方案、季度目标、公共参数、备注、会议记录、发放/退款、最后导出版本及审计 | 项目/data/app.db |
| 参考数据.csv | 实际账单查询来源；必须原样保留，不能改行序或重新整理，否则来源行身份会改变 | 项目/参考数据.csv |
| data/sales-source-samples.json | 拆分订单、订单号及原表源头样例预览 | 项目/data/sales-source-samples.json |
| manifest.json | 版本、文件列表及SHA256校验 | 仅迁移校验使用 |

不要把数据库、CSV、数据包上传GitHub。MySQL/MaxCompute连接配置和数据集映射随数据库保留，但真实连接凭证来自服务器环境变量，须在新服务器单独设置BD_SOURCE_*、BD_ALLOWED_SOURCE_HOSTS等；恢复不会凭空生成这些密钥。已有账号原密码保持有效；同域浏览器登录会话是否可继续取决于Cookie，新IP通常需要重新登录。

## 原机器生成最新迁移包

若迁移前仍在修改数据，最后切换前再备份一次，并在切换时停止旧服务，防止新旧服务器各自写入产生分叉。

```powershell
cd 'D:\工作代码\AI用于商务人效分析'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$transfer = ".\backups\transfer-v0.0.6-$stamp"
.\.venv\Scripts\python.exe .\scripts\backup_state.py --database .\data\app.db --csv '.\参考数据.csv' --output $transfer
if ($LASTEXITCODE -ne 0) { throw '备份失败，请勿继续迁移' }
Compress-Archive -Path "$transfer\*" -DestinationPath "$transfer.zip"
```

SQLite备份API会生成一致快照，CSV及样例在复制时应保持不被修改。若Python虚拟环境不存在，先用已安装的Python3.12运行同一脚本；脚本仅依赖标准库。自定义数据库/CSV路径必须通过--database/--csv指定；MySQL库用数据库自身的备份恢复，不使用SQLite迁移脚本。

## 新服务器首次恢复：推荐使用全新目录

前提：Windows已安装Git、Python3.12（py -3.12可用）、Node.js22.12+和npm；可使用有权限的GitHub账号访问私有仓库。脚本会创建.venv、安装后端依赖、安装pnpm及按锁文件构建前端。不要从另一台电脑复制.venv或node_modules。

将本次生成的ZIP完整传到新服务器D盘。把下面的ZIP文件名换成实际传输的文件名；其他路径按需修改。

```powershell
$ErrorActionPreference = 'Stop'
$transferZip = 'D:\financial-transfer-v0.0.6.zip'
$transferDir = 'D:\financial-transfer-v0.0.6'
$projectDir = 'D:\finanncial_data_v0.0.6'
if (Test-Path -LiteralPath $transferDir) { throw '迁移解压目录已存在，请核对或换用新目录' }
if (Test-Path -LiteralPath $projectDir) { throw '项目目录已存在，请使用全新目录，勿覆盖已有账号库' }
Expand-Archive -LiteralPath $transferZip -DestinationPath $transferDir

git clone --branch v0.0.6 --depth 1 https://github.com/fidigit/finanncial_data.git $projectDir
if ($LASTEXITCODE -ne 0) { throw '克隆失败：请通过Git Credential Manager登录有该私有仓库权限的GitHub账号' }
Set-Location -LiteralPath $projectDir
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-windows.ps1 -TransferDir $transferDir -Port 8787
```

如使用原部署的8787端口，先在旧服务终端Ctrl+C停止旧服务；脚本会检测占用并停止部署，不会自动结束不明进程。

恢复脚本校验所有文件SHA256及数据库完整性，拒绝覆盖已存在的app.db或CSV。恢复布局是数据库在data中，CSV在项目根目录，不要都放进data后仍使用默认路径。

本次保留现有混合演示库，所以运行模式保持DEMO_MODE=true；这不会重置已存在账号。直接切false会因库中历史演示记录而被拒绝。已有生产空库/正式环境的部署请保留原模式及数据库配置，不套用此迁移脚本。

如需再次启动，项目目录运行：

```powershell
$env:DEMO_MODE = 'true'
$dbFile = (Join-Path (Get-Location).Path 'data\app.db').Replace('\', '/')
$env:DATABASE_URL = "sqlite:///$dbFile"
$env:REFERENCE_CSV_PATH = Join-Path (Get-Location).Path '参考数据.csv'
$env:BONUS_SOURCE_SAMPLES_PATH = Join-Path (Get-Location).Path 'data\sales-source-samples.json'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8787
```

另开PowerShell验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/health
# version应为0.0.6；浏览器访问http://服务器IP:8787
```

使用原账号密码登录，核对参考数据条数、BD归类、2026年方案、季度目标、备注和发放状态。若跨机器无法访问，检查服务器网络及TCP8787防火墙。外网部署请使用HTTPS反向代理并保管凭证，勿直接把演示服务暴露公网。

## 已有另一台服务器：只升级代码，保留那台机器自己的状态

若要保留目标服务器已经新增的账号、记录和查询数据，不要用本机迁移包覆盖它。先停止目标服务，备份该服务器自身app.db和CSV，检查git status无未处理源码修改，再执行：

```powershell
cd D:\finanncial_data
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv\Scripts\python.exe .\scripts\backup_state.py --output ".\backups\before-v006-$stamp"
if ($LASTEXITCODE -ne 0) { throw '备份失败' }
git fetch origin --tags
if ($LASTEXITCODE -ne 0) { throw '获取版本失败' }
git switch --detach v0.0.6
if ($LASTEXITCODE -ne 0) { throw '切换失败，请处理本地源码修改，勿强制覆盖' }
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
pnpm build
if ($LASTEXITCODE -ne 0) { throw '构建失败' }
# 使用前文的再次启动命令，保持该服务器实际数据库和CSV路径不变。
```

Git更新不会清空忽略的运行数据。若两台机器已独立修改业务数据，不能直接复制数据库来自动合并；应明确使用哪一份数据库作为最终状态。
