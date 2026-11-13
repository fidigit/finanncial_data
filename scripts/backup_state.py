"""Create a consistent local SQLite snapshot for an out-of-band server transfer."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def backup_state(source_db: Path, source_csv: Path, output: Path, source_samples: Path | None = None):
    if not source_db.is_file():
        raise ValueError('找不到SQLite数据库，请核对 --database 指向当前实际使用的数据库')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(source_db, timeout=30) as source:
        with sqlite3.connect(output / 'app.db') as destination:
            source.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('备份数据库完整性检查失败，禁止用于恢复')
    files = ['app.db']
    if source_csv.is_file():
        shutil.copy2(source_csv, output / '参考数据.csv')
        files.append('参考数据.csv')
    source_samples = source_samples or source_db.parent / 'sales-source-samples.json'
    if source_samples.is_file():
        (output / 'data').mkdir()
        shutil.copy2(source_samples, output / 'data/sales-source-samples.json')
        files.append('data/sales-source-samples.json')
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    hashes = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in files}
    (output / 'manifest.json').write_text(json.dumps({'version': 'v' + version, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': files, 'sha256': hashes, 'scope': 'private runtime data; never upload to GitHub'}, ensure_ascii=False, indent=2), encoding='utf-8')
    return files


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='备份本机SQLite状态与CSV，不上传任何文件')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/app.db')
    parser.add_argument('--csv', type=Path, default=Path(os.getenv('REFERENCE_CSV_PATH', str(ROOT / '参考数据.csv'))))
    parser.add_argument('--samples', type=Path, default=Path(os.getenv('BONUS_SOURCE_SAMPLES_PATH', str(ROOT / 'data/sales-source-samples.json'))))
    args = parser.parse_args()
    if os.getenv('DATABASE_URL', '').startswith('mysql'):
        parser.error('当前配置为MySQL，请使用README中的MySQL备份方法；此工具仅用于SQLite')
    result = backup_state(args.database, args.csv, args.output, args.samples)
    print('本地备份完成：' + str(args.output.resolve()))
    print('已包含：' + '、'.join(result))
    print('此目录包含账号与业务数据，请通过受控方式传输，不要提交到GitHub。')
