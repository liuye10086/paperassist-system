"""Pure structural checks: no database connections or real recovery execution."""
import ast
import importlib
from pathlib import Path

import pytest

from app.core.paths import BACKEND_ROOT, PROJECT_ROOT


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_configuration_and_migrations_are_independent_of_cwd(monkeypatch, tmp_path):
    from app.core import config
    from app.db.database import alembic_config

    paths = []
    monkeypatch.setattr(config, 'dotenv_values', lambda path, **kwargs: paths.append(path) or {})
    monkeypatch.chdir(tmp_path)
    with monkeypatch.context() as local:
        local.setattr(config, 'local_config', lambda: {})
        assert config.get_data_dir() == BACKEND_ROOT / 'data'
    config.local_config()
    assert paths == [BACKEND_ROOT / '.env']
    settings = alembic_config()
    assert Path(settings.config_file_name) == BACKEND_ROOT / 'alembic.ini'
    assert Path(settings.get_main_option('script_location')) == BACKEND_ROOT / 'alembic'
    assert PROJECT_ROOT / 'backend' == BACKEND_ROOT


@pytest.mark.parametrize('label,database_module,store_module', [
    ('legacy', 'app.database', 'app.storage'),
    ('current', 'app.db.database', 'app.adapters.storage'),
])
def test_recovery_uses_the_matching_code_layout(monkeypatch, tmp_path, label, database_module, store_module):
    from app.maintenance import recovery_drill

    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        return b'' if args[-1] == 'check' else b'{"source_verified":true,"health_http_status":200}'
    monkeypatch.setattr(recovery_drill, 'run', fake_run)
    recovery_drill.app_validation(tmp_path / 'python', tmp_path, {}, tmp_path, label)
    assert calls[0] == [tmp_path / 'python', '-m', database_module, 'check']
    imports = [n.module for n in ast.walk(ast.parse(calls[1][-1])) if isinstance(n, ast.ImportFrom)]
    assert store_module in imports
    assert ('app.report_store' if label == 'legacy' else 'app.adapters.report_store') in imports
    assert ('app.adapters.storage' if label == 'legacy' else 'app.storage') not in imports


def test_domain_has_no_dependency_on_api_and_stable_entrypoints_import():
    for path in (BACKEND_ROOT / 'app/domain').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('app.api'), path
    assert importlib.import_module('app.main').app is not None
    assert callable(importlib.import_module('app.manage_users').main)
    assert importlib.import_module('app.maintenance.recovery_drill').__doc__
