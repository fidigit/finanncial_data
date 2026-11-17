"""Administrator-triggered source synchronization using server-only credentials."""
import json
import os
import threading
from pathlib import Path

import pymysql
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app import ROOT, app, admin, audit, database
from scripts.import_buss_snapshot import sync_snapshot

sync_lock=threading.Lock()


def connection_config():
    path=Path(os.getenv('BD_MYSQL_CONFIG_PATH',str(ROOT/'data/mysql-buss-connection.json')))
    try:
        config=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(config,dict) or not all(config.get(k) for k in ['host','port','username','database','password']):
            raise ValueError('incomplete configuration')
        if config.get('table')!='dws_marki_bill_detail_bd_quarter_buss_da':
            raise ValueError('unexpected table')
        return config
    except (OSError,ValueError,TypeError):
        raise HTTPException(503,'请在服务端配置data/mysql-buss-connection.json中的MySQL连接信息和密码') from None


@app.post('/api/source-sync/mysql')
def synchronize_mysql(user=Depends(admin),db:Session=Depends(database)):
    config=connection_config()
    if not sync_lock.acquire(blocking=False):
        raise HTTPException(409,'已有同步正在进行，请稍后刷新查看')
    try:
        result=sync_snapshot(config)
    except pymysql.MySQLError as exc:
        code=exc.args[0] if exc.args and isinstance(exc.args[0],int) else 'unknown'
        raise HTTPException(502,f'MySQL同步失败，错误码{code}，请检查网络、密码及读取权限') from None
    except (OSError,ValueError,KeyError,TypeError):
        raise HTTPException(502,'同步失败，请检查源表结构、数据和服务器文件权限') from None
    finally:
        sync_lock.release()
    from backend.reference_data import _read_snapshot
    _read_snapshot.cache_clear()
    audit(db,user.username,f'同步MySQL源表：{result["date"]}，{result["rows"]}行')
    db.commit()
    return {'ok':True,**result}
