# v0.0.7

季度营收目标支持增加和移除BD，自所选季度向后生效，历史季度保留。新增人员目标留空，后续沿袭遵守人员生效记录。

单笔是否计发提成支持选择是/否，沿用绿色/灰色标签。偏离公式结果时标记人工并在备注记录变化，选回公式结果清除覆盖及对应备注。销售表重新计算提点及奖金，独立人工奖金覆盖仍按已有优先级生效。市场表沿用现有人工确认模型。

拆分订单表、公共常数入口隐藏。Z入口保留。奖金方案只展示已保存项目，手动新增资格可留空。C订单号入口读取后台参考数据，提供搜索、分页和权限过滤。实际数据库连接待提供。

附带源头配置独立导入导出工具，默认补齐配置，导入前自动备份。业务配置包保存在部署机器，不随源码发布。

## 原目录更新

停止原服务后，在现有项目目录执行以下PowerShell命令。沿用服务器原有数据库、数据路径和连接凭证环境变量。

```powershell
Set-Location 'D:\finanncial_data'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv\Scripts\python.exe .\scripts\backup_state.py --output ".\backups\before-v007-$stamp"
if ($LASTEXITCODE -ne 0) { throw '备份失败' }
git fetch origin --tags
if ($LASTEXITCODE -ne 0) { throw '获取版本失败' }
git switch main
if ($LASTEXITCODE -ne 0) { throw '分支切换失败' }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw '代码更新失败' }
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
pnpm build
if ($LASTEXITCODE -ne 0) { throw '网页构建失败' }
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8787
```
