"""Synthetic multiround retention scenario using real persisted API workflows."""
import argparse
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from xml.etree import ElementTree

from openpyxl import Workbook


def workbook_bytes() -> bytes:
    book = Workbook()
    book.active.title = '研究 & 数据'
    book.properties.created = book.properties.modified = datetime(2026, 1, 1)
    rows = [['说明'], [], [None, None, '处理组', '读数'], [None, None, '不选此行', 900],
            [None, None, ' A ', 1], [None, None, 'NA', 3], [None, None, ' A ', 5],
            [None, None, ' B ', 7], [None, None, ' B ', 9], [], ['边界标记']]
    for row in rows:
        book.active.append(row)
    raw, output = BytesIO(), BytesIO()
    book.save(raw)
    book.close()
    with ZipFile(raw) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            data = source.read(name)
            if name == 'docProps/core.xml':
                root = ElementTree.fromstring(data)
                for node in root:
                    if node.tag.endswith('}modified'):
                        node.text = '2026-01-01T00:00:00Z'
                data = ElementTree.tostring(root, encoding='utf-8')
            target.writestr(info, data)
    return output.getvalue()


def retention_snapshot():
    """Exact business rows and asset bytes; authentication last-seen is excluded."""
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    excluded = {'users', 'sessions', 'auth_login_attempts', 'session_revocations', 'password_recovery_codes'}
    with database_connection() as db:
        names = [r['tablename'] for r in db.execute(
            'SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename').fetchall()]
        rows = {name: sorted([dict(r) for r in db.execute('SELECT * FROM "'+name+'"').fetchall()], key=repr)
                for name in names if name not in excluded}
    assets = {str(p.relative_to(get_data_dir())): p.read_bytes() for p in get_data_dir().rglob('*') if p.is_file()}
    return rows, assets


def _assert_retained(before, after, *, project_id=None, expected_setup=None):
    """Only this project's timestamp and an explicitly saved setup may change."""
    for table, rows in before[0].items():
        for row in rows:
            if table == 'projects' and row['id'] == project_id:
                matches = [r for r in after[0][table] if r['id'] == row['id']]
                assert len(matches) == 1, ('old project missing', row['id'])
                current = matches[0]
                assert current['updated_at'] >= row['updated_at']
                assert {k:v for k,v in current.items() if k != 'updated_at'} == {
                    k:v for k,v in row.items() if k != 'updated_at'}
            elif table == 'analysis_setups' and expected_setup is not None and row['file_id'] == expected_setup['file_id']:
                matches = [r for r in after[0][table] if r['file_id'] == row['file_id']]
                assert len(matches) == 1
                assert {k:v for k,v in matches[0].items() if k != 'setup_json'} == {
                    k:v for k,v in expected_setup.items() if k != 'setup_json'}
                assert json.loads(matches[0]['setup_json']) == json.loads(expected_setup['setup_json'])
            else:
                # Includes complete files, budgets and unrelated project/setup rows.
                assert row in after[0][table], ('old row changed', table, row)
    for key, content in before[1].items():
        assert after[1].get(key) == content, ('old asset changed', key)


def _publish(client, base, raw, markers, key):
    from tests.integration.test_dataset_preparation import run, review, decide, decision
    response = client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults',
                          params={'header_row': 3, 'data_range': 'C5:D10'})
    assert response.status_code == 200, response.text
    recipe = response.json()['recipe']
    recipe['fields'][0].update(trim_text=True, missing_markers=markers)
    recipe['fields'][1].update(name='体重', unit=dict(status='confirmed', value='mg'))
    response = client.post(base+'/dataset-preparations', json=dict(dataset_id=raw['id'], recipe=recipe),
                           headers={'Idempotency-Key': key})
    assert response.status_code == 202, response.text
    task = response.json()
    assert run(task)['status'] == 'waiting_confirmation'
    accepted = decide(client, task, decision(review(client, task)), key+'-approve')
    assert accepted.status_code == 202, accepted.text
    assert run(accepted.json())['status'] == 'succeeded'
    return review(client, task)['result']


def create_retention_scenario(client, monkeypatch) -> dict:
    from app.adapters.storage import ProjectStore
    from app.adapters.task_execution_store import ExecutionAssets
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from tests.api.test_analysis import selection
    from tests.api.test_dataset_analysis import version, forbid_original
    from tests.browser.task_browser_support import block_real_providers
    from tests.integration import test_dataset_artifact_chain as chain_helper
    original_reader, execution_reader = ProjectStore.original, ExecutionAssets.original
    attempts = block_real_providers(monkeypatch)
    content = workbook_bytes()
    project = client.post('/api/v1/projects', json=dict(name='多轮版本保留专项', research_topic='合成数据', project_type='sci')).json()
    upload = client.post('/api/v1/projects/'+project['id']+'/files', files={'file': ('version-retention.xlsx', content)})
    assert upload.status_code == 201, upload.text
    file = upload.json()['file']
    base = '/api/v1/projects/'+project['id']+'/files/'+file['id']
    r1 = version(client, base)
    p1 = _publish(client, base, r1, ['NA'], 'p1')
    selected = selection(dataset_id=p1['id'], expected_revision=0, numeric_column='D', group_column='C', unit='mg')
    saved_initial = client.put(base+'/analysis-setup', json=selected)
    assert saved_initial.status_code == 200, saved_initial.text
    initial_setup = saved_initial.json()
    response = client.post(base+'/analysis-runs', json={'expected_revision': 1})
    assert response.status_code == 200, response.text
    old = response.json()
    with monkeypatch.context() as artifacts:
        artifacts.setattr(chain_helper, 'new_result', lambda _: (base, file, old))
        chain = chain_helper.complete_chain(client, artifacts)
    with database_connection() as db:
        tasks = {r['task_type']: json.loads(json.dumps(dict(r), default=str)) for r in
                 db.execute("SELECT * FROM tasks WHERE task_type IN ('boxplot','explanation','word_report')").fetchall()}
    urls = {'figure': base+'/analysis-runs/'+old['id']+'/figures/'+chain['figure']['id']+'/download',
            'explanation': base+'/analysis-runs/'+old['id']+'/explanation', 'report': chain['report_url'],
            'workspaces': {kind: '/api/v1/tasks/'+task['id']+'/workspace' for kind, task in tasks.items()}}
    downloads = {}
    for kind, url in urls.items():
        if kind != 'workspaces':
            response = client.get(url)
            assert response.status_code == 200, response.text
            downloads[kind] = response.content
    original = client.get(base+'/download')
    assert original.status_code == 200 and original.content == content
    evidence = []
    previous = retention_snapshot()
    def checkpoint(stage):
        nonlocal previous
        current = retention_snapshot()
        _assert_retained(previous, current, project_id=project['id'])
        assert client.get(base+'/analysis-setup').json() == initial_setup
        for url in urls['workspaces'].values():
            view = client.get(url)
            assert view.status_code == 200, view.text
            assert view.json()['source']['is_current']
            assert view.json()['source']['dataset_source'] == old['source']
        evidence.append(dict(stage=stage, retained_rows=sum(len(v) for k,v in previous[0].items()
            if k != 'projects'), retained_assets=len(previous[1])))
        previous = current
    # Persisted consumers must never fall back to the uploaded workbook.
    with monkeypatch.context() as persisted:
        persisted.setattr(ProjectStore, 'original', forbid_original)
        persisted.setattr(ExecutionAssets, 'original', forbid_original)
        with monkeypatch.context() as extraction:
            extraction.setattr(ProjectStore, 'original', original_reader)
            extraction.setattr(ExecutionAssets, 'original', execution_reader)
            r2 = version(client, base, 1)
        checkpoint('R2')
        p2 = _publish(client, base, r2, ['NA', 'B'], 'p2')
        checkpoint('P2')
        with monkeypatch.context() as extraction:
            extraction.setattr(ProjectStore, 'original', original_reader)
            extraction.setattr(ExecutionAssets, 'original', execution_reader)
            r3 = version(client, base, 2)
        checkpoint('R3')
        saved = client.put(base+'/analysis-setup', json=selection(dataset_id=p2['id'], expected_revision=1,
            numeric_column='D', group_column='C', unit='mg'))
        assert saved.status_code == 200, saved.text
        saved_setup = saved.json()
        assert saved_setup['revision'] == 2
        assert saved_setup['source'] == p2['source']
        assert saved_setup['selection'] == initial_setup['selection']
        expected_setup = dict(file_id=file['id'], revision=2,
            setup_json=json.dumps(saved_setup, ensure_ascii=False, allow_nan=False))
        assert client.get(base+'/analysis-setup').json() == saved_setup
        response = client.post(base+'/analysis-runs', json={'expected_revision': 2})
        assert response.status_code == 200, response.text
        new = response.json()
        current = retention_snapshot()
        _assert_retained(previous, current, project_id=project['id'], expected_setup=expected_setup)
        evidence.append(dict(stage='select-P2', retained_assets=len(previous[1])))
        before_reads = current
        for kind, url in urls['workspaces'].items():
            response = client.get(url)
            assert response.status_code == 200, response.text
            view = response.json()
            assert not view['source']['is_current']
            assert view['source']['dataset_source'] == old['source']
            assert view['task']['input_version']['source'] == old['source']
        for kind, expected in downloads.items():
            response = client.get(urls[kind])
            assert response.status_code == 200, response.text
            if kind == 'explanation':
                historical = response.json()
                initial = json.loads(expected)
                assert initial.pop('is_current') is True
                assert historical.pop('is_current') is False
                assert initial.pop('current_revision') == 1
                assert historical.pop('current_revision') == 2
                assert historical == initial
                assert historical['explanation'] == chain['explanation']
            else:
                assert response.content == expected, kind
        with monkeypatch.context() as original_download:
            original_download.setattr(ProjectStore, 'original', original_reader)
            response = client.get(base+'/download')
            assert response.status_code == 200 and response.content == content
        assert retention_snapshot() == before_reads
    with database_connection() as db:
        audit = audit_database(db)
        calls = db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']
    assert audit['ok'], audit
    assert attempts == []
    assert all(task['input_snapshot']['result'] == old for task in tasks.values())
    return dict(base=base, project_id=project['id'], file=file, raws=[r1,r2,r3], prepared=[p1,p2],
                old_result=old, new_result=new, old_tasks=tasks, historical_urls=urls,
                stage_evidence=evidence, provider_attempts=attempts, synthetic_model_calls=calls)




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    destination = Path(parser.parse_args().output_dir)
    if not destination.is_absolute():
        parser.error('--output-dir must be absolute')
    from app.adapters.excel_structure import extract_excel_structure
    from app.core.config import ExcelSettings
    content = workbook_bytes()
    started = perf_counter()
    extract_excel_structure(content, 'version-retention.xlsx', ExcelSettings())
    elapsed = perf_counter()-started
    destination.mkdir(parents=True, exist_ok=False)
    (destination/'version-retention.xlsx').write_bytes(content)
    manifest = dict(filename='version-retention.xlsx', size_bytes=len(content), sha256=sha256(content).hexdigest(),
                    structure_parse_seconds=elapsed, expected=dict(raw_versions=[1,2,3], prepared_versions=[1,1], old_n=4, old_mean=5.5, new_n=2, new_mean=3))
    (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination/'验收说明.txt').write_text('唯一工作表研究 & 数据；表头第3行，整理区域C5:D10，共6行。\nP1绑定R1（原始v1/整理v1）：C trim且NA转缺失，有效4、排除2、均值5.5。\n重解析R2，再发布P2绑定R2（原始v2/整理v1）：NA和B转缺失，有效2、排除4、均值3。\nP1/P2代表两次发布的先后标签，整理编号按原始父版本分别从1开始。\n再次重解析R3后显式选择P2；旧图表、解释、Word仍属于R1/P1且可下载。\n合成图表/解释不代表真实模型质量；本机解析耗时不代表容量或队列性能。\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
