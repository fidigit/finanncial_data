"""Verify and restore a private transfer bundle into a fresh deployment. Never overwrite."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESTINATIONS = {'app.db': 'data/app.db', '参考数据.csv': '参考数据.csv', 'data/sales-source-samples.json': 'data/sales-source-samples.json'}


def restore_state(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    files = manifest.get('files', [])
    if not {'app.db', '参考数据.csv'}.issubset(files) or len(files) != len(set(files)) or set(files) - set(DESTINATIONS):
        raise ValueError('迁移包必须包含数据库和参考数据CSV，且不能包含未知路径')
    for name in files:
        item = source / name
        target = destination / DESTINATIONS[name]
        if item.is_symlink() or not item.is_file():
            raise ValueError('迁移包文件缺失或为链接：' + name)
        expected = manifest.get('sha256', {}).get(name)
        if not expected or hashlib.sha256(item.read_bytes()).hexdigest() != expected:
            raise ValueError('文件SHA256校验失败：' + name)
        if target.exists():
            raise FileExistsError('目标已存在，拒绝覆盖：' + str(target))
    with sqlite3.connect((source / 'app.db').as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('迁移数据库完整性检查失败')
    for name in files:
        target = destination / DESTINATIONS[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create also protects against another process creating the target after validation.
        with (source / name).open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    return [DESTINATIONS[name] for name in files]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--project', type=Path, default=ROOT)
    args = parser.parse_args()
    restored = restore_state(args.input, args.project)
    print('校验及恢复完成：' + '、'.join(restored))
    print('已有账号、规则、查询配置及状态已随数据库保留；请另行配置源数据库凭证环境变量。')
