# v0.0.9

销售和市场表的刷新明细改为同步最新数据。管理员点击后读取MySQL目标表最新dt完整分区，按id排序写入本机快照，成功后刷新奖金表。同步过程中按钮显示加载状态。服务端只允许管理员调用，全量同步对所有使用者生效。失败保留原数据，不返回连接密码。

## 服务器配置

项目位于D:\finanncial_data时，配置文件为D:\finanncial_data\data\mysql-buss-connection.json。在服务器原项目目录执行：

```powershell
New-Item -ItemType Directory -Path .\data -Force | Out-Null
if (!(Test-Path .\data\mysql-buss-connection.json)) {
    Copy-Item .\scripts\mysql-buss-connection.example.json .\data\mysql-buss-connection.json
}
notepad .\data\mysql-buss-connection.json
```

在password双引号内填写MySQL密码。JSON字符串中的反斜杠写为两个反斜杠，双引号用反斜杠转义。默认主机10.130.87.26，端口10130，库hiido_report，用户名sodadev_o，表dws_marki_bill_detail_bd_quarter_buss_da。配置修改后下一次同步直接读取，无需重启。

密码以明文保存在服务器配置文件，仅授予服务运行账号及必要管理员文件权限。data目录已被Git忽略，实际密码和业务快照不会发布。也可用BD_MYSQL_CONFIG_PATH指定其他文件位置。MySQL账号需要目标表SELECT权限及服务器网络访问权限。

同步结果位于data/mysql-buss-reference.csv。REFERENCE_CSV_PATH若未配置或仍指向项目根目录参考数据.csv，同步成功后使用MySQL快照；若使用了其他自定义路径，请将其改为项目data/mysql-buss-reference.csv。

版本升级按原目录更新代码、安装依赖、构建前端、重启服务执行。首次填写密码后点击同步最新数据。密码配置不通过浏览器提交或回传。
