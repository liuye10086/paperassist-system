"""Minimal new approvals and exact legacy group rules, synthetic local DB only."""
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.domain.manuscript_writing.bundle import build_bundle
from app.domain.manuscript_writing.frozen import contract as frozen_contract
from tests.api.test_manuscript_writing_live import client, preview, request_v2, LiveFixture
from tests.api.test_admin_configurations import accounts, admin, baseline, saved, validated, switch
from tests.api.test_literature_evidence import post


def grant_body(bundle, count):
    return dict(schema_version=2, confirmed=True, tasks=[dict(logical_task_id=f'actual-{i}',
        bundles=[dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])]) for i in range(count)])


@pytest.mark.parametrize('count',[1,2,4])
def test_new_preview_can_authorize_only_actual_selected_task_groups(client,count):
    root,bundle=preview(client)
    assert bundle['execution_contract']['schema_version']==2
    path=root.split('/manuscripts/')[0]+'/writing-authorizations'
    response=post(client,path,grant_body(bundle,count),'actual-selected')
    assert response.status_code==201,response.text
    result=response.json();assert len(result['manifest']['tasks'])==count
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def insert_legacy_copy(bundle):
    """Create a separate historical fixture row; never update an immutable bundle."""
    with database_connection(write=True) as db:
        row=dict(db.execute('SELECT * FROM manuscript_writing_bundles WHERE id=%s',(bundle['id'],)).fetchone())
        old=row['bundle_json'];data=build_bundle(old['base_snapshot'],old['request_json'])
        data.update(base_snapshot=old['base_snapshot'],request_json=old['request_json'])
        identity=str(uuid4())
        db.execute('''INSERT INTO manuscript_writing_bundles(id,project_id,user_id,manuscript_id,base_version_id,
            request_key,request_digest,bundle_sha256,bundle_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (identity,row['project_id'],row['user_id'],row['manuscript_id'],row['base_version_id'],
             'legacy-fixture-'+identity,row['request_digest'],data['bundle_sha256'],Jsonb(data),row['created_at']))
    return dict(id=identity,bundle_sha256=data['bundle_sha256'])


def test_legacy_and_mixed_bundles_keep_four_group_requirement(client):
    root,new=preview(client);old=insert_legacy_copy(new)
    path=root.split('/manuscripts/')[0]+'/writing-authorizations'
    assert post(client,path,grant_body(old,2),'old-two').status_code==422
    mixed=grant_body(new,2);mixed['tasks'][1]['bundles']=[dict(bundle_id=old['id'],bundle_sha256=old['bundle_sha256'])]
    assert post(client,path,mixed,'mixed-two').status_code==422
    assert post(client,path,grant_body(old,4),'old-four').status_code==201
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_bound_schema1_preview_survives_new_default_and_configuration_switch(admin,client,monkeypatch):
    config=baseline(admin);validated(admin,config);assert switch(admin,config,0,'legacy-config').status_code==200
    import app.domain.manuscript_writing.authorization as authorization
    with monkeypatch.context() as patch:
        patch.setattr(authorization,'contract',lambda version=None,**kwargs:frozen_contract(version,schema_version=1))
        root,old=preview(client)
    assert old['execution_contract']['schema_version']==1
    assert client.get(root+'/writing-previews/'+old['id']).json()==old
    path=root.split('/manuscripts/')[0]+'/writing-authorizations'
    assert post(client,path,grant_body(old,2),'old-bound-two').status_code==422
    granted=post(client,path,grant_body(old,4),'old-bound-four')
    assert granted.status_code==201,granted.text
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_schema1_authorized_fake_post_keeps_original_wire_after_new_configuration(admin,client,monkeypatch):
    one=saved(admin,baseline(admin),'prompts','writing_instruction','Original frozen instruction.')
    validated(admin,one);assert switch(admin,one,0,'one').status_code==200
    import app.domain.manuscript_writing.authorization as authorization
    with monkeypatch.context() as patch:
        patch.setattr(authorization,'contract',lambda version=None,**kwargs:frozen_contract(version,schema_version=1))
        root,old=preview(client)
    path=root.split('/manuscripts/')[0]+'/writing-authorizations'
    auth=post(client,path,grant_body(old,4),'legacy-frozen-grant').json()
    two=saved(admin,one,'prompts','writing_instruction','A different new instruction.')
    validated(admin,two);assert switch(admin,two,1,'two').status_code==200
    body=request_v2(old,auth);body['logical_task_id']='actual-0'
    response=post(client,root+'/writing-requests',body,'legacy-after-switch')
    assert response.status_code==202,response.text
    task=response.json()['task']
    from tests.helpers.tasks import task_owner
    from app.domain.model_usage.service import ModelUsageService
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    usage=ModelUsageService(task_owner(client))
    for kind,key in [('user',task_owner(client)),('project',task['project_id'])]:usage.set_budget(kind,key,5000000,0)
    fixture=LiveFixture()
    assert run_manuscript_writing_task(task['id'],task['revision'],provider=fixture)['status']=='succeeded'
    assert fixture.posts==[old['wire_json']]
    assert 'Original frozen instruction.' in fixture.posts[0] and 'A different new instruction.' not in fixture.posts[0]
    assert client.get(root+'/writing-previews/'+old['id']).json()==old
