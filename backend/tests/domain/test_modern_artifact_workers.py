"""Exercise real Worker publication routing with isolated gateway boundaries."""
from types import SimpleNamespace
import pytest

from app.domain.tasks import boxplot_execution as plot_worker, explanation_execution as explanation_worker


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def source_result():
    return dict(id='run', file_id='file', source_sha256='a'*64, setup_revision=2,
        schema_version=3, result_type='correlation', selection=dict(method='pearson', mode='pair'),
        statistics=dict(method='pearson', mode='pair', n=5), check=dict(valid_count=5, excluded_count=0),
        analysis_plan=dict(sha256='b'*64), analysis_context=dict(plan=dict(research_request=dict(output_language='en'))))


def policy():
    return dict(model='synthetic-model', prompt_version='openai_analysis_plot_v2', max_output_tokens=16000,
        timeout_seconds=15, tools=['code_interpreter'], output_format='text', price=dict(version='synthetic',
            model='synthetic-model', input_micro_usd_per_million=100, cached_input_micro_usd_per_million=50,
            output_micro_usd_per_million=200))


class Repository:
    def __init__(self, task_type='boxplot'):
        self.snapshot = dict(result=source_result(), figure=dict(id='figure', sha256='c'*64,
            engine=dict(id='openai_analysis_plot_v2')), external_processing=dict(
                version=4, provider='openai', task_type=task_type))
        self.task = dict(id='task', user_id='synthetic-owner', revision=2, input_snapshot=self.snapshot)
        self.call = dict(id='call', status='completed', provider_response_id='resp_synthetic',
            provider_state=dict(container_id='cntr_synthetic'), policy_snapshot=policy(), input_digest='d'*64)
        self.expected = dict(title='Correlation', statistics=dict(coefficient=.8, n=5))
        self.payload = dict(language='en', schema_version=2, facts={}, required_references={})
        self.saved = None

    def load_boxplot_task(self, lease): return self.task
    def load_explanation_task(self, lease): return self.task
    def boxplot_call(self, lease): return self.call
    def explanation_call(self, lease): return self.call
    def load_boxplot(self, lease): return self.task, self.snapshot, self.payload, self.expected
    def load_explanation(self, lease): return self.task, self.snapshot, self.payload
    def register_figure_candidate(self, lease, snapshot, figure, png, expected, payload):
        self.saved = figure
        return dict(candidate=True)
    def write_figure_candidate(self, lease, candidate, png): pass
    def complete_boxplot(self, lease, snapshot, payload, expected): return self.saved
    def complete_explanation(self, lease, snapshot, explanation):
        self.saved = explanation
        return explanation


def gateway(monkeypatch, module, repo):
    monkeypatch.setattr(module, 'ModelUsageService', lambda *a, **k: None)
    monkeypatch.setattr(module, 'ModelGateway', lambda *a, **k: SimpleNamespace(
        refresh=lambda _: dict(call=repo.call, response=dict(status='completed'))))


def test_plot_worker_publishes_frozen_english_language_and_modern_renderer(monkeypatch):
    repo = Repository(); gateway(monkeypatch, plot_worker, repo)
    monkeypatch.setattr(plot_worker, 'parse_plot_response', lambda *a, **k: dict(provenance=dict(model='synthetic-model')))
    monkeypatch.setattr(plot_worker, 'download_plot', lambda *a, **k: dict(png=b'synthetic-bytes', provenance=dict(model='synthetic-model')))
    result = plot_worker._execute(repo, object(), None, lambda: object(), [])
    assert result['language'] == 'en'
    assert result['engine']['id'] == 'openai_analysis_plot_v2'
    assert result['figure_kind'] == 'scatter'
    assert result['plan_sha256'] == 'b'*64
    assert result['provenance']['model_call_id'] == 'call'


def test_explanation_worker_publishes_frozen_language_and_correct_prompt(monkeypatch):
    from app.domain import explanation_response
    repo = Repository('explanation'); gateway(monkeypatch, explanation_worker, repo)
    monkeypatch.setattr(explanation_response, 'parse_explanation_response', lambda *a, **k:
        dict(draft={}, provenance=dict(model='synthetic-model')))
    monkeypatch.setattr(explanation_worker, 'render_explanation', lambda *a, **k: [])
    result = explanation_worker._execute(repo, object(), None, lambda: object(), lambda _: None)
    assert result['language'] == 'en'
    assert result['engine']['id'] == 'analysis_explanation_v2'
    assert result['provenance']['prompt_version'] == 'analysis_explanation_v2'
    assert result['plan_sha256'] == 'b'*64


def test_plot_mismatch_is_saved_before_terminal_failure_without_publishing(monkeypatch):
    from app.domain.plot_response import PlotVerificationError
    repo = Repository(); gateway(monkeypatch, plot_worker, repo)
    differences = [dict(path='statistics.coefficient', expected=.8, actual=.1, reason='value_mismatch')]
    recorded = []
    def failed_download(*args, **kwargs):
        raise PlotVerificationError(differences, dict(statistics=dict(coefficient=.1)), dict(response_id='resp_synthetic'))
    def persist(lease, **evidence):
        recorded.append(evidence)
        return dict(status='failed', reason_code='plot_result_mismatch')
    repo.record_plot_mismatch = persist
    monkeypatch.setattr(plot_worker, 'parse_plot_response', lambda *a, **k: dict(provenance=dict(model='synthetic-model')))
    monkeypatch.setattr(plot_worker, 'download_plot', failed_download)
    result = plot_worker._execute(repo, object(), None, lambda: object(), [])
    assert result['status'] == 'failed'
    assert recorded == [dict(differences=differences, manifest=dict(statistics=dict(coefficient=.1)),
                             provenance=dict(response_id='resp_synthetic'))]
    assert repo.saved is None
