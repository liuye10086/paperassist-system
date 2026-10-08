"""Offline acceptance of the complete, version-bound Excel-to-Word workflow."""

import hashlib
from io import BytesIO
import json
import math
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from app.main import app
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, generate  # noqa: F401
from tests.integration.test_explanations import writer, submit  # noqa: F401
from tests.integration.test_reports import export


def workbook_bytes():
    book = Workbook()
    book.active.title = '数据'
    for row in [['数值', '组别']] + [[value, 'A'] for value in range(1, 25)] + [
        [7, 'B'], [None, 'A'], [999, None],
    ]:
        book.active.append(row)
    book.create_sheet('空表')
    content = BytesIO()
    book.save(content)
    book.close()
    return content.getvalue()


def digest(value):
    # Independently check the persisted input fingerprint, not production helpers.
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def assert_bindings(project, file, result, figure, explanation, report, payload):
    assert file['project_id'] == project['id'] and result['file_id'] == file['id']
    assert figure['file_id'] == file['id']
    for item in (figure, explanation, report):
        assert item['analysis_run_id'] == result['id']
        assert item['setup_revision'] == result['setup_revision']
    for item in (result, figure, explanation, report):
        assert item['source_sha256'] == file['sha256']
    assert explanation['figure_id'] == report['figure_id'] == figure['id']
    assert explanation['figure_sha256'] == report['figure_sha256'] == figure['sha256']
    assert report['explanation_id'] == explanation['id']
    assert explanation['provenance']['input_sha256'] == digest(payload)
    snapshot = {'project': {key: project[key] for key in ('id', 'name', 'research_topic', 'project_type', 'created_at')},
                'result': result, 'figure': figure, 'explanation': explanation}
    assert report['input_sha256'] == digest(snapshot)
    assert figure['verification']['status'] == 'matched'
    assert explanation['verification']['status'] == 'references_checked'


def assert_docx(content, project, file, result, figure, explanation, report, revision):
    assert hashlib.sha256(content).hexdigest() == report['sha256']
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(BytesIO(content)) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        text = '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns))
        # Fixed expectations derive from the synthetic dataset, not API statistics.
        valid, excluded = (25, 2) if revision == 1 else (26, 1)
        assert f'原始数据 27 行；有效完整记录 {valid} 行；排除 {excluded} 行。' in text
        assert ('项目类型：SCI 论文' if project['project_type'] == 'sci' else '项目类型：毕业论文') in text
        assert f'配置版本 {revision}' in text
        tables = [[[''.join(cell.itertext()) for cell in row.findall('w:tc', ns)]
                   for row in table.findall('w:tr', ns)] for table in root.findall('.//w:tbl', ns)]
        if revision == 1:
            assert tables[0][1] == ['总体', '25', '12.28', '7.00904', '1', '24']
            assert tables[0][2] == ['A', '24', '12.5', '7.07107', '1', '24']
            assert tables[0][3] == ['B', '1', '7', '无法计算', '7', '7']
            assert tables[1][1] == ['总体', '7', '12', '18', '11']
        else:
            assert tables[0][1] == ['总体', '26', '50.2308', '193.634', '1', '999']
            assert len(tables[0]) == len(tables[1]) == 2
            assert tables[1][1] == ['总体', '7', '12.5', '18.75', '11.75']
            assert '分组字段：不分组' in text
        for section in explanation['sections']:
            assert section['text'] in text
            for evidence in section['evidence']:
                assert f"{evidence['label']}：{evidence['value']}" in text
        for value in (project['id'], file['id'], file['sha256'], result['id'], figure['id'],
                      figure['sha256'], explanation['id'], report['id'], report['input_sha256']):
            assert value in text
        images = [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert len(images) == 1
        assert hashlib.sha256(images[0]).hexdigest() == figure['sha256']


@pytest.mark.parametrize('project_type', ['sci', 'thesis'])
def test_excel_to_word_versioned_workflow(client, cloud, writer, project_type):
    response = client.post('/api/v1/projects', json={
        'name': '完整小闭环验收', 'research_topic': '合成数据验收', 'project_type': project_type,
    })
    assert response.status_code == 201, response.text
    project = response.json()
    files_url = f"/api/v1/projects/{project['id']}/files"
    damaged = client.post(files_url, files={'file': ('损坏.xlsx', b'not an Excel workbook')})
    assert damaged.status_code == 201
    damaged_file = damaged.json()['file']
    assert damaged_file['parse_status'] == 'failed'
    assert damaged_file['error']['code'] == 'invalid_workbook' and damaged.json()['preview'] is None
    assert client.get(files_url + '/' + damaged_file['id'] + '/preview').status_code == 422
    content = workbook_bytes()
    uploaded = client.post(files_url, files={'file': ('闭环.xlsx', content)})
    assert uploaded.status_code == 201, uploaded.text
    file, preview = uploaded.json()['file'], uploaded.json()['preview']
    assert file['project_id'] == project['id']
    assert file['sha256'] == hashlib.sha256(content).hexdigest()
    base = files_url + '/' + file['id']
    assert client.get(base + '/preview').json() == preview
    assert [sheet['name'] for sheet in preview['sheets']] == ['数据', '空表']
    assert preview['sheets'][0]['row_count'] == 27
    assert preview['sheets'][0]['preview_rows'] == [[value, 'A'] for value in range(1, 21)]
    assert preview['sheets'][1]['row_count'] == 0 and preview['sheets'][1]['preview_rows'] == []
    profile = client.get(base + '/analysis-profile', params={'sheet': '数据'})
    assert profile.status_code == 200, profile.text
    assert profile.json()['row_count'] == 27
    assert profile.json()['columns'][0]['numeric_count'] == 26
    selection = {'task_type': 'descriptive_boxplot', 'sheet_name': '数据', 'numeric_column': 'A',
                 'group_column': 'B', 'unit': 'mg/L', 'missing_policy': 'exclude_selected_missing'}
    checked = client.post(base + '/analysis-check', json=selection)
    assert checked.status_code == 200, checked.text
    check = checked.json()
    assert check['ready'] and (check['row_count'], check['valid_count'], check['excluded_count']) == (27, 25, 2)
    assert check['groups'] == [{'label': 'A', 'count': 24}, {'label': 'B', 'count': 1}]
    configured = client.put(base + '/analysis-setup', json={**selection, 'expected_revision': 0})
    assert configured.status_code == 200, configured.text
    setup = configured.json()
    assert setup['revision'] == 1 and setup['source_sha256'] == file['sha256']
    assert setup['selection'] == selection and setup['check'] == check
    result_response = client.post(base + '/analysis-runs', json={'expected_revision': 1})
    assert result_response.status_code == 200, result_response.text
    result = result_response.json()
    overall = result['overall']
    assert (overall['n'], overall['median'], overall['q1'], overall['q3']) == (25, 12, 7, 18)
    assert overall['mean'] == pytest.approx(307 / 25)
    assert overall['std'] == pytest.approx(math.sqrt((4949 - 307 ** 2 / 25) / 24))
    assert result['groups'][0]['statistics']['n'] == 24
    assert result['groups'][0]['statistics']['std'] == pytest.approx(math.sqrt(50))
    assert result['groups'][1]['statistics']['n'] == 1 and result['groups'][1]['statistics']['std'] is None
    old_run = base + '/analysis-runs/' + result['id']
    assert client.post(old_run + '/report', json={'expected_revision': 1, 'figure_id': 'missing',
                                               'explanation_id': 'missing'}).status_code == 409
    figure = generate(client, old_run + '/boxplot')
    assert [(item['n'], item['q1'], item['median'], item['q3']) for item in figure['series']] == [
        (24, 6.75, 12.5, 18.25), (1, 7, 7, 7)]
    from app.adapters.storage import get_project_store
    old_payload = get_project_store().figure_job(result['id'], 'openai_boxplot_v1')['payload']
    assert len(old_payload['values']) == 25 and 999 not in old_payload['values']
    assert client.post(old_run + '/report', json={'expected_revision': 1, 'figure_id': figure['id'],
                                               'explanation_id': 'missing'}).status_code == 409
    assert submit(client, old_run + '/explanation', {**figure, 'id': 'wrong'}).status_code == 409
    assert submit(client, old_run + '/explanation', figure).status_code == 202
    explanation = client.get(old_run + '/explanation').json()['explanation']
    facts = {item['key']: item['value'] for section in explanation['sections'] for item in section['evidence']}
    assert {key: facts[key] for key in ('data.total', 'data.valid', 'data.excluded', 'overall.n',
                                      'overall.mean', 'overall.median', 'overall.q1', 'overall.q3')} == {
        'data.total': '27', 'data.valid': '25', 'data.excluded': '2', 'overall.n': '25',
        'overall.mean': '12.28', 'overall.median': '12', 'overall.q1': '7', 'overall.q3': '18'}
    for changes in ({'figure_id': 'wrong'}, {'explanation_id': 'wrong'}, {'expected_revision': 2}):
        assert export(client, old_run + '/report', figure, explanation, **changes).status_code == 409
    exported = export(client, old_run + '/report', figure, explanation)
    assert exported.status_code == 200, exported.text
    report = exported.json()['report']
    assert_bindings(project, file, result, figure, explanation, report, writer.calls[0])
    old_download = old_run + '/report/' + report['id'] + '/download'
    downloaded = client.get(old_download)
    assert downloaded.status_code == 200
    assert downloaded.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert 'attachment' in downloaded.headers['content-disposition']
    assert_docx(downloaded.content, project, file, result, figure, explanation, report, 1)

    updated = client.put(base + '/analysis-setup', json={**selection, 'group_column': None, 'expected_revision': 1})
    assert updated.status_code == 200, updated.text
    new_setup = updated.json()
    assert new_setup['revision'] == 2 and new_setup['check']['valid_count'] == 26
    assert client.post(base + '/analysis-runs', json={'expected_revision': 1}).status_code == 409
    assert client.post(old_run + '/boxplot', json={'expected_revision': 1}).status_code == 409
    assert submit(client, old_run + '/explanation', figure).status_code == 409
    assert export(client, old_run + '/report', figure, explanation).status_code == 409
    assert client.get(old_run + '/report').json()['report'] == report
    assert client.get(old_download).content == downloaded.content
    new_response = client.post(base + '/analysis-runs', json={'expected_revision': 2})
    assert new_response.status_code == 200, new_response.text
    new_result = new_response.json()
    assert new_result['id'] != result['id'] and new_result['overall']['n'] == 26
    assert new_result['overall']['mean'] == pytest.approx((307 + 999) / 26)
    assert new_result['overall']['std'] == pytest.approx(math.sqrt((4949 + 999 ** 2 - 1306 ** 2 / 26) / 25))
    assert new_result['groups'] == []
    new_run = base + '/analysis-runs/' + new_result['id']
    new_figure = generate(client, new_run + '/boxplot', revision=2)
    assert new_figure['id'] != figure['id'] and new_figure['series'][0]['fliers'] == [999]
    new_payload = get_project_store().figure_job(new_result['id'], 'openai_boxplot_v1')['payload']
    assert len(new_payload['values']) == 26 and 999 in new_payload['values']
    assert submit(client, new_run + '/explanation', figure).status_code == 409
    assert submit(client, new_run + '/explanation', new_figure).status_code == 202
    new_explanation = client.get(new_run + '/explanation').json()['explanation']
    assert new_explanation['id'] != explanation['id']
    assert export(client, new_run + '/report', figure, explanation).status_code == 409
    new_export = export(client, new_run + '/report', new_figure, new_explanation)
    assert new_export.status_code == 200, new_export.text
    new_report = new_export.json()['report']
    assert new_report['id'] != report['id']
    assert_bindings(project, file, new_result, new_figure, new_explanation, new_report, writer.calls[1])
    new_download = new_run + '/report/' + new_report['id'] + '/download'
    new_content = client.get(new_download).content
    assert_docx(new_content, project, file, new_result, new_figure, new_explanation, new_report, 2)
    assert client.get(old_download).content == downloaded.content

    # New client lifecycle, same isolated on-disk store: no setup or source reseeding.
    with TestClient(app, cookies=dict(client.cookies), headers=dict(client.headers)) as reopened:
        assert reopened.get(base + '/analysis-setup').json() == new_setup
        assert reopened.get(base + '/analysis-result').json()['result'] == new_result
        assert reopened.get(new_run + '/boxplot').json()['figure'] == new_figure
        assert reopened.get(new_run + '/explanation').json()['explanation'] == new_explanation
        assert reopened.get(new_run + '/report').json()['report'] == new_report
        assert reopened.get(new_download).content == new_content
        assert reopened.get(old_download).content == downloaded.content
        assert generate(reopened, new_run + '/boxplot', revision=2) == new_figure
        assert submit(reopened, new_run + '/explanation', new_figure).json()['explanation'] == new_explanation
        repeated = export(reopened, new_run + '/report', new_figure, new_explanation)
        assert repeated.status_code == 200 and repeated.json()['report'] == new_report
        other = reopened.post('/api/v1/projects', json={
            'name': '其他项目', 'research_topic': '隔离检查', 'project_type': project_type,
        }).json()
        foreign_base = base.replace(project['id'], other['id'])
        for url in (foreign_base + '/preview', foreign_base + '/analysis-setup', foreign_base + '/analysis-result',
                    new_run.replace(project['id'], other['id']) + '/boxplot',
                    new_run.replace(project['id'], other['id']) + '/explanation',
                    new_run.replace(project['id'], other['id']) + '/report',
                    new_download.replace(project['id'], other['id'])):
            assert reopened.get(url).status_code == 404
        assert reopened.get(new_run + '/report/' + report['id'] + '/download').status_code == 404
    # Historical figures were seeded; only the two new explanations submit.
    assert len(cloud.calls) == 0 and len(writer.calls) == 2
