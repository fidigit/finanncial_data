"""只读参考数据入口；与奖金模型分离，后续可替换为受控数据库查询。"""
import csv
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

DEFAULT_FILE = Path(__file__).resolve().parent.parent / '参考数据.csv'


@lru_cache(maxsize=2)
def _read_snapshot(path: str, modified: int, size: int):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if not columns or len(set(columns)) != len(columns):
            raise ValueError('表头为空或包含重复字段')
        rows = []
        for line, row in enumerate(reader, start=2):
            if None in row or None in row.values():
                raise ValueError(f'第 {line} 行列数与表头不一致')
            # Source line is the row identity: order numbers need not be unique.
            rows.append({'row_id': line, 'values': row})
    order_counts = Counter(r['values'].get('订单号', '') for r in rows if r['values'].get('订单号', ''))
    return columns, rows, sum(n - 1 for n in order_counts.values())


def query_reference(page=1, page_size=20, search='', quarter='', owner='', project='', ownership='', allowed_owner=None):
    path = Path(os.getenv('REFERENCE_CSV_PATH', str(DEFAULT_FILE)))
    if not path.is_file():
        raise HTTPException(404, '参考数据文件尚未配置，请将参考数据.csv放入项目目录或配置 REFERENCE_CSV_PATH')
    try:
        stat = path.stat()
        columns, rows, duplicates = _read_snapshot(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, UnicodeError, ValueError, csv.Error):
        raise HTTPException(422, '参考数据读取失败，请检查 UTF-8 CSV 的表头和各行列数')
    # Restrict before filters, pagination, dropdowns and counts, never in the browser.
    if allowed_owner is not None:
        rows = [r for r in rows if r['values'].get('BD姓名', '').strip() == allowed_owner]
        order_counts = Counter(r['values'].get('订单号', '') for r in rows if r['values'].get('订单号', ''))
        duplicates = sum(n - 1 for n in order_counts.values())
    options = {
        key: sorted({r['values'].get(field, '') for r in rows if r['values'].get(field, '')}, reverse=key == 'quarters')
        for key, field in [('quarters', '季度'), ('owners', 'BD姓名'), ('projects', '付费项目'), ('ownerships', '有/无归属BD')]
    }
    needle = search.strip().casefold()
    filtered = [row for row in rows if
                (not needle or any(needle in value.casefold() for value in row['values'].values()))
                and (not quarter or row['values'].get('季度') == quarter)
                and (not owner or row['values'].get('BD姓名') == owner)
                and (not project or row['values'].get('付费项目') == project)
                and (not ownership or row['values'].get('有/无归属BD') == ownership)]
    return {
        'columns': columns, 'rows': filtered[(page-1)*page_size:page*page_size],
        'total': len(filtered), 'source_total': len(rows), 'page': page, 'page_size': page_size,
        'source_name': path.name, 'duplicate_order_rows': duplicates,
        'options': options, 'mode': 'reference_snapshot',
    }
