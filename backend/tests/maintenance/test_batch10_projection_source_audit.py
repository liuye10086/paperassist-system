"""Projection v2 audit is bound to saved source/configuration, not a version label."""
from copy import deepcopy
from psycopg.types.json import Jsonb

from app.db.database import database_connection
from app.adapters.report_store import digest
from app.adapters.figure_workbench_store import projection_request_digest
from app.domain.figure_workbench.contracts import SaveConfiguration
from app.maintenance.dataset_source_audit import audit_dataset_sources
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_batch05_figure_store import source


def test_projection_v2_audit_binds_snapshot_config_and_stored_run(client):
    workbench, project, result = source(client)
    args = project, result['file_id'], result['id']
    saved = workbench.save(*args, SaveConfiguration(config={
        'figure_kind': 'line', 'language': 'en', 'projection': {'x_column': 'A', 'y_column': 'C'}}))
    version_id = saved['version']['id']
    task = workbench.check(*args, version_id)['task']
    assert task['status'] == 'queued'
    with database_connection() as db:
        original_task = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone())
        original_config = dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s', (version_id,)).fetchone())

    def invalid():
        with database_connection() as db:
            return next(c for c in audit_dataset_sources(db) if c['table'] == 'tasks' and c['column'] == 'dataset_source')['invalid']

    assert invalid() == 0
    for damage in ('execution_version', 'configuration_hash', 'snapshot_result', 'request_digest',
                   'configuration_reference_type', 'output_language', 'self_consistent_config_source'):
        snapshot = deepcopy(original_task['input_snapshot'])
        config = deepcopy(original_config)
        request_digest = original_task['input_digest']
        if damage == 'execution_version': snapshot['projection_execution'] = 1
        elif damage == 'configuration_hash': snapshot['figure_workbench']['configuration_sha256'] = '0' * 64
        elif damage == 'snapshot_result': snapshot['result']['filename'] = 'forged.xlsx'
        elif damage == 'request_digest': request_digest = '0' * 64
        elif damage == 'configuration_reference_type': snapshot['figure_workbench']['version_id'] = []
        elif damage == 'output_language': snapshot['output_language'] = 'zh-CN'
        else:
            config['source_json']['result_sha256'] = '0' * 64
            config['sha256'] = digest({'config': config['config_json'], 'source': config['source_json']})
            snapshot['figure_workbench']['configuration_sha256'] = config['sha256']
            request_digest = projection_request_digest(config)
        with database_connection(write=True) as db:
            db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s',
                       (Jsonb(snapshot), request_digest, task['id']))
            db.execute('UPDATE figure_config_versions SET source_json=%s,sha256=%s WHERE id=%s',
                       (Jsonb(config['source_json']), config['sha256'], version_id))
        assert invalid() == 1, damage
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s',
                   (Jsonb(original_task['input_snapshot']), original_task['input_digest'], task['id']))
        db.execute('UPDATE figure_config_versions SET source_json=%s,sha256=%s WHERE id=%s',
                   (Jsonb(original_config['source_json']), original_config['sha256'], version_id))
    assert invalid() == 0
