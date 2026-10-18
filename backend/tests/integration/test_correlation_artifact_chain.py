"""Real persisted plans and artifacts, synthetic cloud only; no development rows."""
from tests.helpers.statistics import statistics_post
from copy import deepcopy
from io import BytesIO
import json
from statistics import correlation
from zipfile import ZipFile

import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.helpers.analysis_plan import run_plan, review_plan, plan_decision, decide_plan
from tests.integration.test_correlation_plan import prepared_correlations, create_correlation
from tests.integration.test_dataset_artifact_chain import confirmed_task
from tests.integration.test_boxplot_execution import SyntheticPlotProvider, run as run_plot
from tests.integration.test_explanation_execution import SyntheticProvider, run as run_explanation


def result_for(client, language='en', mode='pair', method='pearson'):
    base, file, prepared = prepared_correlations(client)
    task, body = create_correlation(client, base, prepared)
    assert run_plan(task)['status'] == 'waiting_confirmation'
    view = review_plan(client, task)
    choice = deepcopy(body['selection'])
    choice.update(mode=mode, method=method)
    choice['assumptions']['relationship_form'] = 'linear' if method == 'pearson' else 'monotonic'
    if mode == 'matrix':
        choice.update(columns=['A', 'B', 'C'], units={'A':'', 'B':'', 'C':''})
    research = {**body['research_request'], 'output_language':language,
                'question':'LOCAL-QUESTION-SENTINEL'}
    revised = {**plan_decision(view, 'revise', choice), 'research_request':research}
    response = decide_plan(client, task, revised, 'choose-method')
    assert response.status_code == 202, response.text
    assert run_plan(response.json())['status'] == 'waiting_confirmation'
    accepted = decide_plan(client, task, plan_decision(review_plan(client, task)), 'confirm-final')
    assert run_plan(accepted.json())['status'] == 'succeeded'
    response = statistics_post(client, base+'/analysis-runs', json={'expected_revision':1})
    assert response.status_code == 200, response.text
    return base, file, response.json()


def modern_task(client, base, file, result, kind, figure=None, explanation=None):
    task, owner = confirmed_task(client, base, file, result, kind, figure, explanation)
    if kind != 'word_report':
        from app.domain.plot_policy import derive_execution_policy as plot_policy
        from app.domain.explanation_policy import derive_execution_policy as explanation_policy
        key = 'boxplot_policy' if kind == 'boxplot' else 'explanation_policy'
        with database_connection(write=True) as db:
            snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
            # Synthetic ledger prices; production policy routing is exercised unchanged.
            policy = (plot_policy if kind == 'boxplot' else explanation_policy)(snapshot[key], {'schema_version':2})
            db.execute('UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,%s,%s) WHERE id=%s',
                       ([key], Jsonb(policy), task['id']))
    return task, owner


def ranks(values):
    ordered = sorted(values)
    return [sum(i+1 for i, value in enumerate(ordered) if value == current) / ordered.count(current) for current in values]


class ModernPlotProvider(SyntheticPlotProvider):
    """Compute from uploaded observations, without access to authoritative results."""
    def __init__(self, *, corrupt=False):
        super().__init__(None, pending=False)
        self.corrupt = corrupt

    def receipt(self):
        value = super().receipt()
        annotations = value['response']['output'][1]['content'][0]['annotations']
        annotations[0]['filename'] = '/mnt/data/figure.png'
        return value

    def download(self, file_id, container_id, limit, *, policy):
        self.downloads.append(file_id)
        if file_id == 'cfile_png': return self.png
        payload = deepcopy(self.payload)
        columns = list(map(list, zip(*payload.pop('values'))))
        if payload['correlation_method'] == 'spearman': columns = list(map(ranks, columns))
        matrix = [[correlation(x, y) for y in columns] for x in columns]
        value = {**payload, **payload.pop('labels')}
        value.pop('labels', None)
        value['statistics'] = {'n':len(columns[0]), **({'coefficient':matrix[0][1]} if value['mode'] == 'pair' else {'matrix':matrix})}
        if self.corrupt: value['statistics']['n'] += 1
        return json.dumps(value, ensure_ascii=False).encode()


class ModernExplanationProvider(SyntheticProvider):
    def receipt(self):
        value = super().receipt()
        payload = self.posts[0][1]
        draft = {key: ('Based on ' if payload['language']=='en' else '依据') +
                 ', '.join('{{'+ref+'}}' for ref in refs) + '.' for key, refs in payload['required_references'].items()}
        value['response']['output'][0]['content'][0]['text'] = json.dumps(draft, ensure_ascii=False)
        return value


def finish_plot(task, provider):
    for _ in range(8):
        task = run_plot(task, provider)
        if task['status'] in ('failed','succeeded'): break
    return task


@pytest.mark.parametrize('language,mode,method', [('en','pair','pearson'), ('zh-CN','pair','spearman'),
    ('en','matrix','spearman'), ('zh-CN','matrix','pearson')])
def test_confirmed_plan_to_original_png_explanation_word_and_history(client, monkeypatch, language, mode, method):
    from tests.browser.task_browser_support import block_real_providers
    blocked = block_real_providers(monkeypatch)
    base, file, result = result_for(client, language, mode, method)
    task, _ = modern_task(client, base, file, result, 'boxplot')
    provider = ModernPlotProvider()
    done = finish_plot(task, provider)
    assert done['status'] == 'succeeded', done
    assert 'statistics' not in provider.payload
    assert 'LOCAL-QUESTION-SENTINEL' not in json.dumps(provider.payload)
    with database_connection() as db:
        figure = json.loads(db.execute('SELECT figure_json FROM figures WHERE id=%s', (done['result_figure_id'],)).fetchone()['figure_json'])
    assert figure['language'] == language and figure['engine']['id']=='openai_analysis_plot_v2'
    assert figure['statistics']['n'] == 3
    task, _ = modern_task(client, base, file, result, 'explanation', figure)
    explaining = ModernExplanationProvider()
    done = run_explanation(task, explaining)
    assert done['status'] == 'succeeded', done
    assert explaining.posts[0][1]['language'] == language
    assert 'LOCAL-QUESTION-SENTINEL' not in json.dumps(explaining.posts[0][1])
    with database_connection() as db:
        explanation = json.loads(db.execute('SELECT explanation_json FROM explanations WHERE id=%s', (done['result_explanation_id'],)).fetchone()['explanation_json'])
    task, _ = modern_task(client, base, file, result, 'word_report', figure, explanation)
    from app.domain.tasks.execution import run_word_task
    done = run_word_task(task['id'], task['revision'])
    assert done['status'] == 'succeeded', done
    workspace = client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code == 200, workspace.text
    url = workspace.json()['artifacts']['report']['download_url']
    report = client.get(url)
    assert report.status_code == 200, report.text if report.status_code != 200 else ''
    from docx import Document
    document = Document(BytesIO(report.content))
    text = '\n'.join(p.text for p in document.paragraphs)
    assert ('Correlation analysis report' if language=='en' else '相关分析报告') in text
    assert 'LOCAL-QUESTION-SENTINEL' in text
    body_text = text.split('Appendix B' if language=='en' else '附录 B')[0]
    assert result['source']['dataset_sha256'] not in body_text and result['id'] not in body_text
    with ZipFile(BytesIO(report.content)) as archive:
        assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')] == [provider.png]
    # A later setup does not make this immutable artifact unreadable.
    from tests.api.test_analysis import selection
    saved = client.put(base+'/analysis-setup', json=selection(dataset_id=result['source']['dataset_id'],
        expected_revision=1, sheet_name=result['selection']['sheet_name'], numeric_column='A', group_column=None, unit=''))
    assert saved.status_code == 200, saved.text
    assert client.get(url).content == report.content
    assert blocked == []
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        assert audit_database(db)['ok']
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==2


def test_cloud_mismatch_is_durable_failure_with_no_published_artifact(client, monkeypatch):
    from tests.browser.task_browser_support import block_real_providers
    blocked = block_real_providers(monkeypatch)
    base, file, result = result_for(client)
    task, _ = modern_task(client, base, file, result, 'boxplot')
    done = finish_plot(task, ModernPlotProvider(corrupt=True))
    assert done['status'] == 'failed' and done['error_code']=='plot_result_mismatch', done
    workspace = client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code == 200, workspace.text
    failure = workspace.json()['verification_failure']
    assert any(item['path']=='statistics.n' for item in failure['differences'])
    assert failure['manifest']['figure_kind']=='scatter'
    assert failure['manifest']['correlation_method']=='pearson' and failure['manifest']['mode']=='pair'
    assert failure['provenance']['png_file_id']=='cfile_png'
    assert failure['provenance']['result_file_id']=='cfile_result'
    assert 'values' not in failure['manifest'] and 'LOCAL-QUESTION-SENTINEL' not in json.dumps(failure)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==1
        assert db.execute('SELECT verification_failure FROM tasks WHERE id=%s', (task['id'],)).fetchone()['verification_failure']==failure
    assert blocked == []
