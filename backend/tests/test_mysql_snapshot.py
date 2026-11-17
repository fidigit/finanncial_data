import csv
import pytest
from scripts import import_buss_snapshot as importer


def test_snapshot_replaces_atomically_and_keeps_old_data_on_invalid_source(tmp_path,monkeypatch):
    record={key:None for key in importer.FIELDS.values()}
    record.update(id=1,buss_name='测试BD',amount='100',sales_share_amt='50',pay_quarter='2026Q4')
    records=[record]
    class Cursor:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,*args):pass
        def fetchone(self):return {'dt':'2026-11-16'}
        def fetchall(self):return records
    class Connection:
        def cursor(self):return Cursor()
        def close(self):pass
    monkeypatch.setattr(importer.pymysql,'connect',lambda **kwargs:Connection())
    config=dict(host='test',port=3306,username='test',password='secret',database='test')
    result=importer.sync_snapshot(config,tmp_path)
    assert result['rows']==1
    target=tmp_path/'data/mysql-buss-reference.csv'
    with target.open(encoding='utf-8-sig',newline='') as stream:
        row=next(csv.DictReader(stream))
    assert row['_share_amount']=='50' and row['订单金额']=='100' and row['_source_id']=='1'
    before=target.read_bytes()
    records.append(record)
    with pytest.raises(ValueError,match='Duplicate'):
        importer.sync_snapshot(config,tmp_path)
    assert target.read_bytes()==before
    records.clear()
    with pytest.raises(ValueError,match='Empty'):
        importer.sync_snapshot(config,tmp_path)
    assert target.read_bytes()==before
