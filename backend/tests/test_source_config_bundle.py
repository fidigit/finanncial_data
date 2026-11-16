import json
import sqlite3
from pathlib import Path

import pytest

from scripts.source_config_bundle import (
    CONSTANTS, DEFAULTS, TARGETS, export_bundle, import_bundle, load_bundle,
)


def settings_db(path, settings=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE system_settings(key TEXT PRIMARY KEY,value TEXT,version INTEGER)')
        db.execute('CREATE TABLE users(name TEXT,password TEXT,active INTEGER)')
        db.execute("INSERT INTO users VALUES ('原有账号','original-password-hash',1)")
        db.execute('CREATE TABLE data_sources(name TEXT,config TEXT)')
        db.execute("INSERT INTO data_sources VALUES ('mysql','original-query-config')")
        for key, value in (settings or {}).items():
            db.execute('INSERT INTO system_settings VALUES (?,?,7)', (key, json.dumps(value)))


def db_settings(path):
    with sqlite3.connect(path) as db:
        return {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM system_settings')}


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('BONUS_SOURCE_SAMPLES_PATH', raising=False)
    sources = {kind: {'sheet':kind,'columns':[],'rows':[]} for kind in ['splits','targets','services','orders','segmentation']}
    sources['targets']['rows'] = [{'BD姓名':'甲','季度':'2026Q3','直接营收目标':'100000'}]
    sources['services']['rows'] = [{'所购服务':'收费系统户数','是否计入提成范围':'是'}]
    sources['splits']['rows'] = [{'订单号':'OLD-1','BD姓名':'甲','分摊金额':100}]
    samples = tmp_path / 'samples.json'
    samples.write_text(json.dumps(sources), encoding='utf-8')
    source_db = tmp_path / 'source.db'
    settings_db(source_db, {'unrelated_account_setting': {'keep':True}})
    output = tmp_path / 'bundle'
    export_bundle(source_db, samples, output)
    return output / 'source-config.json'


def test_missing_sources_import_without_touching_accounts_queries_or_notes(tmp_path, bundle):
    project = tmp_path / 'server'
    database = project / 'data/app.db'
    keep = {'commission-note-test': {'note':'原有备注'}, 'bd_categories': {'甲':'sales'}}
    settings_db(database, keep)
    before = database.read_bytes()
    preview = import_bundle(bundle, project)
    assert preview['settings_changed'] == 4
    assert database.read_bytes() == before
    assert not (project / 'backups').exists()
    applied = import_bundle(bundle, project, apply=True)
    assert Path(applied['backup'], 'app.db').is_file()
    values = db_settings(database)
    assert all(values[key] == value for key, value in keep.items())
    assert values[CONSTANTS] == DEFAULTS
    assert values[TARGETS]['rows'][0]['直接营收目标'] == '100000'
    assert (project / 'data/sales-source-samples.json').is_file()
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT * FROM users').fetchall() == [('原有账号','original-password-hash',1)]
        assert db.execute('SELECT * FROM data_sources').fetchall() == [('mysql','original-query-config')]
    assert not import_bundle(bundle, project, apply=True)['settings_changed']
    assert not import_bundle(bundle, project)['samples_changed']


def test_conflicts_keep_server_values_but_fill_missing_fields(tmp_path, bundle):
    project = tmp_path / 'server'
    database = project / 'data/app.db'
    settings_db(database, {CONSTANTS:{'vip_minimum':'2000'}, TARGETS:{'rows':[
        {'BD姓名':'甲','季度':'2026Q3','直接营收目标':'999999'},
        {'BD姓名':'乙','季度':'2026Q4','直接营收目标':'555555'}]}})
    samples = project / 'data/sales-source-samples.json'
    samples.write_text(json.dumps({'splits': {'columns':[], 'rows':[
        {'订单号':'OLD-1','BD姓名':'甲','分摊金额':900}]}}), encoding='utf-8')
    import_bundle(bundle, project, apply=True)
    result = db_settings(database)
    assert result[CONSTANTS]['vip_minimum'] == '2000'
    assert result[CONSTANTS]['threshold'] == '30000'
    assert result[TARGETS]['rows'][0]['直接营收目标'] == '999999'
    assert len(result[TARGETS]['rows']) == 2
    assert json.loads(samples.read_text(encoding='utf-8'))['splits']['rows'][0]['分摊金额'] == 900
    import_bundle(bundle, project, apply=True, prefer_package=True)
    result = db_settings(database)
    assert result[CONSTANTS]['vip_minimum'] == '1680'
    assert result[TARGETS]['rows'][0]['直接营收目标'] == '100000'
    assert len(result[TARGETS]['rows']) == 2
    assert json.loads(samples.read_text(encoding='utf-8'))['splits']['rows'][0]['分摊金额'] == 100


def test_invalid_checksum_and_disallowed_setting_cannot_write(tmp_path, bundle):
    import hashlib
    from scripts.source_config_bundle import canonical
    value = json.loads(bundle.read_text(encoding='utf-8'))
    value['payload']['settings']['bd_categories'] = {'甲':'market'}
    bundle.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='SHA256'):
        load_bundle(bundle)
    value['sha256'] = hashlib.sha256(canonical(value['payload'])).hexdigest()
    bundle.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='不允许'):
        load_bundle(bundle)
    assert not (tmp_path / 'nonexistent').exists()


def test_wrong_database_env_is_rejected(tmp_path, bundle, monkeypatch):
    project = tmp_path / 'server'
    settings_db(project / 'data/app.db')
    monkeypatch.setenv('DATABASE_URL','mysql+pymysql://example/database')
    with pytest.raises(ValueError, match='DATABASE_URL'):
        import_bundle(bundle, project, apply=True)
    assert not (project / 'backups').exists()


def test_custom_preview_path_must_be_unified(tmp_path, bundle, monkeypatch):
    project = tmp_path / 'server'
    settings_db(project / 'data/app.db')
    monkeypatch.setenv('BONUS_SOURCE_SAMPLES_PATH',str(tmp_path / 'elsewhere.json'))
    with pytest.raises(ValueError, match='BONUS_SOURCE_SAMPLES_PATH'):
        import_bundle(bundle, project, apply=True)


def test_rolled_back_on_destination_version_change(tmp_path, bundle, monkeypatch):
    import scripts.source_config_bundle as module
    project = tmp_path / 'server'
    database = project / 'data/app.db'
    settings_db(database, {CONSTANTS:{'vip_minimum':'2000'}})
    original_read_db = module.read_db
    count = 0
    def race(path):
        nonlocal count
        count += 1
        if count == 2:
            with sqlite3.connect(database) as db:
                db.execute('UPDATE system_settings SET version=8 WHERE key=?',(CONSTANTS,))
        return original_read_db(path)
    monkeypatch.setattr(module, 'read_db', race)
    with pytest.raises(ValueError, match='其他用户修改'):
        import_bundle(bundle, project, apply=True)
    assert set(db_settings(database)) == {CONSTANTS}
    assert not (project / 'data/sales-source-samples.json').exists()
