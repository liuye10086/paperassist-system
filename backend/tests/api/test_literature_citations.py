"""Offline citation chain contracts, each test uses a random PostgreSQL schema."""
import pytest
from app.adapters.ncbi import parse_fetch
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import create, project
from tests.api.test_literature_evidence import post, claim
from tests.helpers.literature import SyntheticNcbi


class CitationNcbi(SyntheticNcbi):
    def fetch(self, pmids):
        result = super().fetch(pmids)
        raw = result.raw.replace(b'<JournalIssue>', b'<ISOAbbreviation>Synth J</ISOAbbreviation><JournalIssue><Volume>12</Volume><Issue>3</Issue>')
        raw = raw.replace(b'<Year>2024</Year>', b'<Year>2024</Year><Month>01</Month><Day>12</Day>')
        raw = raw.replace(b'</Journal>', b'</Journal><Pagination><MedlinePgn>1-9</MedlinePgn></Pagination>')
        return parse_fetch(raw, pmids)


def seeded(client, kind='sci'):
    from app.domain.literature.execution import run_literature_task
    pid = project(client, kind)
    task = create(client, pid).json()
    assert run_literature_task(task['id'], task['revision'], client=CitationNcbi(3))['status'] == 'succeeded'
    lit = f'/api/v1/projects/{pid}/literature'
    refs = client.get(lit+'/references').json()['items']
    refs = sorted((r for r in refs if r['record']['abstract']), key=lambda r:r['pmid'])
    return pid, lit, task, refs


def binding(client, lit, task, ref, c=None, suffix=''):
    ep = lit+'/evidence'
    c = c or claim(client, ep)
    evidence = post(client, ep+'/claims/'+c['id']+'/evidence', dict(claim_revision=c['revision'],
        project_reference_id=ref['id'], source_kind='abstract', search_id=task['id'],
        quote=ref['record']['abstract'][0]['text']), 'quote'+suffix)
    assert evidence.status_code == 201, evidence.text
    review = post(client, ep+'/claims/'+c['id']+'/reviews', dict(claim_revision=c['revision'],
        project_reference_id=ref['id'], evidence_ids=[evidence.json()['id']], status='supported',
        relevance='related', reason='Explicit synthetic human decision', narrowed_statement='', limitations='Abstract only'), 'review'+suffix)
    assert review.status_code == 201, review.text
    metadata = post(client, lit+'/citations/references/'+ref['id']+'/metadata',
        dict(expected_revision=0, mode='extract', search_id=task['id']), 'metadata'+suffix)
    assert metadata.status_code == 201, metadata.text
    return c, dict(review_id=review.json()['id'], metadata_version_id=metadata.json()['id']), metadata.json(), review.json()


def paragraph(c, *bindings, identity='p-1'):
    return dict(id=identity, fragments=[dict(kind='text', text='Context: '),
        dict(kind='claim', claim_id=c['id'], claim_revision=c['revision'], bindings=list(bindings))])


def draft_body(*paragraphs, **extra):
    return dict(title='Synthetic sample', output_language='en', format='nlm_numeric_journal_v1', paragraphs=list(paragraphs), **extra)


@pytest.mark.parametrize('kind', ['sci','thesis'])
def test_citation_chain_numbering_reorder_delete_and_frozen_history(client, kind):
    pid, lit, task, refs = seeded(client, kind)
    c, b1, m1, _ = binding(client, lit, task, refs[0])
    _, b2, _, _ = binding(client, lit, task, refs[1], c, '2')
    path = lit+'/citations/drafts'
    body = draft_body(paragraph(c,b2,b1), paragraph(c,b1,identity='p-2'))
    response = post(client,path,body,'draft')
    assert response.status_code == 201, response.text
    first=response.json(); frozen=first['snapshot']
    assert [r['project_reference_id'] for r in frozen['output']['references']] == [refs[1]['id'],refs[0]['id']]
    assert frozen['output']['paragraphs'][0]['text'].endswith('(1, 2)')
    assert frozen['output']['paragraphs'][1]['text'].endswith('(2)')
    assert frozen['paragraphs'][0]['fragments'][1]['text']==c['content']
    bound=frozen['paragraphs'][0]['fragments'][1]['bindings'][0]
    assert bound['evidence'][0]['reading_scope']=='abstract'
    assert bound['metadata_version_id'] and bound['review']['status']=='supported'
    assert bound['metadata']['date']=='2024 01 12'
    assert '2024 Jan 12;' in frozen['output']['references'][0]['text']
    second=post(client,path+'/'+first['id']+'/versions',draft_body(paragraph(c,b1,identity='p-2'),paragraph(c,b2,b1),expected_revision=1),'draft-v2')
    assert second.status_code==201,second.text
    assert second.json()['snapshot']['output']['references'][0]['project_reference_id']==refs[0]['id']
    third=post(client,path+'/'+first['id']+'/versions',draft_body(dict(id='p-2',fragments=[dict(kind='text',text='Only text')]),expected_revision=2),'draft-v3')
    assert third.status_code==201 and third.json()['snapshot']['output']['references']==[]
    old=client.get(path+'/'+first['id'],params={'revision':1}).json()
    assert old['snapshot']==frozen and old['is_current'] is False
    assert client.get(path+'/'+first['id']+'/versions/1/output').json()['output']==frozen['output']
    assert client.get(path+'/'+first['id']+'/versions/1/source').json()['paragraphs']==frozen['paragraphs']
    assert post(client,path,body,'draft').json()['snapshot']==frozen
    assert post(client,path,{**body,'title':'Changed'},'draft').status_code==409
    assert post(client,path+'/'+first['id']+'/versions',draft_body(paragraph(c,b1),expected_revision=1),'stale').status_code==409
    assert client.get(lit+'/citations/config').json()['format']=='nlm_numeric_journal_v1'


def test_later_negative_decision_blocks_new_versions_but_old_output_survives(client):
    _,lit,task,refs=seeded(client)
    c,b,m,r=binding(client,lit,task,refs[0])
    path=lit+'/citations/drafts'
    first=post(client,path,draft_body(paragraph(c,b)),'draft').json()
    negative=post(client,lit+'/evidence/claims/'+c['id']+'/reviews',
        {k:v for k,v in r.items() if k in ('claim_revision','project_reference_id','evidence_ids','relevance','reason','narrowed_statement','limitations')}|dict(status='unsupported'),'negative')
    assert negative.status_code==201,negative.text
    denied=post(client,path+'/'+first['id']+'/versions',draft_body(paragraph(c,b),expected_revision=1),'new')
    assert denied.status_code==409,denied.text
    assert denied.json()['detail']['code']=='literature_citation_conflict'
    old=client.get(path+'/'+first['id']).json()
    assert old['snapshot']==first['snapshot'] and old['current_changes']
    assert client.get(path+'/'+first['id']+'/versions/1/output').json()['output']==first['snapshot']['output']
    candidates=client.get(lit+'/citations/candidates').json()['items']
    candidate=next(x for x in candidates if x['id']==refs[0]['id'])
    assert candidate['claims'][0]['latest_review']['status']=='unsupported'


def test_manual_metadata_is_unverified_by_default_requires_basis_and_explicit_confirmation(client):
    _,lit,task,refs=seeded(client)
    _,_,meta,_=binding(client,lit,task,refs[0])
    path=lit+'/citations/references/'+refs[0]['id']+'/metadata'
    body=dict(expected_revision=1,mode='manual',search_id=task['id'],metadata=meta['metadata'],source_description='Saved source transcription',basis='Checked journal masthead')
    manual=post(client,path,body,'manual')
    assert manual.status_code==201,manual.text
    assert manual.json()['source_verified'] is False and manual.json()['usable'] is False
    verified=post(client,path,{**body,'expected_revision':2,'confirm_source':True},'confirmed')
    assert verified.status_code==201 and verified.json()['usable'] is True
    assert post(client,path,{**body,'expected_revision':3,'basis':'  '},'bad').status_code==422
    assert post(client,path,{**body,'expected_revision':1},'stale').status_code==409
    history=client.get(path).json()
    assert history['total']==3 and history['items'][-1]['metadata']==meta['metadata']


def test_cross_project_ids_and_editable_claim_text_are_rejected(client):
    _,lit,task,refs=seeded(client)
    c,b,meta,_=binding(client,lit,task,refs[0])
    other=f'/api/v1/projects/{project(client)}/literature/citations'
    assert client.get(other+'/metadata/'+meta['id']+'/source').status_code==404
    assert post(client,other+'/drafts',draft_body(paragraph(c,b)),'foreign').status_code==404
    p=paragraph(c,b);p['fragments'][1]['text']='Forged statement'
    assert post(client,lit+'/citations/drafts',draft_body(p),'forged').status_code==422
    assert post(client,lit+'/citations/drafts',draft_body(paragraph(c,b),paragraph(c,b)),'duplicate').status_code==422
