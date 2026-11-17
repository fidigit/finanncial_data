"""Read the latest MySQL partition into a local website snapshot."""
import csv
import getpass
import json
import os
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


def main():
    password = getpass.getpass('MySQL password: ')
    connection = pymysql.connect(host='10.130.87.26',port=10130,user='sodadev_o',
        password=password,database='hiido_report',connect_timeout=8,read_timeout=120,
        cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    password = None
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
        target=ROOT/'data/mysql-buss-reference.csv'
        temporary=target.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(FIELDS))
            writer.writeheader()
            for row in records:
                writer.writerow({name:'' if row.get(field) is None else str(row[field]) for name,field in FIELDS.items()})
        os.replace(temporary,target)
        (ROOT/'data/mysql-buss-snapshot.json').write_text(json.dumps({'date':str(dt),'rows':len(records),'table':'hiido_report.dws_marki_bill_detail_bd_quarter_buss_da'},ensure_ascii=False),encoding='utf-8')
        print(f'PASS: {len(records)} rows, dt={dt}. Snapshot saved: {target}')
    finally:
        connection.close()


if __name__=='__main__':
    try:
        main()
    except pymysql.MySQLError as error:
        print('FAIL: MySQL error code',error.args[0])
