"""Evidence reads traverse real immutable parser objects; no provider calls."""
from tests.api.test_projects import client
from tests.api.test_document_versions import uploaded_docx
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.adapters.docx_parser import parse_docx
import pytest


def upload_evidence_document(client, content, filename):
    from tests.api.test_projects import create_project
    from tests.api.test_file_batches import register
    project=create_project(client)
    base,batch,item,content=register(client,project,content,filename)
    result=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(filename,content)})
    assert result.status_code==202,result.text
    saved=result.json()
    return f"/api/v1/projects/{project['id']}/files/{saved['file_id']}",saved


def all_evidence(client, url):
    first=client.get(url)
    assert first.status_code==200,first.text
    result=first.json();items=list(result['items'])
    for page in range(2,(result['pagination']['total']+19)//20+1):
        items+=client.get(url+f'?page={page}').json()['items']
    return result,items


def test_docx_evidence_has_bounded_items_real_sources_and_candidates(client, monkeypatch):
    project, _, _, item, _ = uploaded_docx(client)
    assert run_parse_file_task(item['task']['id'], 1, parser=parse_docx)['status'] == 'succeeded'
    base = f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    version = client.get(base).json()['items'][0]
    url = base + '/' + version['id'] + '/evidence'
    def forbid(*args):
        raise AssertionError('Evidence must never reopen the original')
    monkeypatch.setattr('app.adapters.storage.ProjectStore.original', forbid)
    response = client.get(url)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['schema_version'] == 1 and value['pagination']['page_size'] == 20
    assert value['source']['version_id'] == version['id']
    assert value['counts']['images'] == 2
    assert len(value['items']) <= 20
    items = list(value['items'])
    for page in range(2, (value['pagination']['total'] + 19) // 20 + 1):
        items += client.get(url + f'?page={page}').json()['items']
    assert len(items) == value['pagination']['total']
    images = [i for i in items if i['kind'] == 'image']
    assert all(i['location']['part'] == 'word/document.xml' for i in images)
    # Two adjacent captions compete for the same pictures in this existing fixture.
    assert all(not i['associations'] and 'caption_ambiguous' in i['uncertainties'] for i in images)
    assert all('caption_unlinked' in i['uncertainties'] for i in items if i['kind']=='text' and i['text'].startswith(('图1','图2')))
    assert any(i['kind'] == 'cell' and i['value']['typed'] == '1.50 mg' for i in items)
    assert all(i['value']['unit']['status'] == 'unconfirmed' for i in items if i['value'])
    for bad in ('0', '-1', '1.0', '+1', '１', '1e2'):
        assert client.get(url + '?page=' + bad).status_code == 422


def test_raw_and_prepared_evidence_use_saved_cells_and_confirmed_units(client, monkeypatch):
    from tests.integration.test_dataset_preparation import create_preparation, run, review, decision, decide
    base, _, raw, _, task = create_preparation(client, rows=[['Mass (mg)', 'Label'], [1.5, ' NA '], [None, '=1+1']])
    run(task)
    view = review(client, task)
    recipe = view['recipe']
    recipe['fields'][0]['unit'] = dict(status='confirmed', value='mg')
    recipe['fields'][1].update(trim_text=True, missing_markers=['NA'])
    revised = decide(client, task, decision(view, 'revise', recipe), 'revise-evidence').json()
    run(revised)
    accepted = decide(client, task, decision(review(client, revised)), 'approve-evidence').json()
    assert run(accepted)['status'] == 'succeeded'
    prepared = review(client, accepted)['result']
    def forbid(*args):
        raise AssertionError('No original reparse')
    monkeypatch.setattr('app.adapters.storage.ProjectStore.original', forbid)
    for kind, version in [('dataset', raw), ('prepared-dataset', prepared)]:
        response = client.get(base + f'/{kind}-versions/' + version['id'] + '/evidence')
        assert response.status_code == 200, response.text
        value = response.json()
        assert value['scope']['sheet_name'] == raw['sheet_name']
        assert value['counts']['rows'] == (3 if kind == 'dataset' else 2)
        cells = [c for i in value['items'] if i['kind'] == 'row' for c in i['cells']]
        if kind == 'prepared-dataset':
            assert any(c['value']['typed'] is None for c in cells)
            marker=next(c for c in cells if c['location']['coordinate']=='B2')
            assert marker['value']['original_typed']==' NA '
            assert marker['value']['raw_source_version_id']==raw['id']
            assert value['source']['parent_version_id']==raw['id']
        else:
            assert not any(c['location']['coordinate']=='A3' for c in cells)
        formula = next(c for c in cells if c['value']['kind'] == 'formula')
        assert formula['value']['formula']['cache_validity'] == 'unverified'
        mass = next(i for i in value['items'] if i['kind'] == 'field')
        assert mass['value']['unit']['status'] == ('unconfirmed' if kind == 'dataset' else 'confirmed')


def test_unambiguous_docx_captions_have_two_real_sources(client):
    from tests.helpers.evidence_samples import evidence_docx
    base,item=upload_evidence_document(client,evidence_docx(),'captions.docx')
    assert run_parse_file_task(item['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    version=client.get(base+'/document-versions').json()['items'][0]
    value,items=all_evidence(client,base+'/document-versions/'+version['id']+'/evidence')
    # Saved only outside the isolated data root as a reviewer-facing synthetic API example.
    from app.core.paths import PROJECT_ROOT
    import json
    output=PROJECT_ROOT/'script/.runtime/stage03-step14'
    if output.is_dir():(output/'task1-evidence-api-example.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for kind in ('image','table'):
        target=next(i for i in items if i['kind']==kind)
        candidate=target['associations'][0]
        assert candidate['status']=='candidate' and candidate['target_source']==target['location']
        assert candidate['caption_source']['path']!=target['location']['path']
        assert candidate['caption_source']['part']==target['location']['part']=='word/document.xml'
        caption=next(i for i in items if i['id']==candidate['caption_id'])
        assert 'caption_unlinked' not in caption['uncertainties']
        assert 'caption_association_candidate' in caption['uncertainties']


def test_pdf_old_frozen_retry_then_v2_reparse_keeps_saved_v1(client, monkeypatch):
    from tests.helpers.evidence_samples import evidence_pdf
    from app.adapters.pdf_parser import parse_pdf
    from app.db.database import database_connection
    from app.core.exceptions import StorageError
    base,item=upload_evidence_document(client,evidence_pdf(),'captions.pdf')
    legacy='pdfplumber-0.11.10-text-v1'
    # Reproduce an already persisted v1 task, before the new parser was introduced.
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{parser_version}',to_jsonb(%s::text)) WHERE id=%s",(legacy,item['task']['id']))
        db.execute('UPDATE file_parse_results SET parser_version=%s WHERE task_id=%s',(legacy,item['task']['id']))
    def timeout(*args):raise StorageError('parse_timeout','synthetic timeout')
    failed=run_parse_file_task(item['task']['id'],1,parser=timeout)
    retried=client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']}).json()
    versions=[]
    def local(content,filename,settings,*,parser_version):
        versions.append(parser_version)
        return parse_pdf(content,filename,settings,parser_version=parser_version)
    monkeypatch.setattr('app.adapters.pdf_process.parse_pdf_isolated',local)
    assert run_parse_file_task(retried['id'],retried['revision'])['status']=='succeeded'
    old=client.get(base+'/document-versions').json()['items'][0]
    old_raw=client.get(old['download_url']).content
    old_evidence,_=all_evidence(client,base+'/document-versions/'+old['id']+'/evidence')
    assert 'legacy_pdf_images_not_extracted' in old_evidence['uncertainties']
    fresh=client.post(base+'/document-versions',headers={'Idempotency-Key':'upgrade-pdf'},json={'expected_latest_version':1}).json()
    assert run_parse_file_task(fresh['task_id'],1)['status']=='succeeded'
    assert versions==[legacy,'pdfplumber-0.11.10-evidence-v2']
    value,items=all_evidence(client,base+'/document-versions/'+fresh['id']+'/evidence')
    assert value['counts']['embedded_images']==1
    for kind in ('image','table'):
        target=next(i for i in items if i['kind']==kind)
        assert target['associations'][0]['basis']=='nearest_same_page'
        assert target['associations'][0]['caption_source']['page_number']==target['location']['page_number']==1
    assert client.get(old['download_url']).content==old_raw


def test_evidence_owner_tamper_and_read_only_fingerprint(client):
    import hashlib,json
    from pathlib import Path
    import os
    def data_root():return Path(os.environ['PAPERASSIST_DATA_DIR'])
    from app.db.database import database_connection
    from tests.integration.test_project_ownership import account_client
    project,_,_,item,_=uploaded_docx(client)
    run_parse_file_task(item['task']['id'],1,parser=parse_docx)
    base=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    version=client.get(base).json()['items'][0]
    url=base+'/'+version['id']+'/evidence'
    def fingerprint():
        with database_connection() as db:
            tables=db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename").fetchall()
            # Authentication refreshes its session timestamp on every authenticated HTTP request.
            rows={t['tablename']:[dict(r) for r in db.execute('SELECT to_jsonb(t) AS row FROM "'+t['tablename']+'" t ORDER BY to_jsonb(t)::text').fetchall()] for t in tables if t['tablename']!='sessions'}
        assets={str(p.relative_to(data_root())):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(data_root()).rglob('*') if p.is_file()}
        return json.dumps(rows,sort_keys=True,default=str),assets
    before=fingerprint()
    all_evidence(client,url)
    assert fingerprint()==before
    with account_client('evidence-other@example.test')[0] as other:
        assert other.get(url).status_code==404
    with database_connection(write=True) as db:
        db.execute("UPDATE file_parse_results SET result_json=jsonb_set(result_json,'{object,sha256}',to_jsonb(%s::text)) WHERE id=%s",('b'*64,version['id']))
    assert client.get(url).status_code==409


def test_ocr_evidence_stays_unreviewed_after_real_review_and_exposes_preview_source(client):
    from tests.integration.test_ocr_review import setup_review,execute,decide
    _,base,parent,task,_=setup_review(client)
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    view=client.get(url).json()
    revised=decide(client,view,'revise','evidence-edit',[dict(block_id='text-1',action='replace_text',text='Verified replacement')]).json()
    execute(revised)
    approved=decide(client,client.get(url).json(),'approve','evidence-approve').json()
    assert execute(approved)['status']=='succeeded'
    value,items=all_evidence(client,base+'/document-versions/'+parent['id']+'/evidence')
    text=next(i for i in items if i['kind']=='text')
    assert text['text']=='候选 12 mg' and text['uncertainties']==['ocr_unreviewed']
    assert text['location']['polygon']==[[0.,0.],[10.,0.],[10.,10.],[0.,10.]]
    assert 'ocr_review_not_projected' in value['uncertainties']
    image=next(i for i in items if i['kind']=='image')
    assert image['location']['page_number']==1
    assert client.get(image['preview_url']).status_code==200


def test_raw_evidence_paginates_all_rows_and_preserves_empty_lexical_states(client):
    from tests.helpers.evidence_samples import evidence_xlsx
    from tests.api.test_projects import create_project
    from tests.api.test_dataset_analysis import version
    project=create_project(client)
    upload=client.post(f"/api/v1/projects/{project['id']}/files",files={'file':('lexical.xlsx',evidence_xlsx())})
    assert upload.status_code==201,upload.text
    file=upload.json()['file']
    base=f"/api/v1/projects/{project['id']}/files/{file['id']}"
    raw=version(client,base)
    value,items=all_evidence(client,base+'/dataset-versions/'+raw['id']+'/evidence')
    assert value['counts']['rows']==31 and len(items)==35
    assert [i['location']['row'] for i in items if i['kind']=='row']==list(range(1,32))
    cells={c['location']['coordinate']:c['value'] for i in items for c in i['cells']}
    assert cells['B31']['typed']=='' and cells['B31']['raw'] is None
    assert cells['C31']['typed'] is None and cells['C31']['raw'] is None
    assert cells['D31']['typed']=='' and cells['D31']['raw'] is None
    assert cells['B30']['typed']=='=1+1' and cells['B30']['raw']=='2'
    assert cells['B30']['formula']['cache_state']=='present'
    assert cells['B30']['formula']['cache_validity']=='unverified'
    assert cells['B30']['unit']['status']=='unconfirmed'


@pytest.mark.parametrize('format',['docx','pdf','ocr'])
def test_document_evidence_preserves_saved_warnings_and_their_real_scope(client,monkeypatch,format):
    from tests.helpers.document_samples import document_bytes
    from tests.helpers.pdf_samples import pdf_bytes,TEXT
    from tests.helpers.ocr_samples import ocr_result
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.contracts import Warning
    if format=='docx':
        content=document_bytes(warnings=True);filename='warnings.docx';parser=parse_docx
    elif format=='pdf':
        content=pdf_bytes([TEXT,b'']).replace(b'/BaseFont /Helvetica',b'/BaseFont /UnknownFont').replace(b'(001.20 kg)',b'<81>')
        filename='warnings.pdf';parser=parse_pdf
    else:
        content=b'persisted OCR source';filename='warnings.png'
        def parser(*args,**kwargs):
            result=ocr_result(*args,**kwargs)
            result.document.warnings=[Warning(code='unreviewed',message='所有识别文字均待人工核对。',count=1)]
            result.document.pages[0].text_blocks[0].score=.4
            result.document.pages[0].warnings=[Warning(code='low_confidence',message='部分文字置信度较低，请对照原图核对。',count=1)]
            return result
    base,item=upload_evidence_document(client,content,filename)
    assert run_parse_file_task(item['task']['id'],1,parser=parser)['status']=='succeeded'
    version=client.get(base+'/document-versions').json()['items'][0]
    saved=client.get(version['download_url']).json()
    def forbid(*args,**kwargs):raise AssertionError('Warning projection must not reparse source')
    monkeypatch.setattr('app.adapters.docx_parser.parse_docx',forbid)
    monkeypatch.setattr('app.adapters.pdf_parser.parse_pdf',forbid)
    if format!='ocr':monkeypatch.setattr('app.adapters.storage.ProjectStore.original',forbid)
    value,_=all_evidence(client,base+'/document-versions/'+version['id']+'/evidence')
    expected=[]
    for warning in saved['warnings']:
        expected.append(dict(**warning,scope='document',pages=[p['page_number'] for p in saved.get('pages',[])],location=None))
    for page in saved.get('pages',[]):
        if format=='pdf':location=dict(page_number=page['page_number'],bbox=page['bbox'])
        else:location=dict(page_number=page['page_number'],bbox=[0.,0.,page['source_width'],page['source_height']],coordinate_system=page['source_coordinate_system'])
        for warning in page['warnings']:expected.append(dict(**warning,scope='page',pages=[page['page_number']],location=location))
    actual=[{**w,'location':{k:v for k,v in w['location'].items() if v is not None} if w['location'] else None} for w in value['warnings']]
    assert actual==expected and expected
    if format=='pdf':
        broken=next(w for w in actual if w['code']=='undecoded_characters')
        assert broken['count']==1 and broken['pages']==[1]
        blank=next(w for w in actual if w['code']=='no_extractable_text')
        assert blank['pages']==[2]
    else:assert any(w['scope']=='document' for w in actual)
