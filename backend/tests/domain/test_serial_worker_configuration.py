"""Serial production defaults, including legacy deployment settings."""
import os

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('configured', ['1', '2'])
def test_legacy_deployment_ceiling_cannot_enable_parallel_workers(monkeypatch, configured):
    from app.workers.config import concurrency_ceiling, startup_configuration
    monkeypatch.setenv('PAPERASSIST_WORKER_CONCURRENCY_CEILING', configured)
    legacy = dict(id='old', sha256='saved', bundle={'basic': {'worker_concurrency': 2}})
    monkeypatch.setattr('app.domain.admin_configuration.bindings.current', lambda db: legacy)
    assert concurrency_ceiling() == 1
    loaded = startup_configuration(object())
    assert loaded['concurrency'] == 1
    assert loaded['configuration_id'] == 'old'
    assert legacy['bundle']['basic']['worker_concurrency'] == 2


def test_numeric_thread_settings_override_inherited_parallel_values(monkeypatch):
    from app.workers.config import configure_execution_environment
    names = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'OMP_THREAD_LIMIT', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')
    for name in names:
        monkeypatch.setenv(name, '8')
    configure_execution_environment()
    assert {os.environ[name] for name in names} == {'1'}


def test_worker_child_is_recycled_after_each_task_and_does_not_prefetch_excess(monkeypatch):
    from app.workers import celery_app
    monkeypatch.setattr(celery_app, 'queue_config', lambda: ('amqp://guest:guest@localhost/test', 'paperassist.test.serial'))
    app = celery_app.create_app()
    try:
        assert app.conf.worker_prefetch_multiplier == 1
        assert app.conf.worker_max_tasks_per_child == 1
        assert app.conf.worker_concurrency == 1
    finally:
        app.close()
