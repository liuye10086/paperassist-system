"""Reconstruct genuine pre-plan descriptive fixtures using real bounded math.

This is a TEST-only historical record seed, not new API execution. New v2
receipts are never invented: the old engine JSON omits execution_contract and
readers must report legacy_unverified. Use statistics_post for new statistics.
"""
import re


def seed_legacy_statistics(client, base, revision=1):
    from app.db.database import get_database_config
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir, get_excel_settings
    from app.domain.descriptive import execute, RunRequest
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.statistics_execution.verification import computation_scope
    config = get_database_config()
    assert config.environment == 'test' and config.url.database == 'paperassist_system_test'
    assert re.fullmatch(r'pa_test_[0-9a-f]{32}', config.schema)
    me = client.get('/api/v1/auth/me')
    assert me.status_code == 200
    store = ProjectStore(get_data_dir(), owner_id=me.json()['user']['id'])
    parts = base.split('/')
    project, file = parts[4], parts[6]
    saved = store.analysis_setup(project, file)
    assert saved['selection']['task_type'] == 'descriptive_boxplot'
    assert not saved.get('analysis_plan')

    class HistoricalStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def save_analysis_run(self, project_id, file_id, result):
            assert result['engine']['execution_contract'] == 'fixed_statistics_v2'
            historical = {**result, 'engine': {key: value for key, value in result['engine'].items()
                                               if key != 'execution_contract'}}
            return store.save_analysis_run(project_id, file_id, historical)

    with numeric_execution_scope(timeout_seconds=60), computation_scope():
        result = execute(project, file, RunRequest(expected_revision=revision), HistoricalStore(), get_excel_settings())
    assert 'execution_contract' not in result['engine']
    state = client.get(base + '/analysis-result')
    assert state.status_code == 200, state.text
    assert state.json()['execution_verification'] == 'legacy_unverified'
    return result
