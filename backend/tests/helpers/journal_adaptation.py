"""Synthetic local fixture only; callers execute adaptation through public APIs."""
def nonempty_published(client):
    from tests.api.test_manuscript_review_v2_bridge import published
    from tests.api.test_literature import create
    from tests.api.test_literature_citations import CitationNcbi,binding,paragraph,draft_body
    from tests.api.test_journals import post
    from app.domain.literature.execution import run_literature_task
    from app.domain.tasks.execution import run_task
    from app.adapters.storage import get_project_store
    from app.db.database import database_connection
    from app.domain.manuscript_writing.context import normalize_sections,compose_candidate
    from app.domain.literature.service import digest
    from psycopg.types.json import Jsonb
    from PIL import Image
    from io import BytesIO
    root,v2,_,_=published(client);project=root.split('/')[4]
    task=create(client,project).json();assert run_literature_task(task['id'],1,client=CitationNcbi(3))['status']=='succeeded'
    lit=f'/api/v1/projects/{project}/literature';refs=client.get(lit+'/references').json()['items']
    reference=next(r for r in refs if r['record']['abstract'])
    claim,bound,_,_=binding(client,lit,task,reference)
    citation=post(client,lit+'/citations/drafts',draft_body(paragraph(claim,bound)),'citation').json()
    image=Image.new('RGB',(120,80),'white');image.paste((0,100,200),(10,10,55,70));raw=BytesIO();image.save(raw,format='PNG')
    from tests.api.test_file_batches import register
    upload,batch,item,content=register(client,dict(id=project),raw.getvalue(),'synthetic.png')
    response=client.post(upload+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('synthetic.png',content)});assert response.status_code==202,response.text
    file=dict(id=response.json()['file_id']);sources=[{k:s[k] for k in ('kind','id','file_id','role')} for s in v2['snapshot']['sources']]+[dict(kind='original',id=file['id'],file_id=file['id'],role='image_observation')]
    analysis=next(s['id'] for s in sources if s['kind']=='analysis_run')
    request=dict(title='Synthetic nonempty journal fixture',output_language='en',expected_revision=2,sources=sources,results_groups=[dict(id='main',title='Synthetic measured results',analysis_run_ids=[analysis])],citation_draft=dict(id=citation['id'],revision=1))
    preview=post(client,root.rsplit('/',1)[0]+'/preview',request,'preview-complete').json()
    request['figure_notes']=[dict(figure_id=f['id'],caption='Synthetic measured image.',panels=[]) for g in preview['results_groups'] for f in g['figures']]
    response=post(client,root+'/versions',request,'complete-base');assert response.status_code==201,response.text
    version=response.json()['versions'][0];assert run_task(version['task_id'],1)['status']=='succeeded'
    writing=post(client,root+'/writing-requests',dict(base_revision=3,mode='full_draft',instructions='Synthetic offline fixture'),'complete-writing').json()
    with database_connection(write=True) as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(writing['id'],)).fetchone()
        sections=normalize_sections(task['input_snapshot']['base_snapshot'])
        proposed=[dict(id=s['id'],paragraphs=[dict(id=p['id'],text=p['text'],source_ids=p.get('source_ids',[]),citations=p.get('citations',[]),numeric_bindings=p.get('numeric_bindings',[])) for p in s['paragraphs']]) for s in sections]
        candidate=compose_candidate(dict(sections=proposed),task['input_snapshot'])
        db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s WHERE task_id=%s',(Jsonb(candidate),digest(candidate),writing['id']))
        db.execute("UPDATE tasks SET status='succeeded' WHERE id=%s",(writing['id'],))
    response=post(client,root+'/writing-requests/'+writing['id']+'/publish',dict(expected_revision=3),'complete-publish');assert response.status_code==201,response.text
    version=response.json()['versions'][0];assert run_task(version['task_id'],1)['status']=='succeeded'
    assert version['snapshot']['references'] and any(g['figures'] for g in version['snapshot']['results_groups']) and any(g['tables'] for g in version['snapshot']['results_groups'])
    return root,version
