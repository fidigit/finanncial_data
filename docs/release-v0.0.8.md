# v0.0.8

销售表输入入口仅显示奖金汇总表、奖金方案。拆分订单、订单号、分段标识和公共常数入口隐藏。

销售与市场XLSX导出在末尾T列增加订单id，共20列。网页保持19列。订单id按文本保存，使用深灰字体、无背景填充并锁定。Q/R仍只允许编辑是否发放、是否退款。所有20列均提供筛选，工作表保护允许使用现有筛选器。回传校验同步保护订单id。

包含已确认的数据接入更新：可交互输入密码读取hiido_report.dws_marki_bill_detail_bd_quarter_buss_da最新dt完整快照。账号密码不保存，数据快照位于被Git忽略的data目录。分摊按sales_share_amt/amount，按订单号和服务名识别共享。基数保留两位，市场来源影响销售提点。支持从相邻下一年向前沿袭奖金方案，默认表格按季度、BD姓名倒序，累计仍按付款时间计算。

原目录更新保留data/app.db与部署机器上的快照和配置。首次切换到该MySQL源头，须在部署机器执行scripts/import_buss_snapshot.py输入密码生成快照。服务的REFERENCE_CSV_PATH需指向data/mysql-buss-reference.csv，或不设置该变量以使用自动识别。仅更新源码不会带入另一台机器的业务快照。
