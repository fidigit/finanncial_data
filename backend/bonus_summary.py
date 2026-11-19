"""Quarterly figures used by the first worksheet of a unified bonus export."""
import re
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from xml.etree import ElementTree as ET

from backend.bonus_rules import setting_payload
from backend.sales_formulas import decimal, effective_target, global_parameters

SUMMARY_NAME = '奖金汇总表'
SUMMARY_TITLE = '一、奖金汇总表'
ADJUSTMENTS_KEY = 'bonus_summary_workbook_inputs'
CENT = Decimal('0.01')
ZERO = Decimal(0)
GROUPS = ['工号', '姓名', '岗位性质', '销售奖金部分/元', '', '', '', '会议奖金部分/元', '', '', '', '',
          '其他调整项-日常工作', '其他调整项-退款扣减/补发', '应发奖金合计']
FIELDS = ['', '', '', '直接营收目标', '实际达成', '完成率', '提成奖金', '有效会议目标',
          '实际会议', '有效专场会议', '有效参会会议', '会议奖金', '', '', '']
WIDTHS = (10, 10, 12.34, 15.22, 15, 10.44, 14, 12.55, 12.11, 13.11, 12.44, 13.34, 14.45, 15.34, 17.85)


def meeting_quarter(value):
    return f'{value[:4]}Q{(int(value[5:7])-1)//3+1}'


def valid_quarter(value):
    return re.fullmatch(r'\d{4}Q[1-4]', value or '') is not None


def number(value):
    return decimal(value) or ZERO


def completion(actual, target):
    return actual / target if target else ZERO


def sheet_row(label):
    return [label] + [''] * 14


def build_summary(data, settings, configured_targets):
    memberships = setting_payload(settings, 'bd_categories')
    inputs = setting_payload(settings, ADJUSTMENTS_KEY)
    adjustments = {(r['owner'], r['quarter']): r for r in inputs.get('rows', [])}
    employee_nos = dict(inputs.get('employee_nos', {}))
    entries = defaultdict(lambda: {'sales': [], 'market': [], 'meetings': []})
    for kind in ('sales', 'market', 'meetings'):
        for row in data[kind]:
            quarter = meeting_quarter(row['meeting_date']) if kind == 'meetings' else row['quarter']
            name = row['owner'].strip()
            if valid_quarter(quarter) and name:
                entries[(quarter, name)][kind].append(row)
                if row.get('employee_no'):
                    employee_nos[name] = row['employee_no']
    for row in configured_targets:
        name, quarter = row['BD姓名'], row['季度']
        if valid_quarter(quarter) and memberships.get(name) in ('sales', 'market'):
            entries[(quarter, name)]
    threshold = number(global_parameters(settings)['threshold'])
    periods = defaultdict(list)
    for (quarter, name), records in entries.items():
        kind = memberships.get(name)
        if records['sales']:
            kind = 'sales'
        elif records['market']:
            kind = 'market'
        commission = records[kind] if kind in ('sales', 'market') else []
        target = decimal(effective_target(settings, name, quarter))
        actual = sum((number(r['bonus_basis']) for r in commission
                      if kind == 'sales' or r.get('calculation', {}).get('channel') == '直接营收'), ZERO)
        rate = completion(actual, target)
        bonus = sum((number(r['bonus']) for r in commission), ZERO)
        if kind == 'sales' and actual < threshold:
            bonus = ZERO
        meetings = records['meetings']
        special = sum(r['qualified'] is True and r['meeting_type'] == '专场会议' for r in meetings)
        attendance = sum(r['qualified'] is True and r['meeting_type'] == '参会会议' for r in meetings)
        eligible = (kind == 'sales' and rate >= 1) or (kind == 'market' and special + attendance >= 3)
        meeting_bonus = special * 1000 + attendance * 500 if eligible else 0
        row_inputs = adjustments.get((name, quarter), {})
        meeting_target = row_inputs.get('meeting_target', 6 if kind == 'market' else 0 if kind == 'sales' else '')
        daily = decimal(row_inputs.get('daily'))
        correction = decimal(row_inputs.get('correction'))
        total = (bonus + meeting_bonus + number(daily) + number(correction)).quantize(CENT, rounding=ROUND_DOWN)
        periods[quarter].append([
            employee_nos.get(name, ''), name, {'sales':'销售', 'market':'市场'}.get(kind, ''),
            target if target is not None else '', actual, rate, bonus, meeting_target,
            len(meetings), special, attendance, meeting_bonus,
            daily if daily is not None else '', correction if correction is not None else '', total,
        ])
    output = [sheet_row(SUMMARY_TITLE)]
    if not periods:
        return output + [sheet_row('暂无可汇总记录')]
    for quarter in sorted(periods, reverse=True):
        if len(output) > 1:
            output.append(sheet_row(''))
        rows = sorted(periods[quarter], key=lambda row: ({'销售':0, '市场':1}.get(row[2], 2), row[1]))
        total = ['团队合计', '', ''] + [sum((number(row[col]) for row in rows), ZERO) for col in range(3, 15)]
        total[5] = completion(total[4], total[3])
        output.extend([sheet_row('统计周期：' + quarter), GROUPS, FIELDS, *rows, total])
    return output


def style_summary_sheet(root, sheet_data, values, tag):
    """Apply the source workbook layout to each quarterly block."""
    cols = ET.Element(tag('cols'))
    for col, width in enumerate(WIDTHS, 1):
        ET.SubElement(cols, tag('col'), {'min': str(col), 'max': str(col), 'width': str(width), 'customWidth': '1'})
    root.insert(list(root).index(sheet_data), cols)
    merges = ET.Element(tag('mergeCells'))
    for index, (row, value) in enumerate(zip(sheet_data, values, strict=True), 1):
        label = value[0]
        styles = [6] * 15
        height = 18
        if label == SUMMARY_TITLE or str(label).startswith('统计周期：'):
            styles = [4] + [0] * 14
            height = 22.95 if label == SUMMARY_TITLE else 18
        elif value == GROUPS:
            styles = [5] * 15
            styles[13] = 12
            height = 21.6
            ranges = [f'{col}{index}:{col}{index+1}' for col in 'ABCMNO']
            ranges.extend([f'D{index}:G{index}', f'H{index}:L{index}'])
            for ref in ranges:
                ET.SubElement(merges, tag('mergeCell'), {'ref': ref})
        elif value == FIELDS:
            styles = [5] * 15
            styles[3] = styles[7] = 12
            height = 19.2
        elif label == '团队合计':
            styles = [5, 5, 5, 10, 10, 11, 10, 5, 5, 5, 5, 10, 10, 10, 10]
            ET.SubElement(merges, tag('mergeCell'), {'ref': f'A{index}:C{index}'})
        elif value[1]:
            styles = [6, 6, 6, 7, 7, 9, 8, 6, 6, 6, 6, 8, 7, 7, 8]
        else:
            styles = [0] * 15
        row.set('r', str(index))
        row.set('ht', str(height))
        row.set('customHeight', '1')
        for col, cell in enumerate(row, 1):
            cell.set('r', chr(64 + col) + str(index))
            cell.set('s', str(styles[col-1]))
            if cell.get('t') == 'n':
                val = cell.find(tag('v'))
                val.text = format(Decimal(val.text), '.15g')
    views = root.find(tag('sheetViews'))
    if views is not None:
        root.remove(views)
    if len(merges):
        merges.set('count', str(len(merges)))
    return merges


def add_summary_styles(styles, tag):
    root = ET.fromstring(styles)
    formats = ET.Element(tag('numFmts'), {'count':'1'})
    ET.SubElement(formats, tag('numFmt'), {'numFmtId':'164', 'formatCode':'0.0%'})
    root.insert(0, formats)
    fonts = root.find(tag('fonts'))
    for bold, color in [(False, 'FF000000'), (True, 'FF000000'), (True, 'FFC00000'), (True, 'FFFF0000')]:
        font = ET.SubElement(fonts, tag('font'))
        if bold:
            ET.SubElement(font, tag('b'))
        ET.SubElement(font, tag('sz'), {'val':'10'})
        ET.SubElement(font, tag('color'), {'rgb':color})
        ET.SubElement(font, tag('name'), {'val':'微软雅黑'})
    fonts.set('count', str(len(fonts)))
    fills = root.find(tag('fills'))
    fill = ET.SubElement(fills, tag('fill'))
    pattern = ET.SubElement(fill, tag('patternFill'), {'patternType':'solid'})
    ET.SubElement(pattern, tag('fgColor'), {'rgb':'FFD9E2F3'})
    ET.SubElement(pattern, tag('bgColor'), {'indexed':'64'})
    fills.set('count', str(len(fills)))
    borders = root.find(tag('borders'))
    border = ET.SubElement(borders, tag('border'))
    for side in ('left','right','top','bottom'):
        edge = ET.SubElement(border, tag(side), {'style':'thin'})
        ET.SubElement(edge, tag('color'), {'auto':'1'})
    borders.set('count', str(len(borders)))
    xfs = root.find(tag('cellXfs'))
    for font, fill, border, fmt, alignment in [
        (4,0,0,0,'left'), (3,2,1,0,'center'), (2,0,1,0,'center'),
        (2,0,1,4,'center'), (2,2,1,4,'center'), (2,0,1,164,'center'),
        (3,2,1,4,'center'), (3,2,1,164,'center'), (5,2,1,0,'center'),
    ]:
        xf = ET.SubElement(xfs, tag('xf'), {'numFmtId':str(fmt), 'fontId':str(font), 'fillId':str(fill),
            'borderId':str(border), 'xfId':'0', 'applyAlignment':'1', 'applyNumberFormat':'1', 'applyProtection':'1'})
        ET.SubElement(xf, tag('alignment'), {'horizontal':alignment,'vertical':'center','wrapText':'1'})
        ET.SubElement(xf, tag('protection'), {'locked':'1'})
    xfs.set('count', str(len(xfs)))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
