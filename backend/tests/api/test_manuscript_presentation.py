"""Fixed presentation revisions in isolated migrated PostgreSQL, no real calls."""
from copy import deepcopy
import pytest
from tests.api.test_analysis import client
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task
from app.db.database import database_connection

def test_saved_binding_replay_revision_owner_and_historical_head(client):
    path,_,_=setup(client)
    def create(data,key):
        root=post(client,path,data,key).json();version=root['versions'][0]
        assert run_task(version['task_id'],1)['status']=='succeeded'
        return root,version
    root,base=create(body(output_language='zh-CN',methods={'study_design':'合成比较 5 mg'}),'zh')
    _,peer=create(body(methods={'study_design':'Synthetic comparison 5 mg'}),'en')
    endpoint=path+'/'+root['id']+'/presentations'
    request=dict(base_version_id=base['id'],peer_version_id=peer['id'],config=dict(paragraph_groups=[dict(id='g',zh_ids=['methods:study_design'],en_ids=['methods:study_design'])]))
    preview=post(client,endpoint+'/preview',request)
    assert preview.status_code==200,preview.text
    first=post(client,endpoint,request,'presentation')
    assert first.status_code==201,first.text
    saved=first.json();assert saved['revision']==1 and saved['stale'] is False
    assert post(client,endpoint,request,'presentation').status_code==200
    assert post(client,endpoint,dict(request,expected_revision=1),'presentation').status_code==409
    assert post(client,endpoint,request,'old-revision').status_code==409
    other=client.post('/api/v1/projects',json=dict(name='Other',research_topic='Other',project_type='sci')).json()
    foreign=f"/api/v1/projects/{other['id']}/manuscripts/{root['id']}/presentations/{saved['id']}"
    assert client.get(foreign).status_code==404
    assert client.get(endpoint).json()['items'][0]['id']==saved['id']
    next_version=post(client,path+'/'+root['id']+'/versions',body(output_language='zh-CN',expected_revision=1),'next').json()['versions'][0]
    assert run_task(next_version['task_id'],1)['status']=='succeeded'
    current=client.get(endpoint+'/'+saved['id']).json()
    assert current['stale'] and current['base_sha256']==saved['base_sha256']
    assert current['paragraph_groups']==saved['paragraph_groups']
    request['expected_revision']=1
    second=post(client,endpoint,request,'second')
    assert second.status_code==201 and second.json()['revision']==2
    # Database itself prevents rewriting the frozen configuration.
    with pytest.raises(Exception,match='append-only'):
        with database_connection(write=True) as db:db.execute('UPDATE manuscript_presentation_versions SET revision=9 WHERE id=%s',(saved['id'],))

def test_invalid_bindings_and_pending_source_material(client):
    path,_,_=setup(client);root=post(client,path,body(),'root').json();base=root['versions'][0]
    run_task(base['task_id'],1);endpoint=path+'/'+root['id']+'/presentations'
    assert post(client,endpoint,dict(base_version_id='missing'),'missing').status_code==404
    request=dict(base_version_id=base['id'],config=dict(paragraph_groups=[dict(id='bad',en_ids=['missing'],status='missing')]))
    assert post(client,endpoint+'/preview',request).status_code==422
    response=post(client,endpoint,dict(base_version_id=base['id']),'pending')
    assert response.status_code==201,response.text
    assert any(c['code']=='statement:ethics' and c['status']=='pending' for c in response.json()['checks'])

def test_fixed_guide_uses_existing_format_rules_and_missing_guide_is_rejected(client):
    from tests.api.test_journals import profile
    from tests.api.test_journal_format import guide
    path,_,_=setup(client);root=post(client,path,body(),'root').json();version=root['versions'][0]
    run_task(version['task_id'],1)
    journals=path.removesuffix('/manuscripts')+'/journals'
    p=post(client,journals+'/profiles',profile(),'profile').json()
    g=post(client,journals+'/guides',guide(p,source_text='Maximum body words: 0; count: en_whitespace_body'),'guide')
    assert g.status_code==201,g.text
    endpoint=path+'/'+root['id']+'/presentations'
    response=post(client,endpoint,dict(base_version_id=version['id'],config=dict(guide_version_id=g.json()['id'])),'fixed-guide')
    assert response.status_code==201,response.text
    result=response.json()
    assert result['journal_check']['guide_id']==g.json()['id'] and result['journal_check']['guide_sha256']
    assert any(c['code'].startswith('journal:word_limit') and c['status']=='conflict' for c in result['checks'])
    assert result['can_export'] is False and result['quality']['real_compliance']=='pending'
    assert post(client,endpoint+'/preview',dict(base_version_id=version['id'],config=dict(guide_version_id='missing'))).status_code==404

def test_language_confirmation_binds_real_export_bytes_config_and_legacy_raw_config(client,monkeypatch):
    from hashlib import sha256
    from uuid import uuid4
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest
    from app.core.config import get_data_dir
    path,_,_=setup(client)
    root=post(client,path,body(methods=dict(study_design='Synthetic laboratory comparison preserves provided study limitations and requires independent scientific verification.')),'root').json()
    base=root['versions'][0];assert run_task(base['task_id'],1)['status']=='succeeded'
    endpoint=path+'/'+root['id']+'/presentations'
    saved=post(client,endpoint,dict(base_version_id=base['id']),'source-config').json()
    assert 'language_review' not in saved['config']
    source=post(client,path+'/'+root['id']+'/versions/1/exports',dict(presentation_version_id=saved['id'],language_view='en',review_mode='identified'),'source-export')
    assert source.status_code==201,source.text
    source=source.json();assert run_task(source['task_id'],1)['status']=='succeeded'
    with database_connection() as db:
        metadata=db.execute('SELECT metadata_json FROM manuscript_exports WHERE id=%s',(source['id'],)).fetchone()['metadata_json']
        original=db.execute('SELECT * FROM manuscript_presentation_versions WHERE id=%s',(saved['id'],)).fetchone()
    # A historical sealed request can omit optional defaults introduced later.
    legacy_request=deepcopy(original['request_json']);legacy_snapshot=deepcopy(original['snapshot_json'])
    legacy_request['config'].pop('guide_version_id',None);legacy_snapshot['config'].pop('guide_version_id',None)
    legacy_id=str(uuid4())
    with database_connection(write=True) as db:
        db.execute('INSERT INTO manuscript_presentation_versions(id,manuscript_id,project_id,user_id,revision,base_version_id,peer_version_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(legacy_id,original['manuscript_id'],original['project_id'],original['user_id'],2,original['base_version_id'],original['peer_version_id'],'legacy',Jsonb(legacy_request),digest(legacy_request),Jsonb(legacy_snapshot),digest(legacy_snapshot),original['created_at']))
    legacy=client.get(endpoint+'/'+legacy_id)
    assert legacy.status_code==200,legacy.text
    assert 'guide_version_id' not in legacy.json()['config'] and 'language_review' not in legacy.json()['config']
    items=metadata['presentation']['language_inventory']
    decisions=[dict(location=i['location'],content_sha256=i['content_sha256'],decision='provided_literal' if i.get('protected_identity') else 'no_text' if i['kind']=='image' and i.get('no_text') else 'target_language',reason='Human verified this exact exported item',exceptions=[]) for i in items]
    review=dict(source_export_id=source['id'],source_sha256=metadata['sha256'],language_view='en',review_mode='identified',decisions=decisions)
    request=dict(expected_revision=2,base_version_id=base['id'],config=dict(saved['config'],language_review=review))
    changed=deepcopy(request);changed['config']['blind']['identity_terms']=['Changed output configuration']
    assert post(client,endpoint,changed,'changed-config').status_code==409
    changed=deepcopy(request);changed['config']['language_review']['source_sha256']='0'*64
    assert post(client,endpoint,changed,'changed-sha').status_code==409
    changed=deepcopy(request);changed['config']['language_review']['review_mode']='blind'
    assert post(client,endpoint,changed,'changed-mode').status_code==409
    changed=deepcopy(request);changed['config']['language_review']['decisions']=decisions[:-1]
    assert post(client,endpoint,changed,'missing-item').status_code==422
    source_path=get_data_dir()/'manuscript_exports'/(source['id']+'.docx');raw=source_path.read_bytes()
    assert sha256(raw).hexdigest()==metadata['sha256']
    source_path.write_bytes(raw+b'changed isolated fixture')
    assert post(client,endpoint,request,'changed-bytes').status_code==409
    source_path.write_bytes(raw)
    confirmed=post(client,endpoint,request,'confirmed')
    assert confirmed.status_code==201,confirmed.text
    result=confirmed.json();assert result['language_review']['status']=='confirmed'
    assert result['language_review']['decision_count']==len(items)
    def no_repeat_render(*args,**kwargs):raise AssertionError('Confirmed unchanged output must reuse saved DOCX bytes')
    monkeypatch.setattr('app.adapters.manuscript_docx.build_manuscript_docx',no_repeat_render)
    reused=post(client,path+'/'+root['id']+'/versions/1/exports',dict(presentation_version_id=result['id'],language_view='en',review_mode='identified'),'confirmed-export')
    assert reused.status_code==201,reused.text
    completed=run_task(reused.json()['task_id'],1)
    assert completed['status']=='succeeded',completed
    view=client.get(path+'/'+root['id']+'/exports/'+reused.json()['id']).json()
    assert view['sha256']==metadata['sha256']
    assert view['presentation']['quality']['language_review']=='confirmed_for_exact_output'
    assert client.get(view['download_url']).content==raw
    assert client.get(endpoint+'/'+result['id']).status_code==200
