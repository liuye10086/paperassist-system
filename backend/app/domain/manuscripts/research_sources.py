"""Typed research-source projection shared by manuscript and model validation."""
from copy import deepcopy
import re
from uuid import uuid4
from app.adapters.research_results_store import base,insert,invalid
from app.db.research_results_schema import SOURCE_TARGETS
from app.domain.bioinformatics.contracts import digest

KINDS=frozenset(('research_finding_version','research_report_version','research_figure_version'))


def project_source(source):
    value=source.model_dump(mode='json') if hasattr(source,'model_dump') else source
    content=value['content']
    if value['source_kind']=='research_report_version':content=content['finding']['content']
    projection={key:deepcopy(content.get(key,[])) for key in ('facts','methods','claims','conflicts','gaps','warnings','limitations')}
    if value['source_kind']=='research_figure_version':
        projection['figure']={k:deepcopy(value['content']['config'].get(k)) for k in ('title','caption','language','figure_language')}
        projection['members']=[{k:m[k] for k in ('id','key','format','role','sha256','size_bytes') if k in m} for m in value['content'].get('members',[])]
    return dict(kind=value['source_kind'],id=value['source_id'],role='image_observation' if value['source_kind']=='research_figure_version' else 'user_results',
        label=value['title'],sha256=value['sha256'],locator=value['locator'],source_file_ids=value['source_file_ids'],content=projection)


def read(service,project,source,db=None,*,progress=None):
    from app.domain.research_results.sources import ResearchSourceReader
    return project_source(ResearchSourceReader(service.assets).read_source(project,dict(source_kind=source['kind'],source_id=source['id'],locator=source.get('locator',{'kind':'object'}),sha256=source['sha256']),db=db,progress=progress))


def _read_in_phase(service,project,source,db,*,phase,progress=None):
    from app.domain.research_results.sources import ResearchSourceReader
    return project_source(ResearchSourceReader(service.assets)._read_source_in_phase(project,dict(source_kind=source['kind'],source_id=source['id'],locator=source.get('locator',{'kind':'object'}),sha256=source['sha256']),db=db,phase=phase,progress=progress))


def file_ids(sources):
    return sorted({f for source in sources for f in ([source['file_id']] if 'file_id' in source else source.get('source_file_ids',[]))})


def bind(db,project,owner,version_id,source):
    column,_=SOURCE_TARGETS[source['kind']]
    insert(db,'manuscript_research_sources',{**base(str(uuid4()),project,owner),'version_id':version_id,
        'source_kind':source['kind'],'source_id':source['id'],column:source['id'],'role':source['role'],
        'source_json':source,'sha256':digest(source)})


def numeric(source):
    blocked={f for c in source.get('content',{}).get('conflicts',[]) if c['decision']=='unresolved' for f in c['fact_ids']}
    for index,fact in enumerate(source.get('content',{}).get('facts',[])):
        raw=fact['raw_value']
        numeric_value=type(raw) in (int,float) or isinstance(raw,str) and re.fullmatch(r'[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?',raw) is not None
        if fact['id'] in blocked or fact['verification_status'] in ('missing','conflict') or not numeric_value:continue
        yield dict(fact_path=f'/facts/{index}/raw_value',value=str(fact['raw_value']),research_fact_id=fact['id'],
            origin=fact['origin'],unit=fact['unit'],observation_level=fact['observation_level'],comparison=fact['comparison'])


def changes(service,project,source):
    reasons=[]
    try:
        if read(service,project,source)!=source:reasons.append('source_changed')
        table={'research_finding_version':'research_finding_versions','research_report_version':'research_report_versions','research_figure_version':'research_figure_versions'}[source['kind']]
        root='set_id' if source['kind']=='research_finding_version' else 'root_id'
        with service.store.connection() as db:
            newer=db.execute('SELECT 1 FROM '+table+' n JOIN '+table+' old ON n.'+root+'=old.'+root+' WHERE old.id=%s AND n.revision>old.revision',(source['id'],)).fetchone()
        if newer:reasons.append('newer_source_version')
    except Exception as exc:
        from app.core.exceptions import StorageError
        if not isinstance(exc,StorageError) or exc.code in ('storage_unavailable','database_configuration'):raise
        reasons.append('source_unavailable_or_changed')
    return [dict(kind=source['kind'],id=source['id'],reasons=reasons)] if reasons else []


def validate_version(service,db,row):
    """A versioned producer branch with task, source, parent and scope checks."""
    from app.domain.manuscripts.delivery_context import resolve_document_context
    from app.domain.manuscripts.school_binding import validate_frozen
    from app.domain.manuscripts.contracts import WORKFLOW
    snapshot=row['snapshot_json'];request=row['request_json']
    if request.get('schema_version')!=2 or request.get('kind')!='research_results_methods':raise invalid()
    if digest(snapshot)!=row['snapshot_sha256'] or digest(request)!=row['request_digest']:raise invalid()
    context=resolve_document_context(db,row['project_id'],row['user_id'],manuscript_id=row['manuscript_id'],active=False)
    if (snapshot.get('project_id')!=row['project_id'] or snapshot.get('workflow_version')!=WORKFLOW
        or snapshot.get('schema_version')!=1 or request['delivery_id']!=context['delivery_id']
        or snapshot.get('research_bridge',{}).get('delivery_id')!=context['delivery_id']
        or snapshot['research_bridge'].get('document_kind')!=context['document_kind']
        or request['expected_revision']!=row['revision']-1 or snapshot['title']!=request['title'] or snapshot['output_language']!=request['output_language']):raise invalid()
    validate_frozen(service,db,row)
    source_rows=db.execute('SELECT * FROM manuscript_research_sources WHERE version_id=%s',(row['id'],)).fetchall()
    expected=[s for s in snapshot['sources'] if s['kind'] in KINDS]
    if len(source_rows)!=len(expected):raise invalid()
    indexed={(s['source_kind'],s['source_id']):s for s in source_rows}
    for source in expected:
        bound=indexed.get((source['kind'],source['id']))
        column,_=SOURCE_TARGETS[source['kind']]
        if not bound or bound[column]!=source['id'] or bound['source_json']!=source or bound['sha256']!=digest(source) or bound['role']!=source['role'] or bound['project_id']!=row['project_id'] or bound['user_id']!=row['user_id']:raise invalid()
    legacy=db.execute('SELECT * FROM manuscript_sources WHERE version_id=%s',(row['id'],)).fetchall()
    if sorted((s['source_json'] for s in legacy),key=lambda s:s['id'])!=sorted((s for s in snapshot['sources'] if s['kind'] not in KINDS),key=lambda s:s['id']):raise invalid()
    producer=service.store.require_task(db,row['task_id'])
    if producer['project_id']!=row['project_id'] or producer['user_id']!=row['user_id'] or digest(producer['input_snapshot'])!=producer['input_digest']:raise invalid()
    if producer['task_type']=='research_fact_draft':
        from app.domain.research_results.task_contracts import input_version
        from app.domain.research_results.fact_draft import compose
        input_version(producer)
        record=db.execute('SELECT * FROM research_manuscript_candidates WHERE task_id=%s AND project_id=%s AND user_id=%s',(producer['id'],row['project_id'],row['user_id'])).fetchone()
        if (not record or record['published_version_id']!=row['id'] or record['candidate_json']!=snapshot
            or record['candidate_sha256']!=digest(snapshot) or record['base_version_id']!=row['parent_version_id']
            or record['expected_revision']!=row['revision']-1 or record['id']!=request['candidate_id']
            or compose(producer['input_snapshot']['payload'])!=snapshot or producer['status']!='succeeded'
            or producer.get('result_research_candidate_id')!=record['id']):raise invalid()
    elif producer['task_type']=='manuscript_draft':
        task_input=producer['input_snapshot']
        if task_input.get('snapshot_sha256')!=row['snapshot_sha256'] or task_input.get('manuscript_version_id')!=row['id']:raise invalid()
        if snapshot.get('writing_provenance'):
            writing=db.execute('SELECT * FROM manuscript_writing_requests WHERE task_id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',
                (snapshot['writing_provenance']['request_id'],row['manuscript_id'],row['project_id'],row['user_id'])).fetchone()
            if not writing:raise invalid()
            if snapshot['writing_provenance'].get('schema_version')==2:
                from app.domain.manuscript_writing.live_publish import validate_published
                validate_published(service,db,row,writing)
            else:
                from app.domain.manuscript_writing.context import validate_candidate
                if writing['published_revision']!=row['revision'] or writing['candidate_json']!=snapshot or writing['base_version_id']!=row['parent_version_id']:raise invalid()
                validate_candidate(snapshot,writing['input_snapshot'])
        elif snapshot.get('review_provenance'):
            from app.domain.manuscript_review.service import validate_review_version
            validate_review_version(service,db,row)
        else:raise invalid()
    else:raise invalid()
    if row['parent_version_id']:
        parent=db.execute('SELECT * FROM manuscript_versions WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(row['parent_version_id'],row['manuscript_id'],row['project_id'],row['user_id'])).fetchone()
        if not parent or parent['revision']!=row['revision']-1:raise invalid()
    elif row['revision']!=1:raise invalid()
