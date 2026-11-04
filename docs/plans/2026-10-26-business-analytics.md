# 商务数据分析网站 Implementation Plan

**Goal:** 根据 V1.0 需求交付可部署的网站基础版与后续开发设计，预留 MySQL、MaxCompute、多数据表接入。

**Architecture:** React/TypeScript/Ant Design 前端，FastAPI 服务端，SQLAlchemy 持久化。开发使用 SQLite，部署使用 MySQL；外部数据源与应用数据库分离。基础版不执行尚未确认的计奖规则。

**Tech Stack:** React、Vite、Ant Design、FastAPI、SQLAlchemy、PyMySQL、PyODPS、Docker Compose。

## 实施步骤

1. 编写系统设计：页面、权限、分层、数据模型、接入配置、计算及结算状态机、部署和验收边界。
2. 创建 API：登录、会话、服务端人员隔离、主题偏好、演示奖金查询及导出、数据源与数据集配置、审计。
3. 实现 MySQL / MaxCompute 连接测试和元数据读取；凭证只引用服务器环境变量，接口不回传凭证；仅管理员可调用。
4. 创建 Ant Design 工作台：总览、个人奖金、核算、规则、导入、异常、数据源与字段映射、系统设置。
5. 提供 Dockerfile、Compose、环境变量样例、初始化和备份恢复说明。
6. 验证类型及生产构建，测试越权、禁用账号、主题持久化、数据源配置校验、重复配置和未确认规则阻断。

## 本次交付边界

真实表结构、业务公式、实际数据库与服务器凭证未提供；演示数据明确标记。连接器具备真实连接测试与表元数据读取能力，多表接入配置可保存；同步调度、Excel生产导入、完整奖金计算及发放工作流在设计中明确为后续实现，不能宣称已验收。
