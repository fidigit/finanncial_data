# v0.0.2 升级说明

本地开发版本已更新。远端机器只有更新源码并重新构建、重启后才会使用新功能；本文件不表示v0.0.2已推送GitHub或已创建Git标签。

1. 停止现有服务并备份：在项目目录运行 `.\.venv\Scripts\python.exe .\scripts\backup_state.py --output ".\backups\before-v0.0.2-$(Get-Date -Format yyyyMMdd-HHmmss)"`。
2. 更新到包含v0.0.2变更的源码，保留 `data/app.db`、根目录 `参考数据.csv` 和部署环境配置。不要以空数据库替换现有数据库。
3. 运行 `pnpm install --frozen-lockfile` 和 `pnpm build`。后端没有新增第三方依赖。
4. 在原PowerShell会话用原DATABASE_URL和REFERENCE_CSV_PATH启动：`.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8787`。
5. 检查 `/api/health` 中 `version` 为 `0.0.2`，刷新浏览器。用admin或梁梓珊检查随机临时归类并按实际岗位调整。

启动时仅在不存在归类配置时随机初始化；每个独立数据库随机结果可能不同。需要保持另一台机器与本机一致时，应保留/迁移更新后的数据库，或者在归类器中手动指定。

会议表初始为空，请由管理员新增真实会议记录。暂未连接会议来源表，奖金和达标结果为人工确认，不会自动计发。
