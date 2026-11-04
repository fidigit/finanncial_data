# 商务数据分析网站 v0.0.1

根据《BD奖金计算与查询系统_最终需求文档_V1.0.md》实现的系统设计与可运行基础版。

发布版本：`v0.0.1`。仓库：[fidigit/finanncial_data](https://github.com/fidigit/finanncial_data)。

跨机器Windows部署及数据保留操作：[v0.0.1部署手册](docs/deployment-v0.0.1.md)。

- 设计：[商务数据分析网站_系统设计_V1.0.md](docs/商务数据分析网站_系统设计_V1.0.md)
- 栈：React + TypeScript + Ant Design / FastAPI / SQLAlchemy
- 部署：Docker Compose + MySQL；开发演示可用 SQLite
- 数据源：MySQL、MaxCompute，预留多表和字段映射。

## 当前能力与边界

已实现账号登录与停用、服务端本人数据隔离、演示奖金查询/详情/CSV导出、5套主题按账号保存、数据源配置/真实探测/元数据、数据集映射草稿及基础审计。

**当前不是完整可投产的奖金系统**：真实计奖口径、Excel生产导入、同步调度、规则引擎、确认结算、人工调整和真实发放流水尚未实现。页面标明演示或待开放；真实试算接口明确拒绝执行。MySQL/MaxCompute 连接器尚未用业务账号实测。真实源表接入前必须完成字段、归属与财务样例确认。

## 本机运行

需要 Node.js 22.12+（或兼容版本）、pnpm 11.25、Python 3.12。PowerShell：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
pnpm install --frozen-lockfile
pnpm build
./scripts/start-local.ps1
```

浏览器访问 http://127.0.0.1:18080 。演示账号：`admin`、`bd.lin`、`bd.zhou`，密码均为 `Demo2026!`。仅用于隔离的演示环境，不用于正式业务。

当前机器已创建 `.venv` 和安装依赖，可以直接运行启动脚本。若全局 `pnpm` 不在 PATH，可使用本机 Codex 随附的 `C:/Users/JOYY/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd`。

开发热更新：后端运行 `.venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 18080`，前端另开终端 `pnpm dev`，访问其输出地址。生产构建无需前端开发服务器。

开发模式默认 `DEMO_MODE=true`，数据库在 `data/app.db`。正式数据库必须独立，禁止在演示数据库直接切换模式；正式启动会拒绝已知演示账号或演示奖金记录。

## 局域网部署

服务器安装 Docker Engine / Compose（Linux）或适用的 Docker Desktop（Windows），在项目目录执行：

```powershell
Copy-Item .env.example .env
# 编辑 .env，设置各自独立的强密码、数据库连接和真实凭证引用。
docker compose up -d --build
docker compose ps
```

访问 `http://服务器局域网IP:8080`，首个管理员账号 `admin`，初始密码来自 `ADMIN_PASSWORD`（至少12位）。没有默认正式BD账号，也没有正式奖金数据。通过系统设置创建人员账号。

配置说明：

1. `DATABASE_URL` 用于网站自身持久化，与“数据接入”中的外部业务库不同。数据库用户名、密码和库名须与 MySQL 配置一致；URL中用户名和密码的特殊字符要进行URL编码。
2. Compose 强制 `DEMO_MODE=false`；默认仅应用端口暴露，MySQL不向局域网公开。
3. 局域网防火墙放行所选应用端口。按需加 Nginx / Caddy HTTPS 反向代理，开启 `COOKIE_SECURE=true`；随附 HTTP 示例适用于受控局域网演示。
4. 容器连接外部业务库时，`localhost` 指容器本身；填写服务器可访问的实际主机名或IP。
5. 容器和账号对数据库的权限、服务器到 MaxCompute 的网络与云 RAM 授权必须实际验证。
6. 首次启动使用初始建表，不自动迁移已有表。后续改表前引入版本迁移并备份。
7. 本机环境没有 Docker，Compose 镜像构建、MySQL联调和局域网访问尚未验证。

## 新增一个 MySQL 数据源

在服务器 `.env` 配置：

```dotenv
BD_ALLOWED_SOURCE_HOSTS=mysql-readonly.internal,实际MaxCompute主机名
BD_SOURCE_ORDER_MYSQL='{"username":"只读账号","password":"实际密码"}'
```

重启使环境生效：`docker compose up -d --force-recreate app`。管理员进入“数据接入”新增连接：名称、MySQL主机、端口、数据库，凭证引用填 `BD_SOURCE_ORDER_MYSQL`。然后“测试连接”“读取表结构”。

凭证JSON可按PyMySQL规范提供 `ssl` 配置及容器内CA路径；应结合实际服务器验证TLS。连接探测和元数据不会向源库写数据，但账号也应在数据库侧限制为只读。

## 新增一个 MaxCompute 数据源

```dotenv
BD_SOURCE_MAXCOMPUTE='{"access_id":"实际AccessKey ID","access_key":"实际AccessKey Secret"}'
```

在数据接入填实际 `Project`、HTTPS `Endpoint`，引用 `BD_SOURCE_MAXCOMPUTE`，并把 Endpoint 的主机名加入白名单。不要把示例地域或项目当真实配置。基础版使用PyODPS读取项目和表结构，不向浏览器返回密钥。生产建议采用最小RAM权限；STS自动刷新作为后续扩展。

## 以后新增数据表

### 业务总览参考表（已实现）

登录用户可在“业务总览”查看项目 `参考数据.csv`：保留全部原始字段、空值和重复订单号，支持全字段搜索、季度/BD/付费项目/归属筛选以及服务端分页。该表与演示奖金看板独立，源文件中的比例和奖金金额按原值展示，不重新计算。

超级管理员“梁梓珊”和指定账号 `admin` 可在“全部归属状态”和“重置”之间切换小开关。开启（默认）：BD仅查看“BD姓名”与本人姓名匹配的记录；关闭：BD可查看全部记录，包括无归属账单。管理员始终可查看全部。服务端在搜索、分页、选项、数量统计之前应用权限，前端每15秒检查策略变更；每次查询立即使用当前策略。开关状态持久保存，变更有审计日志，其他普通管理员和BD不能调用切换接口。这个开关仅影响业务参考表，其他奖金模块继续保留原有权限。

账号支持中文姓名。当前本机数据库已按用户要求创建8位BD账号和“梁梓珊”超级管理员；初始密码按用户指定的小写拼音设置，仅保存哈希，不在重启时重置密码。它们是本机数据库记录，部署新空数据库时需另行初始化业务账号，不因代码启动自动生成或覆盖。

所有用户通过“头像菜单 → 修改密码”验证原密码后修改，新密码至少8位、两次输入一致；成功后注销该账号全部设备会话，需要重新登录。密码不会出现在审计日志或用户列表中。

默认从项目根目录读取，也可用服务器环境变量 `REFERENCE_CSV_PATH` 指定文件。替换文件后点击表格“刷新数据”即可重新读取；源文件不被修改，也不被打包进前端静态资源。后续 MySQL 接入可替换该查询层，保持表格接口不变。

Docker 如需显示该 CSV，使用只读挂载（文件必须存在）：

```powershell
docker compose -f compose.yaml -f compose.reference.yaml up -d --build
```

### 首页BD提成确认表（2026-11-04新增）

位于原始参考表下方，使用分组表头展示订单信息、确认基数、确认提点、奖金、发放、退款及备注。付款公司优先取付款户名，否则取业务id信息；推荐类型从订单来源识别。新服务未设置计发规则时自动提醒，管理员可设置服务规则，并通过单笔“确认 / 修改”填写共享BD、分摊比例、基数、市场BD、确认提点、人工奖金、发放/退款及备注。

本表沿用参考数据权限开关，修改仅限管理员；规则和确认记录持久化并留审计，原CSV不变。累计营收口径和分段计提规则尚未确认，相关单元格明确显示待确认；人工确认不执行付款或自动结算。新接口位于 `/api/commission-data`。

### 数据集映射草稿

在“数据表与字段映射”新增数据集：选择连接、源表、目标模型、源唯一主键、人员归属字段、水位与分区约定，填写标准字段到源字段映射。目前保存为草稿，不拉取业务行，不产生奖金。

后续按设计实现同步任务，批准映射后将源数据同步到标准业务模型，并进行人员映射、质量校验、幂等合并与金额对账。不能把表名填完就认为完成财务数据接入。

## 备份与恢复

演示 SQLite：停止本地服务后备份 `data/app.db`；在独立目录复制数据库文件并用演示模式恢复核对。生产 MySQL 使用一致性逻辑备份，文件卷单独备份。以下为 Linux 服务器例子，凭证通过容器环境读取，避免出现在命令参数：

```bash
mkdir -p backups
umask 077
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u"$MYSQL_USER" --single-transaction --no-tablespaces "$MYSQL_DATABASE"' > backups/bd.sql
```

恢复前停止 `app`，目标必须是**独立测试库或已批准的恢复库**。下面的命令会把备份导入当前 Compose 指向的库，务必先核验目标：

```bash
docker compose stop app
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < backups/bd.sql
docker compose up -d app
```

恢复后检查健康接口、账号和主题、数据源/映射数量、奖金金额与日志。凭证环境文件另行限制权限和保管，勿放进公开备份。不要使用 `docker compose down -v` 作为日常更新命令，它会移除持久卷。

备份周期、保留时间及恢复目标待业务确认；以上为交付操作方案，生产恢复演练需在真实部署环境执行。

## 验证

```powershell
pnpm build
.venv/Scripts/python.exe -m pytest backend/tests -q
```

后端测试使用临时独立数据库，不修改演示库；覆盖跨人员访问、导出范围、停用、注销、主题、凭证边界、配置输入、规则阻断等关键行为。
