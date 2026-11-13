import sqlite3
from pathlib import Path

import pytest

from scripts.backup_state import backup_state


def test_backup_preserves_state_and_refuses_overwrite(tmp_path):
    source = tmp_path / 'source.db'
    csv_file = tmp_path / 'source.csv'
    csv_file.write_text('BD姓名\n测试人员\n', encoding='utf-8')
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE state (name TEXT, value TEXT)')
        db.execute('INSERT INTO state VALUES (?,?)', ('scope', 'self_only'))
    output = tmp_path / 'transfer'
    assert backup_state(source, csv_file, output) == ['app.db', '参考数据.csv']
    with sqlite3.connect(output / 'app.db') as db:
        assert db.execute('SELECT value FROM state WHERE name=?', ('scope',)).fetchone()[0] == 'self_only'
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert (output / '参考数据.csv').read_bytes() == csv_file.read_bytes()
    assert (output / 'manifest.json').is_file()
    with pytest.raises(FileExistsError):
        backup_state(source, csv_file, output)



def test_transfer_roundtrip_preserves_query_configuration_accounts_and_samples(tmp_path):
    import json
    from scripts.restore_state import restore_state
    source=tmp_path/'source'
    (source/'data').mkdir(parents=True)
    db_file=source/'data/app.db'
    with sqlite3.connect(db_file) as db:
        db.execute('create table state (name text, value text)')
        db.executemany('insert into state values (?,?)',[
            ('password_hash','unchanged-hash'),('saved_query','mysql-dataset-map'),
            ('annual_plan','2026'),('last_export','20261113-120000_v1')])
    csv_file=source/'参考数据.csv'
    csv_file.write_bytes('BD姓名,季度\n测试人员,2026Q4\n'.encode('utf-8-sig'))
    (source/'data/sales-source-samples.json').write_text('{"splits": {"rows": []}}',encoding='utf-8')
    bundle=tmp_path/'transfer'
    files=backup_state(db_file,csv_file,bundle)
    assert files==['app.db','参考数据.csv','data/sales-source-samples.json']
    manifest=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version']=='v0.0.6' and set(manifest['sha256'])==set(files)
    target=tmp_path/'deployment'
    restored=restore_state(bundle,target)
    assert 'data/app.db' in restored
    with sqlite3.connect(target/'data/app.db') as db:
        assert dict(db.execute('select name,value from state'))['password_hash']=='unchanged-hash'
        assert dict(db.execute('select name,value from state'))['saved_query']=='mysql-dataset-map'
    assert (target/'参考数据.csv').read_bytes()==csv_file.read_bytes()
    assert (target/'data/sales-source-samples.json').read_bytes()==(source/'data/sales-source-samples.json').read_bytes()
    with pytest.raises(FileExistsError):restore_state(bundle,target)
    (bundle/'参考数据.csv').write_text('tampered',encoding='utf-8')
    with pytest.raises(ValueError,match='SHA256'):restore_state(bundle,tmp_path/'invalid-target')
    assert not (tmp_path/'invalid-target/data/app.db').exists()


def test_restore_rejects_unknown_paths_and_missing_csv_before_writes(tmp_path):
    import json
    from scripts.restore_state import restore_state
    source=tmp_path/'source'
    source.mkdir()
    for files in [['app.db'],['app.db','参考数据.csv','../other']]:
        (source/'manifest.json').write_text(json.dumps({'files':files}),encoding='utf-8')
        with pytest.raises(ValueError):restore_state(source,tmp_path/'target')
        assert not (tmp_path/'target').exists()
