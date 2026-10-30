"""Pure safety/diff checks; never connect to PostgreSQL or create an app."""
import copy
import importlib.util
from pathlib import Path
import pytest


def verifier():
    path = Path(__file__).resolve().parents[1] / 'verify_cr_b02_incremental_migration.py'
    assert path.is_file(), 'The retained 0058-to-0059 migration verifier is missing'
    spec = importlib.util.spec_from_file_location('b02_incremental_verifier', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample():
    return {'tables': {'tasks': {'columns': ['id', 'status'], 'count': 1, 'sha256': 'a'},
                       'files': {'columns': ['id'], 'count': 0, 'sha256': 'b'}},
            'indexes': {'tasks_pkey': {'table': 'tasks', 'definition': 'CREATE UNIQUE INDEX tasks_pkey ON tasks(id)'}},
            'assets': {'files/original.xlsx': {'size': 3, 'sha256': 'c'}}}


def test_state_rejects_public_or_other_asset_directory():
    module = verifier()
    state = module.new_state(Path('C:/Users/86182/Desktop/PaperAssist-System'))
    assert module.validate_state(state) == state
    for key, value in [('schema', 'public'), ('assets', 'C:/Users/86182/Desktop/PaperAssist-System/backend/data')]:
        changed = {**state, key: value}
        with pytest.raises(ValueError):
            module.validate_state(changed)


def test_comparison_detects_old_row_mutation_missing_index_and_asset_change():
    module = verifier()
    baseline = sample()
    assert module.compare_preservation(baseline, copy.deepcopy(baseline)) == []
    changed = copy.deepcopy(baseline)
    changed['tables']['tasks']['sha256'] = 'different'
    changed['indexes'] = {}
    changed['assets']['files/original.xlsx']['sha256'] = 'different'
    failures = module.compare_preservation(baseline, changed)
    assert {'rows:tasks', 'index:tasks_pkey', 'asset:files/original.xlsx'} <= set(failures)


def test_old_columns_cannot_disappear_and_new_empty_tables_do_not_hide_mutations():
    module = verifier()
    baseline = sample()
    changed = copy.deepcopy(baseline)
    changed['tables']['tasks']['columns'] = ['id']
    changed['tables']['new_bio_table'] = {'columns': ['id'], 'count': 0, 'sha256': 'z'}
    assert 'columns:tasks' in module.compare_preservation(baseline, changed)
