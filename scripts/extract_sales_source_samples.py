"""Read the reference workbook and cache source previews locally; never changes workbook/state."""
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent

def extract(workbook, output):
    book = load_workbook(workbook, data_only=True, read_only=True)
    def value(v):
        return v.isoformat() if isinstance(v, (date, datetime)) else v
    data = {}
    sheet = book['数据源-市场+销售 拆分订单']
    rows = []
    for row in range(4, 31):
        order = sheet[f'J{row}'].value or sheet[f'A{row}'].value
        if not order:
            continue
        for col in range(2, 9):
            amount, total = sheet.cell(row, col).value, sheet[f'I{row}'].value
            if amount not in (None, 0):
                rows.append({'订单号': order, 'BD姓名': sheet.cell(3, col).value, '分摊金额': amount, '总计': total, '分摊比例': amount / total if total else None})
    data['splits'] = {'sheet': sheet.title, 'columns': ['订单号', 'BD姓名', '分摊金额', '总计', '分摊比例'], 'rows': rows}
    sheet = book['奖金汇总表']
    data['targets'] = {'sheet': sheet.title, 'columns': ['BD姓名', '季度', '直接营收目标'], 'rows': [{'BD姓名': sheet[f'B{r}'].value, '季度': '2026Q3', '直接营收目标': sheet[f'D{r}'].value} for r in range(5, 12) if sheet[f'B{r}'].value]}
    sheet = book['2025年奖金方案']
    data['services'] = {'sheet': sheet.title, 'columns': ['所购服务', '是否计入提成范围'], 'rows': [{'所购服务': sheet[f'A{r}'].value, '是否计入提成范围': sheet[f'B{r}'].value} for r in range(20, 97) if sheet[f'A{r}'].value]}
    sheet = book['1-1物业系统营收提成明细(销售)']
    columns = {'A': 'BD姓名', 'C': '订单号', 'D': '签约主体/付款主体', 'E': '客户付款时间', 'F': '所购服务', 'G': '新客/续费', 'H': '订单收款金额', 'L': '是否存在协会或合伙人推荐的情况？（是/否）', 'O': '是否渠道来自市场（如有提成，销售按8%）'}
    data['orders'] = {'sheet': sheet.title + ' · C订单号及关联输入', 'columns': list(columns.values()), 'rows': [{name: value(sheet[f'{col}{r}'].value) for col, name in columns.items()} for r in range(4, 14)]}
    data['segmentation'] = {'sheet': sheet.title + ' · Z是否适用分段计算', 'columns': ['BD姓名', '订单号', '是否适用分段计算'], 'rows': [{'BD姓名': sheet[f'A{r}'].value, '订单号': sheet[f'C{r}'].value, '是否适用分段计算': sheet[f'Z{r}'].value} for r in range(4, 14)]}
    book.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return {key: len(item['rows']) for key, item in data.items()}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', type=Path, default=ROOT / '重要文件' / '马克商务拓展组2026年Q3奖金表-1023（test）.xlsx')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'sales-source-samples.json')
    args = parser.parse_args()
    print(extract(args.workbook, args.output))
