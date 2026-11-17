"""Read the latest MySQL partition into a local website snapshot."""
import csv
import getpass
import json
import os
import tempfile
from pathlib import Path
import pymysql

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {'季度':'pay_quarter','BD姓名':'buss_name','付款户名':'pay_account_name',
          '付费时间':'pay_time','付费项目':'service_name','首购/续费':'is_renew',
          '订单金额':'amount','订单号':'order_id','业务id信息':'id_info',
          '订单来源':'custom_from','订单来源补充':'custom_from_diy','有/无归属BD':'is_belong',
          '直接/间接收入':'bill_type','运营姓名':'op_name','支付方式':'pay_method',
          '营收金额':'sales_share_amt','奖金比例':'sales_ratio','奖金金额':'bonus_amt',
          '_source_id':'id','_share_amount':'sales_share_amt','_market_name':'name'}


def sync_snapshot(config, root=ROOT):
    connection = pymysql.connect(host=config['host'],port=int(config['port']),user=config['username'],
        password=config['password'],database=config['database'],connect_timeout=8,read_timeout=120,
        cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT MAX(dt) AS dt FROM dws_marki_bill_detail_bd_quarter_buss_da')
            dt=cursor.fetchone()['dt']
            if dt is None:
                raise ValueError('Source has no latest date')
            cursor.execute('SELECT * FROM dws_marki_bill_detail_bd_quarter_buss_da WHERE dt=%s ORDER BY id',(dt,))
            records=cursor.fetchall()
        ids=[str(r['id']) for r in records]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate source id within latest date; import stopped')
        if not records:
            raise ValueError('Empty source; import stopped')
        required=set(FIELDS.values())
        if any(not required.issubset(row) for row in records):
            raise ValueError('Source columns missing; import stopped')
        target=root/'data/mysql-buss-reference.csv'
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8-sig',newline='',dir=target.parent,
                                             prefix='mysql-buss-',suffix='.tmp',delete=False) as stream:
                temporary=Path(stream.name)
                writer=csv.DictWriter(stream,fieldnames=list(FIELDS))
                writer.writeheader()
                for row in records:
                    writer.writerow({name:'' if row.get(field) is None else str(row[field]) for name,field in FIELDS.items()})
            os.replace(temporary,target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {'date':str(dt),'rows':len(records),'table':'dws_marki_bill_detail_bd_quarter_buss_da'}
    finally:
        connection.close()


def main():
    password=getpass.getpass('MySQL password: ')
    result=sync_snapshot({'host':'10.130.87.26','port':10130,'username':'sodadev_o',
                          'database':'hiido_report','password':password})
    print(f'PASS: {result["rows"]} rows, dt={result["date"]}.')


if __name__=='__main__':
    try:
        main()
    except pymysql.MySQLError as error:
        print('FAIL: MySQL error code',error.args[0])
