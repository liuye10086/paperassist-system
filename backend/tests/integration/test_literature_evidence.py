"""Actual saved synthetic bytes and PostgreSQL claim/evidence invariants."""
import copy
import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature_evidence import post, claim
from tests.helpers.literature_evidence import seeded


def setup(client, kind='sci'):
    pid, search_id, reference = seeded(client, kind)
    path = f'/api/v1/projects/{pid}/literature/evidence'
    item = claim(client, path)
    body = dict(claim_revision=1, project_reference_id=reference['id'], source_kind='abstract',
        search_id=search_id, quote='Synthetic protocol fixture')
    return pid, path, item, reference, body


@pytest.mark.parametrize('kind', ['sci', 'thesis'])
def test_exact_abstract_quote_history_four_statuses_and_actor(client, kind):
    pid, path, item, reference, body = setup(client, kind)
    endpoint = path+'/claims/'+item['id']
    forged = post(client, endpoint+'/evidence', {**body, 'quote': 'Invented outcome'}, 'forged')
    assert forged.status_code == 422, forged.text
    assert post(client, endpoint+'/evidence', {k:v for k,v in body.items() if k!='search_id'}, 'missing').status_code == 422
    response = post(client, endpoint+'/evidence', body, 'quote')
    assert response.status_code == 201, response.text
    evidence = response.json()
    assert evidence['reading_scope'] == 'abstract'
    assert evidence['source']['search_id'] == body['search_id']
    assert evidence['location']['abstract_index'] == 0
    assert post(client, endpoint+'/evidence', body, 'quote').json() == evidence
    review = dict(claim_revision=1, project_reference_id=reference['id'], evidence_ids=[evidence['id']],
        status='supported', relevance='related', reason='Synthetic manual annotation', narrowed_statement='', limitations='Abstract only')
    for status in ('supported', 'partial', 'unsupported', 'needs_review'):
        result = post(client, endpoint+'/reviews', {**review, 'status': status,
            'narrowed_statement': 'Synthetic bounded statement' if status=='partial' else ''}, status)
        assert result.status_code == 201, result.text
        assert result.json()['decided_by']
    assert post(client, endpoint+'/reviews', {**review, 'status': 'partial'}, 'partial-invalid').status_code == 422
    assert post(client, endpoint+'/reviews', {**review, 'relevance': 'unrelated'}, 'unrelated').status_code == 422
    assert post(client, endpoint+'/reviews', {**review, 'evidence_ids': []}, 'no-source').status_code == 422
    assert post(client, endpoint+'/reviews', {**review, 'evidence_ids': [], 'status': 'needs_review'}, 'no-source-wait').status_code == 201
    assert client.get(endpoint+'/reviews').json()['total'] == 5
    assert post(client, endpoint+'/versions', dict(expected_revision=1, content='New content', context='', output_language='en'), 'v2').status_code == 201
    assert client.get(endpoint+'/reviews').json()['total'] == 0
    assert client.get(endpoint+'/reviews?revision=1').json()['total'] == 5
    assert post(client, endpoint+'/reviews', review, 'stale').status_code == 409
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_saved_abstract_tampering_and_stale_model_snapshot_fail_closed(client):
    pid, path, item, reference, body = setup(client)
    endpoint = path+'/claims/'+item['id']
    evidence = post(client, endpoint+'/evidence', body, 'quote').json()
    from app.domain.literature_evidence.service import LiteratureEvidenceService
    # Use the authenticated identity already scoped to this project.
    from app.adapters.storage import ProjectStore
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (pid,)).fetchone()['owner_id']
    from app.core.config import get_data_dir
    service = LiteratureEvidenceService(ProjectStore(get_data_dir(), owner_id=owner))
    snapshot = service.assistance_snapshot(pid, dict(claim_id=item['id'], claim_revision=1,
        project_reference_id=reference['id'], evidence_ids=[evidence['id']], output_language='en'))
    # Display-only response additions must not change already frozen model-task sources.
    assert set(snapshot['reference']['source']) == {'search_id', 'receipt_id', 'query', 'effective_query',
        'retrieved_at', 'source_kind', 'cached', 'ordinal', 'source_download_url'}
    frozen = copy.deepcopy(snapshot)
    frozen['reference']['source'].pop('source_context', None)
    service.assert_assistance_inputs_current(pid, frozen)
    service.assert_assistance_inputs_current(pid, snapshot)
    with database_connection(write=True) as db:
        hit = db.execute('SELECT * FROM literature_search_hits WHERE project_reference_id=%s', (reference['id'],)).fetchone()
        record = copy.deepcopy(hit['record_json']); record['abstract'][0]['text'] = 'Changed stored abstract'
        db.execute('UPDATE literature_search_hits SET record_json=%s WHERE id=%s', (Jsonb(record), hit['id']))
    assert client.get(endpoint+'/evidence').status_code == 409
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        service.assert_assistance_inputs_current(pid, snapshot)


def test_missing_materials_is_needs_review_and_cross_reference_quote_is_rejected(client):
    pid, path, item, reference, body = setup(client)
    endpoint = path+'/claims/'+item['id']
    others = client.get(f'/api/v1/projects/{pid}/literature/references').json()['items']
    missing = next(r for r in others if r['id'] != reference['id'])
    assert post(client, endpoint+'/evidence', {**body, 'project_reference_id': missing['id']}, 'empty-abstract').status_code == 422
    review = dict(claim_revision=1, project_reference_id=missing['id'], evidence_ids=[], status='needs_review',
        relevance='uncertain', reason='No abstract acquired', narrowed_statement='', limitations='Missing data')
    assert post(client, endpoint+'/reviews', review, 'wait').status_code == 201


def test_evidence_page_projects_bibliography_for_reference_outside_first_page(client):
    from tests.api.test_literature import project, create
    from tests.helpers.literature import SyntheticNcbi
    from app.domain.literature.execution import run_literature_task
    pid = project(client)
    task = create(client, pid).json()
    assert run_literature_task(task['id'], 1, client=SyntheticNcbi(20))['status'] == 'succeeded'
    first = client.get(f'/api/v1/projects/{pid}/literature/references?page=1').json()
    later = client.get(f'/api/v1/projects/{pid}/literature/references?page=2').json()
    assert first['total'] == 20 and later['items']
    reference = next(r for r in later['items'] if r['record']['abstract'])
    assert reference['id'] not in {r['id'] for r in first['items']}
    path = f'/api/v1/projects/{pid}/literature/evidence'
    item = claim(client, path)
    endpoint = path+'/claims/'+item['id']+'/evidence'
    saved = post(client, endpoint, dict(claim_revision=1, project_reference_id=reference['id'],
        source_kind='abstract', search_id=task['id'], quote='Synthetic protocol fixture'), 'later-page').json()
    page = client.get(endpoint).json()
    assert page['items'][0]['id'] == saved['id']
    assert page['items'][0]['bibliography'] == dict(title=reference['record']['title'], pmid=reference['pmid'])


def seed_reference(client, pid):
    from tests.api.test_literature import create
    from tests.helpers.literature import SyntheticNcbi
    from app.domain.literature.execution import run_literature_task
    task = create(client, pid).json()
    assert run_literature_task(task['id'], 1, client=SyntheticNcbi(2))['status']=='succeeded'
    return client.get(f'/api/v1/projects/{pid}/literature/references').json()['items'][0]


def test_user_docx_material_freezes_actual_item_and_detects_original_tampering(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    from app.core.config import get_data_dir
    from app.maintenance.literature_evidence_audit import audit_literature_evidence
    project, _, _, uploaded, original = uploaded_docx(client)
    pid = project['id']; reference = seed_reference(client, pid)
    assert run_parse_file_task(uploaded['task']['id'], 1, parser=parse_docx)['status']=='succeeded'
    path = f'/api/v1/projects/{pid}/literature/evidence'
    options = client.get(path+'/material-options')
    assert options.status_code == 200, options.text
    option = options.json()['items'][0]
    version = option['versions'][0]
    body = dict(project_reference_id=reference['id'], file_id=uploaded['file_id'], source_kind=version['kind'],
        version_id=version['version_id'], source_description='User supplied synthetic DOCX', match_note='Manually matched synthetic bibliography')
    response = post(client, path+'/materials', body, 'material')
    assert response.status_code == 201, response.text
    material = response.json()
    source = client.get(path+'/materials/'+material['id']+'/source').json()
    selected = next(i for i in source['items'] if i['kind']=='text' and i.get('text'))
    item = claim(client, path)
    endpoint = path+'/claims/'+item['id']
    quote = dict(claim_revision=1, project_reference_id=reference['id'], source_kind='material',
        material_id=material['id'], item_id=selected['id'], quote=selected['text'])
    response = post(client, endpoint+'/evidence', quote, 'quote')
    assert response.status_code == 201, response.text
    frozen = response.json()
    assert frozen['reading_scope']=='user_material' and frozen['location']['item_id']==selected['id']
    assert frozen['source']['sha256']==material['source']['sha256']
    assert post(client, endpoint+'/evidence', {**quote, 'item_id':'invented'}, 'invented').status_code==422
    with database_connection() as db:
        checks = audit_literature_evidence(db)
        assert all(c['invalid']==0 for c in checks), checks
        file = db.execute('SELECT * FROM files WHERE id=%s', (uploaded['file_id'],)).fetchone()
    from pathlib import Path
    path_object = Path(get_data_dir()) / file['object_key']
    path_object.write_bytes(b'changed actual bytes')
    assert client.get(endpoint+'/evidence').status_code==409
    with database_connection() as db:
        assert any(c['invalid'] for c in audit_literature_evidence(db))


def test_unreadable_ocr_does_not_become_supporting_evidence(client):
    from tests.integration.test_ocr_review import setup_review, execute, decide
    project, file_base, parent, task, _ = setup_review(client)
    pid = project['id']; reference = seed_reference(client, pid)
    assert execute(task)['status']=='waiting_confirmation'
    review_url = '/api/v1/tasks/'+task['id']+'/ocr-review'
    revised = decide(client, client.get(review_url).json(), 'revise', 'unreadable', [dict(block_id='text-1', action='unreadable')])
    assert execute(revised.json())['status']=='waiting_confirmation'
    approved = decide(client, client.get(review_url).json(), 'approve', 'approve')
    assert execute(approved.json())['status']=='succeeded'
    version = client.get(review_url).json()['result']
    path = f'/api/v1/projects/{pid}/literature/evidence'
    body = dict(project_reference_id=reference['id'], file_id=file_base.split('/')[-1], source_kind='ocr_review_version',
        version_id=version['id'], source_description='Synthetic OCR fixture', match_note='Manually matched')
    response = post(client, path+'/materials', body, 'ocr-material')
    assert response.status_code == 201, response.text
    item = claim(client, path)
    quote = dict(claim_revision=1, project_reference_id=reference['id'], source_kind='material',
        material_id=response.json()['id'], item_id='text-1', quote='invented readable value')
    assert post(client, path+'/claims/'+item['id']+'/evidence', quote, 'unreadable-quote').status_code==422


def test_supplement_rolls_back_task_when_link_insert_fails(client):
    pid, path, item, reference, body = setup(client)
    from app.db.database import migration_connection
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_supplement() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic link failure'; END $$""")
        db.execute('CREATE TRIGGER reject_link BEFORE INSERT ON literature_claim_supplements FOR EACH ROW EXECUTE FUNCTION reject_supplement()')
    response = post(client, path+'/claims/'+item['id']+'/supplement', dict(claim_revision=1, query='fixture', reason='Synthetic'), 'rollback')
    assert response.status_code >= 500
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks WHERE idempotency_key LIKE %s', ('claim-supplement:%',)).fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM literature_claim_supplements').fetchone()['n']==0


def test_other_owner_cannot_read_or_write_claim_material_or_history(client):
    from tests.integration.test_project_ownership import account_client
    pid, path, item, reference, body = setup(client)
    with account_client('evidence-intruder@example.test')[0] as other:
        assert other.get(path+'/claims').status_code==404
        assert other.get(path+'/claims/'+item['id']).status_code==404
        assert other.get(path+'/claims/'+item['id']+'/evidence').status_code==404
        assert other.get(path+'/materials').status_code==404
        assert other.get(path+'/material-options').status_code==404
        assert post(other, path+'/claims/'+item['id']+'/evidence', body, 'intruder').status_code==404


def test_supplement_audit_normalizes_query_without_changing_original_request_or_replay(client):
    from tests.api.test_literature_evidence import base
    from app.maintenance.literature_evidence_audit import audit_literature_evidence
    path = base(client)
    item = claim(client, path)
    endpoint = path+'/claims/'+item['id']+'/supplement'
    body = dict(claim_revision=1, query='  fixture[Title]  ', reason='Synthetic missing evidence')
    response = post(client, endpoint, body, 'spaces')
    assert response.status_code==202, response.text
    replay = post(client, endpoint, body, 'spaces')
    assert replay.status_code==200 and replay.json()==response.json()
    with database_connection() as db:
        link = db.execute('SELECT * FROM literature_claim_supplements WHERE claim_id=%s', (item['id'],)).fetchone()
        search = db.execute('SELECT * FROM literature_searches WHERE task_id=%s', (link['task_id'],)).fetchone()
        assert link['request_json']==body  # Original request and its replay digest remain unchanged.
        assert search['input_json']['query']=='fixture[Title]'
        checks = audit_literature_evidence(db)
        assert all(check['invalid']==0 for check in checks), checks
