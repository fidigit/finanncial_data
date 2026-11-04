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
