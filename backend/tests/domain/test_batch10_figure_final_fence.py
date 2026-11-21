import json
from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('kind', ['figure', 'explanation'])
def test_cloud_publication_rechecks_writer_lease_after_verification(monkeypatch, kind):
    from app.adapters.task_execution_store import LeaseLost
    from app.domain.figure_workbench import execution, explanations

    events = []
    call = dict(id='call', provider_status='completed', input_digest='c' * 64, model='synthetic',
                provider_response_id='response', provider_state={'container_id': 'container'})
    png = b'synthetic-figure-content'
    figure = dict(id='figure', figure_config_version_id='version', analysis_run_id='run',
                  engine={'id': 'openai_figure_workbench_v4'}, presentation={'schema_version': 3},
                  sha256=sha256(png).hexdigest(), facts_sha256='b' * 64,
                  provenance=dict(model_call_id=call['id'], model_input_digest=call['input_digest'],
                                  response_id='response', container_id='container', model='synthetic'))
    version = 'figure_explanation_v5'
    explanation = dict(id='exp', figure_id='figure', analysis_run_id='run', engine={'id': version})
    task = dict(id='task', input_snapshot=dict(figure=figure, explanation_policy={'policy': {'prompt_version': version}}))

    class Repository:
        @contextmanager
        def connection(self, *, write):
            assert write
            try:
                yield SimpleNamespace(execute=self.execute)
            except LeaseLost:
                events.append('rollback')
                raise

        def execute(self, sql, args):
            if 'FROM model_calls' in sql:
                assert args == (task['id'], execution.PLOT_KEY)
                row = call
            elif 'FROM figures' in sql:
                assert args == (figure['figure_config_version_id'],)
                row = {'figure_json': json.dumps(figure)}
            elif 'FROM explanations' in sql:
                assert args == (figure['id'], version)
                row = None
            else:
                if kind == 'figure':
                    assert sql.startswith('UPDATE tasks SET figure_candidate=NULL') and args == (task['id'],)
                else:
                    assert sql.startswith('INSERT INTO explanations') and json.loads(args[-1]) == explanation
                events.append('write')
                row = None
            return SimpleNamespace(fetchone=lambda: row)

        def require_lease(self, db, lease):
            if 'write' in events:
                events.append('expired')
                raise LeaseLost()
            events.append('lease')
            return task

        def _finish(self, *args):
            pytest.fail('An expired writer must not finish publication')

    monkeypatch.setattr(execution, 'require_task_sources', lambda *args: events.append('source'))
    repo = Repository()
    if kind == 'figure':
        def verify_png(saved):
            assert saved == figure and saved['sha256'] == sha256(png).hexdigest()
            events.append('verified')
            return png
        with pytest.raises(LeaseLost):
            execution._publish_figure(repo, None, SimpleNamespace(assets=SimpleNamespace(figure_png=verify_png)), figure)
        assert events == ['lease', 'source', 'verified', 'write', 'expired', 'rollback']
    else:
        def validate(bundle, value):
            assert bundle['figure'] == figure and value == explanation
            events.append('verified')
        monkeypatch.setattr(explanations, 'validate_saved', validate)
        with pytest.raises(LeaseLost):
            execution._publish_explanation(repo, None, {'figure': figure}, explanation)
        assert events == ['verified', 'lease', 'source', 'write', 'expired', 'rollback']
