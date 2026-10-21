"""Small recursive math grammar. No TeX evaluation, shell, files, or macros."""
from dataclasses import dataclass
import re

from app.core.exceptions import StorageError

MAX_DEPTH = 12
MAX_MATRIX_ROWS = MAX_MATRIX_COLUMNS = 6
MAX_LINES = 8
SYMBOLS = dict(zip(
    'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega'.split(),
    'αβγδεζηθικλμνξοπρστυφχψω'))
SYMBOLS.update(dict(zip('Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega'.split(), 'ΓΔΘΛΞΠΣΥΦΨΩ')))
SYMBOLS.update({'infty': '∞', 'times': '×', 'cdot': '·', 'pm': '±', 'le': '≤',
                'ge': '≥', 'ne': '≠', 'approx': '≈', 'partial': '∂', 'nabla': '∇',
                'in': '∈', 'to': '→', 'sin': 'sin', 'cos': 'cos', 'log': 'log', 'exp': 'exp'})


@dataclass(frozen=True)
class MathNode:
    kind: str
    value: str = ''
    children: tuple = ()


class Parser:
    def __init__(self, expression):
        self.s, self.i = expression, 0

    def error(self, reason):
        raise StorageError('layout_formula_invalid', f'公式语法不受支持：{reason}（位置 {self.i}）。',
                           422, params={'position': self.i, 'reason': reason})

    def space(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def group(self, depth):
        self.space()
        if self.i >= len(self.s) or self.s[self.i] != '{':
            self.error('expected_group')
        self.i += 1
        result = self.sequence(depth + 1, '}')
        if self.i >= len(self.s) or self.s[self.i] != '}':
            self.error('unclosed_group')
        self.i += 1
        if not result.children:
            self.error('empty_group')
        return result

    def script(self, depth):
        self.space()
        if self.i < len(self.s) and self.s[self.i] == '{':
            return self.group(depth)
        value = self.atom(depth + 1)
        if value.kind == 'nary':
            # Single-token scripts cannot carry the operator's own limits/body.
            # Braced scripts use sequence(), which constructs the complete nary.
            self.error('nary_script_requires_group')
        return value

    def atom(self, depth):
        if depth > MAX_DEPTH:
            self.error('depth_limit_12')
        self.space()
        if self.i >= len(self.s):
            self.error('missing_operand')
        char = self.s[self.i]
        if char == '{':
            return self.group(depth)
        if char == '\\':
            self.i += 1
            match = re.match(r'[A-Za-z]+', self.s[self.i:])
            if not match:
                self.error('unknown_command')
            command = match[0]
            self.i += len(command)
            if command in SYMBOLS:
                return MathNode('text', SYMBOLS[command])
            if command == 'frac':
                return MathNode('frac', children=(self.group(depth), self.group(depth)))
            if command == 'sqrt':
                self.space()
                degree = MathNode('seq')
                if self.i < len(self.s) and self.s[self.i] == '[':
                    self.i += 1
                    degree = self.sequence(depth + 1, ']')
                    if self.i >= len(self.s) or self.s[self.i] != ']':
                        self.error('unclosed_degree')
                    self.i += 1
                return MathNode('sqrt', children=(degree, self.group(depth)))
            if command in ('sum', 'int'):
                return MathNode('nary', '∑' if command == 'sum' else '∫')
            if command in ('matrix', 'cases', 'aligned'):
                self.space()
                if self.i >= len(self.s) or self.s[self.i] != '{':
                    self.error('expected_group')
                self.i += 1
                rows, cells = [], []
                while True:
                    cell = self.sequence(depth + 1, '}&', rows=True)
                    if not cell.children:
                        self.error('empty_cell')
                    cells.append(cell)
                    if self.s.startswith('\\\\', self.i):
                        self.i += 2
                        rows.append(tuple(cells))
                        cells = []
                    elif self.i < len(self.s) and self.s[self.i] == '&':
                        if command == 'aligned':
                            self.error('aligned_uses_rows_only')
                        self.i += 1
                    elif self.i < len(self.s) and self.s[self.i] == '}':
                        self.i += 1
                        rows.append(tuple(cells))
                        break
                    else:
                        self.error('unclosed_rows')
                    if len(rows) > MAX_LINES or len(cells) > MAX_MATRIX_COLUMNS:
                        self.error('matrix_or_lines_limit')
                limit = MAX_LINES if command == 'aligned' else MAX_MATRIX_ROWS
                if len(rows) > limit or max(map(len, rows)) > MAX_MATRIX_COLUMNS or len(set(map(len, rows))) > 1:
                    self.error('matrix_or_lines_limit')
                if command == 'cases' and len(rows[0]) != 2:
                    self.error('cases_require_two_columns')
                return MathNode(command, children=tuple(rows))
            self.error('unknown_command')
        if char in '}^_&$#%\\' or ord(char) < 32:
            self.error('unexpected_character')
        self.i += 1
        return MathNode('text', char)

    def sequence(self, depth=0, stops='', rows=False):
        if depth > MAX_DEPTH:
            self.error('depth_limit_12')
        nodes = []
        while True:
            self.space()
            if self.i >= len(self.s) or self.s[self.i] in stops or (rows and self.s.startswith('\\\\', self.i)):
                break
            base = self.atom(depth)
            sub = sup = None
            while True:
                self.space()
                if self.i >= len(self.s) or self.s[self.i] not in '_^':
                    break
                op = self.s[self.i]
                self.i += 1
                if (op == '_' and sub is not None) or (op == '^' and sup is not None):
                    self.error('duplicate_script')
                value = self.script(depth)
                if op == '_':
                    sub = value
                else:
                    sup = value
            if base.kind == 'nary':
                base = MathNode('nary', base.value, (sub or MathNode('seq'), sup or MathNode('seq'), self.group(depth)))
            elif sub is not None or sup is not None:
                base = MathNode('scripts', children=(base, sub, sup))
            nodes.append(base)
        return MathNode('seq', children=tuple(nodes))


def parse_expression(expression: str) -> MathNode:
    parser = Parser(expression)
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
        parser.error('length_1_to_2000')
    node = parser.sequence()
    if parser.i != len(expression):
        parser.error('unexpected_character')
    return node
