"""Bounded decimal expression language for five sales columns; no eval or exec."""
import ast
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from functools import lru_cache

class FormulaError(ValueError):
    pass

COMMON = {'A': 'BD姓名（文本）', 'C': '订单号（文本）', 'F': '所购服务（文本）',
          'G': '新客/续费（文本：首购、新客、续费）', 'H': '订单收款金额（元）'}
SPECS = {
    'S': {'title': '是否计发提成',
          'default': 'IF(所购服务 == "团队VIP", IF(订单金额 >= 团队VIP金额下限, 真, 假), 服务规则查询结果)',
          'result': '团队VIP按金额下限判断；其他服务查计提范围；缺失或异常显示Check（待配置）。单笔人工确认优先。',
          'variables': {**COMMON, 'R': '服务规则判断结果（真/假/空值）', '团队VIP金额下限': '全BD、全季度共用的金额参数，元',
                        '所购服务': '订单的服务名称；团队VIP为固定判断条件', '订单金额': '订单收款金额（元）',
                        '服务规则查询结果': '按服务名称查询已接入计提规则；未配置为空值（Check）'}},
    'J': {'title': '分摊比例', 'default': 'IF(AND(ISNULL(本人分摊金额), ISNULL(订单分摊总金额)), IF(存在共享信息, 空值, 1), IF(OR(ISNULL(本人分摊金额), ISNULL(订单分摊总金额)), 空值, IF(AND(订单分摊总金额 > 0, 本人分摊金额 <= 订单分摊总金额), 本人分摊金额 / 订单分摊总金额, 空值)))', 'result': '0～1；1表示100%，空值为待确认',
          'variables': {**COMMON, '拆分订单比例': '已接入拆分金额算出的比例；无共享信息为1，缺依据为空值', '本人分摊金额': '当前BD拆分金额（元）', '订单分摊总金额': '拆分金额合计（元）', '存在共享信息': '订单是否已声明共享（真/假）'}},
    'K': {'title': '奖金计算基数', 'default': 'ROUND(订单金额 * 分摊比例, 2)', 'result': '非负金额（元）；空值为待确认',
          'variables': {**COMMON, 'J': '分摊比例（0～1）', 'S': '最终是否计发提成（真/假/空值）', '订单金额': '订单收款金额（元）', '分摊比例': '按订单和BD查拆分金额后计算的比例'}},
    'T': {'title': '累计营收', 'default': '前序累计 + 本单计入基数', 'result': '非负累计金额（元）；空值会继续向下游传递',
          'variables': {**COMMON, 'K': '本单奖金计算基数', 'S': '最终是否计发提成', '前序累计': '同BD同季度上一单的T，首单为0', '本单计入基数': '按当前累计口径计入的K'}},
    'X': {'title': '适用提点（分段提点）',
          'default': 'IF(是否计发提成, IF(季度基数合计 < 起提门槛, 0, IF(购买性质 == "续费", 续费提点, IF(累计超过季度目标, 超额提点, 目标内提点))), 0)',
          'result': '0～1；0.10表示10%。跨目标订单分别按V=假/真运行本公式计算两段提点',
          'variables': {**COMMON, 'J': '分摊比例', 'K': '本单奖金计算基数', 'S': '最终是否计发提成', 'R': '服务规则判断结果',
                        'T': '当前累计营收', 'U': '成单渠道（自拓、市场推荐、协会/合伙人）', 'V': '累计是否超过目标（真/假/空值）',
                        'W': '当季度目标（元）', '季度基数合计': '同BD同季度全部计入基数之和', '起提门槛': '紫色参数，元',
                        '续费提点': '紫色续费参数，按小数传入', '目标内提点': '当前U渠道的目标内参数，按小数传入', '超额提点': '当前U渠道的超额参数，按小数传入', '是否计发提成': '完整服务规则判断并考虑人工确认后的结果', '购买性质': '首购、新客或续费', '累计超过季度目标': '按BD季度查目标，并比较完整累计营收，真为超过'}},
}
RULE_PARAMETERS = {
    'S': ('vip_minimum',), 'J': (), 'K': (), 'T': ('include_ineligible',),
    'X': ('threshold', 'renewal_rate', 'self_rate', 'self_excess', 'market_rate', 'market_excess', 'partner_rate', 'partner_excess'),
}

FUNCTIONS = {'IF': (3, 3), 'COALESCE': (1, 10), 'ROUND': (1, 2), 'MIN': (1, 10), 'MAX': (1, 10),
             'ABS': (1, 1), 'ISNULL': (1, 1), 'AND': (1, 10), 'OR': (1, 10), 'NOT': (1, 1)}
SPECIAL = {'空值': None, '真': True, '假': False}
MAX_NUMBER = Decimal('1000000000000000')

@lru_cache(maxsize=256)
def parse_formula(column, expression):
    if column not in SPECS:
        raise FormulaError('只允许编辑S、J、K、T、X五列公式')
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
        raise FormulaError('公式不能为空，且不超过2000个字符')
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise FormulaError('公式语法错误，请检查括号、运算符和引号') from exc
    if len(list(ast.walk(tree))) > 250:
        raise FormulaError('公式过于复杂，请拆简条件')
    def visit(node, depth=0):
        if depth > 24:
            raise FormulaError('公式嵌套不能超过24层')
        if isinstance(node, ast.Constant):
            if node.value is None or type(node.value) is bool:
                return
            if type(node.value) in (int, float):
                value = Decimal(ast.get_source_segment(expression.strip(), node))
                if not value.is_finite() or abs(value) > MAX_NUMBER:
                    raise FormulaError('数值常量超出允许范围')
                return
            if isinstance(node.value, str) and len(node.value) <= 100:
                return
        elif isinstance(node, ast.Name):
            if node.id in SPECS[column]['variables'] or node.id in SPECIAL:
                return
            raise FormulaError(f'变量“{node.id}”不可用于{column}列；仅允许该列上游变量，不能循环引用')
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            visit(node.left, depth + 1); visit(node.right, depth + 1); return
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            visit(node.operand, depth + 1); return
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values: visit(value, depth + 1)
            return
        elif isinstance(node, ast.Compare) and all(isinstance(op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot)) for op in node.ops):
            visit(node.left, depth + 1)
            for value in node.comparators: visit(value, depth + 1)
            return
        elif isinstance(node, ast.IfExp):
            for value in [node.test, node.body, node.orelse]: visit(value, depth + 1)
            return
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
            low, high = FUNCTIONS[node.func.id]
            if not low <= len(node.args) <= high:
                raise FormulaError(f'{node.func.id}函数参数数量错误')
            for value in node.args: visit(value, depth + 1)
            return
        raise FormulaError('只支持算术、比较、条件及IF/COALESCE/ROUND/MIN/MAX/ABS/ISNULL/AND/OR/NOT函数')
    try:
        visit(tree.body)
    except (DecimalException, ValueError, TypeError) as exc:
        if isinstance(exc, FormulaError): raise
        raise FormulaError('数值常量格式无效') from exc
    return tree.body

def _number(value):
    if not isinstance(value, Decimal):
        raise FormulaError('算术运算必须使用数值，不能使用文本或真/假')
    if not value.is_finite() or abs(value) > MAX_NUMBER:
        raise FormulaError('计算结果超出允许范围')
    return value

def _truth(value):
    if value is None or type(value) is bool: return value
    raise FormulaError('条件必须是比较结果或真/假')

def evaluate_formula(column, expression, context):
    tree = parse_formula(column, expression)
    def logic(values, is_and):
        unknown = False
        for node in values:
            value = _truth(run(node))
            if value is None: unknown = True
            elif value != is_and: return not is_and
        return None if unknown else is_and
    def condition(test, yes, no):
        value = _truth(run(test))
        return None if value is None else run(yes if value else no)
    def run(node):
        if isinstance(node, ast.Constant):
            if type(node.value) in (int, float):
                return Decimal(ast.get_source_segment(expression.strip(), node))
            return node.value
        if isinstance(node, ast.Name):
            return SPECIAL[node.id] if node.id in SPECIAL else context.get(node.id)
        if isinstance(node, ast.BinOp):
            left, right = run(node.left), run(node.right)
            if left is None or right is None: return None
            left, right = _number(left), _number(right)
            if isinstance(node.op, ast.Add): result = left + right
            elif isinstance(node.op, ast.Sub): result = left - right
            elif isinstance(node.op, ast.Mult): result = left * right
            else:
                if right == 0: raise FormulaError('除数不能为0')
                result = left / right
            return _number(result)
        if isinstance(node, ast.UnaryOp):
            value = run(node.operand)
            if value is None: return None
            if isinstance(node.op, ast.Not): return not _truth(value)
            return _number(value) if isinstance(node.op, ast.UAdd) else -_number(value)
        if isinstance(node, ast.BoolOp): return logic(node.values, isinstance(node.op, ast.And))
        if isinstance(node, ast.IfExp): return condition(node.test, node.body, node.orelse)
        if isinstance(node, ast.Compare):
            left = run(node.left)
            for op, right_node in zip(node.ops, node.comparators):
                right = run(right_node)
                if isinstance(op, (ast.Is, ast.IsNot)):
                    result = (left is right) if isinstance(op, ast.Is) else (left is not right)
                elif left is None or right is None: return None
                elif isinstance(op, ast.Eq): result = left == right
                elif isinstance(op, ast.NotEq): result = left != right
                elif isinstance(op, ast.Lt): result = left < right
                elif isinstance(op, ast.LtE): result = left <= right
                elif isinstance(op, ast.Gt): result = left > right
                else: result = left >= right
                if not result: return False
                left = right
            return True
        name, args = node.func.id, node.args
        if name == 'IF': return condition(*args)
        if name == 'COALESCE':
            for arg in args:
                value = run(arg)
                if value is not None: return value
            return None
        if name in ('AND', 'OR'): return logic(args, name == 'AND')
        values = [run(arg) for arg in args]
        if name == 'ISNULL': return values[0] is None
        if any(value is None for value in values): return None
        if name == 'NOT': return not _truth(values[0])
        numbers = [_number(value) for value in values]
        if name == 'ROUND':
            digits = numbers[1] if len(numbers) == 2 else Decimal(0)
            if digits != digits.to_integral_value() or not 0 <= digits <= 6:
                raise FormulaError('ROUND保留位数必须是0～6的整数')
            return numbers[0].quantize(Decimal(1).scaleb(-int(digits)), rounding=ROUND_HALF_UP)
        if name == 'ABS': return abs(numbers[0])
        return min(numbers) if name == 'MIN' else max(numbers)
    try:
        value = run(tree)
        if value is None: return None
        if column == 'S':
            if type(value) is bool: return value
            if isinstance(value, str) and value in ('是', '否'): return value == '是'
            raise FormulaError('S列必须返回真/假、是/否或空值')
        value = _number(value)
        if value < 0 or (column in ('J', 'X') and value > 1):
            raise FormulaError(f'{column}列结果必须在0～1之间' if column in ('J', 'X') else f'{column}列结果不能为负数')
        return value
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, FormulaError): raise
        raise FormulaError('公式运算失败，请检查数值类型和运算范围') from exc
