"""Offline error contract checks; run with --confcutdir=tests/static (no DB)."""
import ast
from pathlib import Path
import re

import pytest

from app.core.errors import PUBLIC_CODES, error_detail, safe_params
from app.domain.tasks.errors import safe_error_code


ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / 'frontend/src/shared/i18n/errorMessages.ts'
ADDED_CODES = frozenset('''
admin_usage_summary_not_found literature_pmc_not_authorized numeric_process_terminated
review_continuation_invalid review_document_export_not_found review_document_export_not_ready
review_document_not_found review_progress_correction_conflict review_progress_invalid
review_return_blocked review_return_invalid review_return_preview_conflict review_revision_not_ready
'''.split())
CONSTRUCTORS = {'StorageError', 'PlotError', 'NumericError', 'CorrelationError', 'ComparisonError'}


def literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def emitted_codes():
    """Include direct codes, code-default helpers, second/keyword codes and child mappings."""
    codes = set()
    for path in (ROOT / 'backend/app').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        helpers = {}
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = function.args.posonlyargs + function.args.args
            positions = {arg.arg: i for i, arg in enumerate(parameters)}
            if 'code' not in positions:
                continue
            if not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id in CONSTRUCTORS and node.args
                       and isinstance(node.args[0], ast.Name) and node.args[0].id == 'code'
                       for node in ast.walk(function)):
                continue
            helpers[function.name] = positions['code']
            defaults = dict(zip([arg.arg for arg in parameters][-len(function.args.defaults):], function.args.defaults))
            default = literal(defaults.get('code'))
            if default:
                codes.add(default)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name in CONSTRUCTORS or name == 'fail':
                value = literal(node.args[0]) if node.args else None
            elif name in helpers:
                position = helpers[name]
                value = literal(node.args[position]) if len(node.args) > position else None
                value = next((literal(kw.value) for kw in node.keywords if kw.arg == 'code'), value)
            else:
                continue
            if value:
                codes.add(value)
        if path.name == 'fixed_statistics_process.py':
            # The isolated child maps parse errors before raising NumericError(code, ...).
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'code' for target in node.targets):
                    codes.update(value.value for value in ast.walk(node.value)
                                 if isinstance(value, ast.Constant) and isinstance(value.value, str)
                                 and value.value.startswith('numeric_'))
    return codes


def test_catalog_covers_all_public_codes():
    entries = set(re.findall(r'^\s*([a-z][a-z0-9_]+):\s*\{', CATALOG.read_text(encoding='utf-8'), re.MULTILINE))
    assert PUBLIC_CODES <= entries, f'Missing translations: {sorted(PUBLIC_CODES - entries)}'


def test_direct_helper_and_numeric_mapping_codes_are_public():
    codes = emitted_codes()
    assert ADDED_CODES <= codes, f'Emitter scan missed: {sorted(ADDED_CODES - codes)}'
    assert codes <= PUBLIC_CODES, f'Unpublished error codes: {sorted(codes - PUBLIC_CODES)}'


@pytest.mark.parametrize('code', sorted(ADDED_CODES))
def test_added_codes_survive_http_and_task_envelopes_without_arbitrary_params(code):
    assert error_detail(code, 'fixed local message', {'secret': 'PRIVATE TRACE'}) == {
        'code': code, 'message': 'fixed local message', 'params': {},
    }
    assert safe_error_code(code) == code


def test_projection_compound_codes_stay_derived_and_unknown_codes_stay_private():
    assert not any(code.startswith('figure_projection_') and code != 'figure_projection_invalid' for code in PUBLIC_CODES)
    assert safe_params('figure_projection_invalid', {'reason': 'duplicate_x', 'secret': 'PRIVATE TRACE'}) == {'reason': 'duplicate_x'}
    assert safe_params('figure_projection_invalid', {'reason': 'PRIVATE TRACE'}) == {}
    detail = error_detail('private_code', 'PRIVATE TRACE', {'secret': 'PRIVATE TRACE'})
    assert detail['code'] == 'internal_error'
    assert 'PRIVATE TRACE' not in str(detail)
    assert safe_error_code('private_code') == 'internal_error'
