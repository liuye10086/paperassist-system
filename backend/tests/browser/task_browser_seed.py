"""Synthetic source preparation shared by API and real-browser verification."""
from io import BytesIO

from openpyxl import Workbook

from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import selection
from tests.api.test_boxplot import generate
from tests.api.test_descriptive import run as statistics_run
from tests.integration.test_explanations import seed_legacy, recover


# Explicit expected values: do not derive the oracle from production display_status.
MATRIX = [
    ('待执行样例.xlsx', 'queued', 'compute', 'queued', None, []),
    ('文件解析样例.xlsx', 'running', 'parse', 'parsing', None, []),
    ('AI计划分析样例.xlsx', 'running', 'plan', 'analyzing', None, []),
    ('数据计算样例.xlsx', 'running', 'compute', 'computing', None, []),
    ('文献检索样例.xlsx', 'running', 'search', 'searching', None, []),
    ('文档生成样例.xlsx', 'running', 'export', 'generating_document', None, []),
    ('待补充资料样例.xlsx', 'waiting_input', 'compute', 'waiting_input', 'unsupported_input', []),
    ('待用户确认样例.xlsx', 'waiting_confirmation', 'compute', 'waiting_confirmation', 'unsupported_confirmation', []),
    ('本地Word完成样例.xlsx', 'succeeded', 'export', 'succeeded', None, []),
    ('合成执行失败样例.xlsx', 'failed', 'export', 'failed', None, ['retry']),
    ('AI解释分析样例.xlsx', 'running', 'interpret', 'analyzing', None, []),
    ('AI核验分析样例.xlsx', 'running', 'verify', 'analyzing', None, []),
    ('文档写作样例.xlsx', 'running', 'write', 'generating_document', None, []),
]


def project(client, name):
    response = client.post('/api/v1/projects', json={
        'name': name, 'research_topic': '仅用于隔离测试的合成数据与状态展示', 'project_type': 'sci'})
    assert response.status_code == 201, response.text
    return response.json()


def source(client, project_id, filename):
    book = Workbook()
    book.active.title = '研究 & 数据'
    for row in [('指标', '组别'), (1, 'A'), (2, 'A'), (3, 'A'), (4, 'B'), (5, 'B'), (6, 'B')]:
        book.active.append(row)
    output = BytesIO()
    book.save(output)
    book.close()
    response = client.post(f'/api/v1/projects/{project_id}/files',
                           files={'file': (filename, output.getvalue())})
    assert response.status_code == 201, response.text
    file = response.json()['file']
    base = f'/api/v1/projects/{project_id}/files/{file["id"]}'
    configured = client.put(base + '/analysis-setup', json=selection(expected_revision=0))
    assert configured.status_code == 200, configured.text
    result = statistics_run(client, base)
    return base, file, result


def request_for(file, result, *, figure=None, explanation=None):
    return TaskCreateRequest(task_type='word_report' if explanation else 'boxplot',
        file_id=file['id'], analysis_run_id=result['id'], expected_revision=result['setup_revision'],
        figure_id=figure['id'] if figure else None, explanation_id=explanation['id'] if explanation else None)


def saved_material(client, base, result):
    """Historical PNG/explanation are synthetic; Word rendering runs locally."""
    plot_url = base + '/analysis-runs/' + result['id'] + '/boxplot'
    figure = generate(client, plot_url)
    explanation_url = plot_url.replace('/boxplot', '/explanation')
    seed_legacy(client, explanation_url, figure)
    recover()  # Explicit preparation only; the live API's old worker is disabled.
    response = client.get(explanation_url)
    assert response.status_code == 200, response.text
    explanation = response.json()['explanation']
    assert explanation
    return figure, explanation


def matrix(client, owner, project_id):
    from app.domain.tasks.execution import run_word_task

    service = TaskService(owner)
    rows = []
    for index, (filename, status, phase, display, wait_kind, actions) in enumerate(MATRIX):
        base, file, result = source(client, project_id, filename)
        if status == 'succeeded':
            figure, explanation = saved_material(client, base, result)
            request = request_for(file, result, figure=figure, explanation=explanation)
        else:
            request = request_for(file, result)
        task, created = service.create(project_id, request, idempotency_key=f'matrix-{index}')
        assert created
        if status == 'succeeded':
            task = run_word_task(task['id'], task['revision'])
            assert task['status'] == 'succeeded' and task['result_report_id']
        elif status != 'queued':
            task = service.transition(task['id'], expected_revision=task['revision'], status='running', phase=phase)
            if status != 'running':
                reason = {'waiting_input': 'input_required', 'waiting_confirmation': 'confirmation_required',
                          'failed': 'execution_failed'}[status]
                task = service.transition(task['id'], expected_revision=task['revision'], status=status, reason_code=reason)
        assert (task['status'], task['phase'], task['display_status']) == (status, phase, display)
        rows.append({'filename': filename, 'task_id': task['id'], 'file_id': file['id'],
            'status': status, 'phase': phase, 'display_status': display,
            'wait_kind': wait_kind, 'allowed_actions': actions,
            'evidence': 'actual_local_word_export' if status == 'succeeded' else 'synthetic_state_projection'})
    return rows
