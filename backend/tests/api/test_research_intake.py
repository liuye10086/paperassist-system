import pytest
from fastapi.testclient import TestClient
from app.main import app
from tests.helpers.auth import login_test_client


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield login_test_client(value)


def research(client, key='research-one'):
    response = client.post('/api/v1/projects', headers={'Idempotency-Key':key}, json={
        'name':'研究', 'research_topic':'空间表达', 'project_type':'research', 'delivery_kinds':['analysis','sci_draft']})
    assert response.status_code == 201, response.text
    return response.json()


def test_research_creation_replay_and_request_lookup(client):
    p = research(client)
    replay = client.post('/api/v1/projects', headers={'Idempotency-Key':'research-one'}, json={
        'name':'研究', 'research_topic':'空间表达', 'project_type':'research', 'delivery_kinds':['analysis','sci_draft']})
    assert replay.status_code == 200
    assert replay.json()['id'] == p['id']
    assert client.get('/api/v1/project-create-requests/research-one').json()['id'] == p['id']
    result = client.get(f"/api/v1/projects/{p['id']}/research-intake")
    assert result.status_code == 200, result.text
    assert result.json()['current_requirement'] is None
    assert {r['kind'] for r in result.json()['deliveries']} == {'analysis','sci_draft'}
    assert result.json()['capabilities']['legacy_writing'] is False


def test_requirement_versions_conflict_and_idempotency(client):
    p = research(client)
    base = f"/api/v1/projects/{p['id']}"
    body = {'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis']},'material_refs':[]}
    first = client.post(base+'/requirements', headers={'Idempotency-Key':'save-one'}, json=body)
    assert first.status_code == 201, first.text
    assert first.json()['revision'] == 2
    assert first.json()['version']['version'] == 1
    assert client.post(base+'/requirements', headers={'Idempotency-Key':'save-one'}, json=body).json() == first.json()
    assert client.post(base+'/requirements', headers={'Idempotency-Key':'save-two'}, json=body).status_code == 409
    body['content']['notes'] = 'changed'
    assert client.post(base+'/requirements', headers={'Idempotency-Key':'save-one'}, json=body).status_code == 409
    assert client.get(base+'/requirements').json()['total'] == 1
    old = client.get(base+'/requirements/'+first.json()['version']['id']).json()
    assert old['content']['notes'] == ''


def test_design_validation_and_pending_donor_gaps(client):
    p = research(client)
    base = f"/api/v1/projects/{p['id']}"
    content = {'schema_version':1,'experiments':[{'id':'e','data_type':'spatial'}],
               'groups':[{'id':'g','experiment_id':'e','name':'病例'}],
               'samples':[{'id':'s','experiment_id':'e','group_id':'g'}]}
    body = {'expected_revision':1,'operation':'save','content':content,'material_refs':[]}
    saved = client.post(base+'/research-designs',headers={'Idempotency-Key':'design-one'},json=body)
    assert saved.status_code == 201, saved.text
    assert any('donor' in gap['path'] for gap in saved.json()['gaps'])
    content['samples'].append(dict(content['samples'][0]))
    body['expected_revision'] = 2
    assert client.post(base+'/research-designs',headers={'Idempotency-Key':'design-two'},json=body).status_code == 422


def test_confirmation_keeps_old_version_and_pending_locator(client):
    p=research(client);base=f"/api/v1/projects/{p['id']}"
    body={'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis']},
          'material_refs':[{'availability':'pending','purpose':'protocol','locator':'Z:/does-not-exist/protocol.docx'}]}
    saved=client.post(base+'/requirements',headers={'Idempotency-Key':'draft'},json=body)
    assert saved.status_code==201,saved.text
    recovered=client.get(base+'/requirements/requests/draft')
    assert recovered.status_code==200,recovered.text
    body.update(expected_revision=2,operation='confirm')
    body['content']=saved.json()['version']['content']
    body['material_refs']=recovered.json()['material_refs']
    confirmed=client.post(base+'/requirements',headers={'Idempotency-Key':'confirm'},json=body)
    assert confirmed.status_code==201,confirmed.text
    assert confirmed.json()['version']['parent_id']==saved.json()['version']['id']
    assert confirmed.json()['version']['operation']=='confirm'
    assert confirmed.json()['version']['version']==2
    assert client.get(base+'/requirements/'+saved.json()['version']['id']).json()['operation']=='save'
    assert client.get(base+'/research-intake').json()['revision']==3
    assert confirmed.json()['version']['confirmed'] is True
    assert confirmed.json()['version']['blocking_gaps']


def test_material_references_cannot_bind_another_project(client):
    from tests.api.test_projects import upload
    first=research(client);second=research(client,key='research-two')
    uploaded=upload(client,second['id'])
    assert uploaded.status_code==201,uploaded.text
    reference={'availability':'provided','purpose':'raw_data','file_id':uploaded.json()['file']['id']}
    base=f"/api/v1/projects/{first['id']}"
    body={'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis']},'material_refs':[reference]}
    result=client.post(base+'/requirements',headers={'Idempotency-Key':'cross-project'},json=body)
    assert result.status_code==422,result.text
    assert client.get(base+'/requirements').json()['total']==0


def test_design_table_preview_reports_duplicate_and_unknown_group_without_writing(client):
    p=research(client);base=f"/api/v1/projects/{p['id']}"
    response=client.post(base+'/design-table-preview',json={
        'format':'csv','text':'Sample,Group,Donor\ns1,g,\ns1,g,d1\ns2,missing,d2\n',
        'mapping':{'id':'Sample','group_id':'Group','donor':'Donor'},'experiment_id':'e','group_ids':['g']})
    assert response.status_code==200,response.text
    assert len(response.json()['samples'])==1
    assert len(response.json()['conflicts'])==2
    assert response.json()['samples'][0]['donor']['state']=='pending'
    assert client.get(base+'/research-designs').json()['total']==0


def test_other_owner_cannot_read_intake_or_creation_result(client):
    from app.auth.service import create_user
    p=research(client)
    create_user('second-intake@example.invalid','isolated-password-2026')
    with TestClient(app) as other:
        other.headers.update({'X-PaperAssist-Client':'web','Origin':'http://testserver'})
        logged=other.post('/api/v1/auth/login',json={'email':'second-intake@example.invalid','password':'isolated-password-2026'})
        assert logged.status_code==200,logged.text
        other.headers['X-CSRF-Token']=logged.json()['csrf_token']
        for path in [f"/api/v1/projects/{p['id']}/research-intake",f"/api/v1/projects/{p['id']}/requirements",'/api/v1/project-create-requests/research-one']:
            denied=other.get(path)
            assert denied.status_code==404,(path,denied.text)


def test_research_summary_keeps_unopened_manuscript_capabilities_unavailable(client):
    project=research(client)
    response=client.get(f"/api/v1/projects/{project['id']}/summary")
    assert response.status_code==200,response.text
    summary=response.json()
    assert summary['project_type']=='research'
    assert summary['future']['writing']['state']=='not_available'
    assert summary['future']['revision']['state']=='not_available'
    assert summary['future']['sci'] is None and summary['future']['thesis'] is None


def test_design_table_plural_rejects_extra_columns_and_malformed_csv(client):
    p=research(client);base=f"/api/v1/projects/{p['id']}"
    body={'format':'csv','text':'id,group_id\ns1,g\n','mapping':{'id':'id','group_id':'group_id'},'experiment_id':'e','group_ids':['g']}
    response=client.post(base+'/design-table-previews',json=body)
    assert response.status_code==200,response.text
    body['text']='id,group_id\ns1,g,unexpected\n'
    assert client.post(base+'/design-table-previews',json=body).status_code==422
    body['text']='id,group_id\n"unterminated,g\n'
    assert client.post(base+'/design-table-previews',json=body).status_code==422


def test_design_table_from_uploaded_parsed_xlsx_is_complete_and_read_only(client):
    from io import BytesIO
    from openpyxl import Workbook
    workbook=Workbook();sheet=workbook.active;sheet.title='Samples'
    sheet.append(['Sample','Group','Donor'])
    for index in range(25):sheet.append([f's{index}','g',f'd{index}'])
    stream=BytesIO();workbook.save(stream);workbook.close()
    p=research(client);base=f"/api/v1/projects/{p['id']}"
    uploaded=client.post(base+'/files',files={'file':('sample-sheet.xlsx',stream.getvalue())})
    assert uploaded.status_code==201,uploaded.text
    identifier=uploaded.json()['file']['id']
    body={'file_id':identifier,'sheet':'Samples','mapping':{'id':'Sample','group_id':'Group','donor':'Donor'},'experiment_id':'e','group_ids':['g']}
    response=client.post(base+'/design-table-previews',json=body)
    assert response.status_code==200,response.text
    assert len(response.json()['samples'])==25
    assert response.json()['source']['file_id']==identifier
    assert all(sample['file_id']==identifier for sample in response.json()['samples'])
    assert client.get(base+'/research-designs').json()['total']==0


def test_new_versions_respect_deletion_barrier_but_read_replay_remains_available(client):
    from app.db.database import database_connection
    from uuid import uuid4
    p=research(client);base=f"/api/v1/projects/{p['id']}"
    body={'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis']}}
    first=client.post(base+'/requirements',headers={'Idempotency-Key':'before-barrier'},json=body)
    assert first.status_code==201,first.text
    with database_connection(write=True) as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(p['id'],)).fetchone()['owner_id']
        db.execute('''INSERT INTO storage_deletion_operations(id,project_id,owner_id,scope_kind,reason,manifest,manifest_sha256,state)
            VALUES(%s,%s,%s,'project','synthetic barrier only','{}'::jsonb,%s,'partial_retained')''',(str(uuid4()),p['id'],owner,'a'*64))
    replay=client.post(base+'/requirements',headers={'Idempotency-Key':'before-barrier'},json=body)
    assert replay.json()==first.json()
    body['expected_revision']=2
    blocked=client.post(base+'/requirements',headers={'Idempotency-Key':'after-barrier'},json=body)
    assert blocked.status_code==409,blocked.text
    assert blocked.json()['detail']['code']=='storage_deletion_pending'
    assert client.get(base+'/requirements').json()['total']==1
