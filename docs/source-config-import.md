# 六类源头配置补齐（现有Windows部署）

此包只含源头配置与历史预览，不含账号、密码、账单CSV、连接密钥或整库文件。不改变应用版本，不要求更新GitHub，不创建带应用版本的新项目目录。

## 使用方式

先在原服务窗口Ctrl+C停止。将配置ZIP放入现有项目D:\finanncial_data，解压到项目data/source-config-import（Git忽略目录），再调用包内的import_source_config.py。脚本只依赖Python标准库；使用原项目.venv即可，不需要安装依赖。

预检：

```powershell
.\.venv\Scripts\python.exe .\data\source-config-import\import_source_config.py import --project .
```

补齐：

```powershell
.\.venv\Scripts\python.exe .\data\source-config-import\import_source_config.py import --project . --apply
```

默认以服务器已有配置为准，按BD+季度、服务名、常数名逐项补缺。显式追加--prefer-package才使用包内同名值；仍保留服务器额外的季度、服务、年份，不删除其他设置。导入前自动生成backups/source-config-时间戳，包含原数据库、原预览文件（若存在）和导入报告。不重置账号、不修改账单、备注、发放退款、查询连接和最后导出状态。

默认SQLite为项目data/app.db，可用--database指定真实路径；DATABASE_URL如不匹配则拒绝操作。MySQL应用状态库不适用此脚本。BONUS_SOURCE_SAMPLES_PATH如设置须指向当前项目data/sales-source-samples.json，以匹配当前预览接口。

导入后用原服务环境启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8787
```

管理员登录检查：拆分订单、C订单号、Z分段标识显示历史预览；季度目标按所选季度查看；方案按付款年份查看；公共常数与齿轮同步。历史预览不会自动套入实际订单。仅原本匹配订单的年度方案、季度目标和公共常数参与现有计算。若未来年份/季度没有配置，使用页面沿袭功能，不自动猜测目标。

完整性：配置内容有SHA256校验，设置键使用固定允许名单，正式写入使用事务和版本检查。校验、格式或并发检查失败会停止；预检不写入数据库、不创建备份。
