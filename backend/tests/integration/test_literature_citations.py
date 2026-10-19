"""Synthetic sources, real PostgreSQL transactions and permission boundaries."""
import copy
import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection, migration_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature_citations import seeded, binding, paragraph, draft_body
from tests.api.test_literature_evidence import post


def test_saved_source_corruption_blocks_new_citations_and_preserves_old_output(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,_=binding(client,lit,task,refs[0])
    path=lit+'/citations/drafts'
    first=post(client,path,draft_body(paragraph(c,b)),'first').json()
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM literature_search_hits WHERE project_reference_id=%s',(refs[0]['id'],)).fetchone()
        changed=copy.deepcopy(row['record_json']);changed['title']='Fabricated changed bookkeeping'
        db.execute('UPDATE literature_search_hits SET record_json=%s WHERE id=%s',(Jsonb(changed),row['id']))
    assert post(client,path,draft_body(paragraph(c,b)),'changed').status_code==409
    old=client.get(path+'/'+first['id']).json()
    assert old['snapshot']==first['snapshot']
    assert 'source_unavailable_or_changed' in old['current_changes'][0]['reasons']
    assert client.get(path+'/'+first['id']+'/versions/1/output').json()['output']==first['snapshot']['output']
    for suffix in ('/candidates','/todos'):
        candidates=client.get(lit+'/citations'+suffix)
        assert candidates.status_code==200,candidates.text
        candidate=next(r for r in candidates.json()['items'] if r['id']==refs[0]['id'])
        assert candidate['claims'][0]['review_source_current'] is False
        assert candidate['claims'][0]['citation_eligible'] is False
        assert 'verify_evidence_source' in candidate['todos']


@pytest.mark.parametrize('status',['partial','needs_review'])
def test_unconfirmed_decisions_are_not_eligible(client,status):
    _,lit,task,refs=seeded(client)
    c,b,meta,review=binding(client,lit,task,refs[0])
    body={k:review[k] for k in ('claim_revision','project_reference_id','evidence_ids','relevance','reason','limitations')}
    body.update(status=status,narrowed_statement='Narrower supported statement' if status=='partial' else '')
    newer=post(client,lit+'/evidence/claims/'+c['id']+'/reviews',body,'newer')
    assert newer.status_code==201,newer.text
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,{**b,'review_id':newer.json()['id']})),'denied').status_code==409
    revision=post(client,lit+'/evidence/claims/'+c['id']+'/versions',dict(expected_revision=1,content='Narrowed statement',context='',output_language='en'),'narrow')
    assert revision.status_code==201
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(revision.json(),b)),'old-review').status_code==422
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,b)),'old-claim').status_code==409


def test_incomplete_or_unconfirmed_metadata_does_not_confirm_citation(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,_=binding(client,lit,task,refs[0])
    path=lit+'/citations/references/'+refs[0]['id']+'/metadata'
    manual=dict(expected_revision=1,mode='manual',search_id=task['id'],metadata=meta['metadata'],
        source_description='Synthetic explicit source',basis='Synthetic transcription')
    unverified=post(client,path,manual,'unverified').json()
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,{**b,'metadata_version_id':unverified['id']})),'denied').status_code==409
    metadata={**meta['metadata'],'year':''}
    incomplete=post(client,path,{**manual,'expected_revision':2,'metadata':metadata,'confirm_source':True},'incomplete').json()
    assert incomplete['gaps']==['year'] and not incomplete['usable']
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,{**b,'metadata_version_id':incomplete['id']})),'denied-2').status_code==409


def test_failed_version_insert_rolls_back_draft_root_and_revision(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,_=binding(client,lit,task,refs[0])
    path=lit+'/citations/drafts'
    first=post(client,path,draft_body(paragraph(c,b)),'first').json()
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_citation_version() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic transaction failure'; END $$""")
        db.execute('CREATE TRIGGER reject_citation BEFORE INSERT ON literature_citation_versions FOR EACH ROW EXECUTE FUNCTION reject_citation_version()')
    assert post(client,path,draft_body(paragraph(c,b)),'rollback-new').status_code>=500
    assert post(client,path+'/'+first['id']+'/versions',draft_body(paragraph(c,b),expected_revision=1),'rollback-version').status_code>=500
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM literature_citation_drafts').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM literature_citation_versions').fetchone()['n']==1
        assert db.execute('SELECT revision FROM literature_citation_drafts').fetchone()['revision']==1


def test_other_owner_cannot_read_sources_history_or_mutate(client):
    from tests.integration.test_project_ownership import account_client
    _,lit,task,refs=seeded(client)
    c,b,meta,_=binding(client,lit,task,refs[0])
    path=lit+'/citations';sample=post(client,path+'/drafts',draft_body(paragraph(c,b)),'sample').json()
    with account_client('citation-intruder@example.test')[0] as other:
        for suffix in ('/config','/candidates','/todos','/drafts','/drafts/'+sample['id'],
            '/drafts/'+sample['id']+'/versions/1/source','/metadata/'+meta['id']+'/source',
            '/references/'+refs[0]['id']+'/metadata'):
            assert other.get(path+suffix).status_code==404
        assert post(other,path+'/drafts',draft_body(paragraph(c,b)),'intruder').status_code==404
        assert post(other,path+'/references/'+refs[0]['id']+'/metadata',dict(expected_revision=1,mode='extract',search_id=task['id']),'intruder').status_code==404


def test_material_confirmation_is_append_only_separate_from_actual_reading_scope(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    from tests.api.test_literature import create
    from app.domain.literature.execution import run_literature_task
    from tests.api.test_literature_citations import CitationNcbi
    project,_,_,uploaded,_=uploaded_docx(client)
    pid=project['id'];lit=f'/api/v1/projects/{pid}/literature'
    task=create(client,pid).json()
    assert run_literature_task(task['id'],1,client=CitationNcbi(3))['status']=='succeeded'
    ref=client.get(lit+'/references').json()['items'][0]
    assert run_parse_file_task(uploaded['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    option=client.get(lit+'/evidence/material-options').json()['items'][0];version=option['versions'][0]
    material=post(client,lit+'/evidence/materials',dict(project_reference_id=ref['id'],file_id=uploaded['file_id'],
        source_kind=version['kind'],version_id=version['version_id'],source_description='Synthetic document',match_note='Manual synthetic match'),'material').json()
    path=lit+'/citations/materials/'+material['id']+'/confirmations'
    candidates=client.get(lit+'/citations/candidates').json()['items']
    initial=next(r for r in candidates if r['id']==ref['id'])
    assert initial['holds_full_paper'] is False and initial['materials'][0]['completeness']=='unconfirmed'
    body=dict(expected_revision=0,completeness='full_paper',basis='Explicit synthetic whole-paper check')
    first=post(client,path,body,'full')
    assert first.status_code==201,first.text
    assert first.json()['source']==material['source']
    assert post(client,path,body,'full').json()==first.json()
    assert post(client,path,{**body,'completeness':'fragment'},'stale').status_code==409
    assert post(client,path,{**body,'expected_revision':1,'completeness':'fragment'},'fragment').status_code==201
    history=client.get(path).json()
    assert history['total']==2 and history['items'][1]==first.json()
    source=client.get(lit+'/evidence/materials/'+material['id']+'/source').json()
    assert source['total']==first.json()['actual_item_count']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM literature_claim_evidence').fetchone()['n']==0
    assert post(client,path,{**body,'expected_revision':2,'basis':' '},'blank').status_code==422
    # A saved confirmation remains historical when the actual file becomes unavailable.
    assert post(client,path,{**body,'expected_revision':2},'full-again').status_code==201
    from app.core.config import get_data_dir
    from pathlib import Path
    with database_connection() as db:
        file=db.execute('SELECT object_key FROM files WHERE id=%s',(uploaded['file_id'],)).fetchone()
    (Path(get_data_dir())/file['object_key']).write_bytes(b'changed synthetic original')
    candidate=next(r for r in client.get(lit+'/citations/candidates').json()['items'] if r['id']==ref['id'])
    assert candidate['materials'][0]['completeness']=='full_paper'
    assert candidate['materials'][0]['source_current'] is False
    assert candidate['holds_full_paper'] is False
    assert 'obtain_or_confirm_full_paper' in candidate['todos']


def test_empty_evidence_or_model_only_review_is_not_a_citation(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,r=binding(client,lit,task,refs[0])
    body=dict(claim_revision=1,project_reference_id=refs[0]['id'],evidence_ids=[],status='needs_review',relevance='uncertain',reason='Only model suggestion',narrowed_statement='',limitations='No verified evidence')
    latest=post(client,lit+'/evidence/claims/'+c['id']+'/reviews',body,'unverified')
    assert latest.status_code==201
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,{**b,'review_id':latest.json()['id']})),'no-evidence').status_code==409


def test_manual_metadata_cannot_upgrade_saved_book_to_supported_journal(client):
    from tests.api.test_literature import create,project
    from tests.helpers.literature import SyntheticNcbi
    from app.adapters.ncbi import parse_fetch
    from app.domain.literature.execution import run_literature_task
    from tests.domain.test_literature_citation_format import _metadata
    class Books(SyntheticNcbi):
        def fetch(self,pmids):
            raw=('<PubmedArticleSet>'+''.join('<PubmedBookArticle><BookDocument><PMID>'+p+'</PMID><ArticleTitle>Synthetic book chapter</ArticleTitle></BookDocument></PubmedBookArticle>' for p in pmids)+'</PubmedArticleSet>').encode()
            return parse_fetch(raw,pmids)
    pid=project(client);task=create(client,pid).json()
    assert run_literature_task(task['id'],1,client=Books(1))['status']=='succeeded'
    lit=f'/api/v1/projects/{pid}/literature';ref=client.get(lit+'/references').json()['items'][0]
    path=lit+'/citations/references/'+ref['id']+'/metadata'
    extracted=post(client,path,dict(expected_revision=0,mode='extract',search_id=task['id']),'book')
    assert extracted.status_code==201 and extracted.json()['gaps']==['article_type']
    forged=post(client,path,dict(expected_revision=1,mode='manual',search_id=task['id'],metadata=_metadata(pmid=ref['pmid']),
        source_description='Book record',basis='Manual entry',confirm_source=True),'forged')
    assert forged.status_code==422,forged.text


def test_receipt_request_tampering_is_not_a_verified_source(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,_=binding(client,lit,task,refs[0])
    with database_connection(write=True) as db:
        receipt=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s',(meta['source']['receipt_id'],)).fetchone()
        db.execute('UPDATE literature_fetch_receipts SET request_json=%s WHERE id=%s',
            (Jsonb({**receipt['request_json'],'operation':'esearch'}),receipt['id']))
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,b)),'tampered-receipt').status_code==409


def test_empty_saved_receipt_pmids_degrade_candidates_and_keep_manual_decision(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,review=binding(client,lit,task,refs[0])
    first=post(client,lit+'/citations/drafts',draft_body(paragraph(c,b)),'before-source-change').json()
    evidence_path=lit+'/evidence/claims/'+c['id']+'/evidence'
    normal=client.get(evidence_path)
    assert normal.status_code==200,normal.text
    assert normal.json()['items'][0]['id']==review['evidence_ids'][0]
    with database_connection(write=True) as db:
        receipt=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s',(meta['source']['receipt_id'],)).fetchone()
        db.execute('UPDATE literature_fetch_receipts SET request_json=%s WHERE id=%s',
            (Jsonb({**receipt['request_json'],'pmids':[]}),receipt['id']))
    for suffix in ('/candidates','/todos'):
        response=client.get(lit+'/citations'+suffix)
        assert response.status_code==200,response.text
        candidate=next(r for r in response.json()['items'] if r['id']==refs[0]['id'])
        assert candidate['claims'][0]['latest_review']==review
        assert candidate['claims'][0]['review_source_current'] is False
        assert candidate['claims'][0]['citation_eligible'] is False
        assert candidate['metadata']['source_current'] is False
        assert 'verify_evidence_source' in candidate['todos']
    denied=post(client,lit+'/citations/drafts',draft_body(paragraph(c,b)),'after-source-change')
    assert denied.status_code==409,denied.text
    invalid_source=client.get(evidence_path)
    assert invalid_source.status_code==409,invalid_source.text
    assert invalid_source.json()['detail']['code']=='task_source_conflict'
    old=client.get(lit+'/citations/drafts/'+first['id'])
    assert old.status_code==200,old.text
    assert old.json()['snapshot']==first['snapshot']
    assert old.json()['current_changes']


def test_current_changes_locate_every_affected_stable_paragraph(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,r=binding(client,lit,task,refs[0])
    body=draft_body(paragraph(c,b),paragraph(c,b,identity='p-2'))
    first=post(client,lit+'/citations/drafts',body,'two-paragraphs').json()
    review={k:r[k] for k in ('claim_revision','project_reference_id','evidence_ids','relevance','reason','narrowed_statement','limitations')}
    assert post(client,lit+'/evidence/claims/'+c['id']+'/reviews',{**review,'status':'unsupported'},'no-longer-supported').status_code==201
    result=client.get(lit+'/citations/drafts/'+first['id']).json()
    assert {change['paragraph_id'] for change in result['current_changes']}=={'p-1','p-2'}
