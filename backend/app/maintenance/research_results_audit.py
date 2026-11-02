"""Typed research task/source SQL audit. No model calls or scientific reruns."""
from app.domain.research_results.task_contracts import input_version,RESEARCH_TASKS
from app.domain.bioinformatics.contracts import digest
from app.adapters.bio_analysis_store import scoped_object


def source_refs(value):
    if isinstance(value,dict):
        if all(isinstance(value.get(k),str) for k in ('source_kind','source_id','sha256')):yield value
        if value.get('kind') in ('research_finding_version','research_report_version','research_figure_version') and all(isinstance(value.get(k),str) for k in ('id','sha256')):
            yield dict(source_kind=value['kind'],source_id=value['id'],sha256=value['sha256'],source_file_ids=value.get('source_file_ids',[]))
        for child in value.values():yield from source_refs(child)
    elif isinstance(value,list):
        for child in value:yield from source_refs(child)


def validate_source(db,project,owner,source):
    from app.db.research_results_schema import SOURCE_TARGETS
    kind=source['source_kind'];table=SOURCE_TARGETS[kind][1]
    if kind=='analysis_run':
        import json
        row=db.execute('SELECT r.* FROM analysis_runs r JOIN files f ON f.id=r.file_id JOIN projects p ON p.id=f.project_id WHERE r.id=%s AND f.project_id=%s AND p.owner_id=%s',(source['source_id'],project,owner)).fetchone()
        if not row or not row['completed_at']:raise ValueError('Statistics source incomplete or outside project')
        result=json.loads(row['result_json'])
        if digest(result)!=source['sha256'] or result.get('completed_at')!=row['completed_at']:raise ValueError('Statistics source hash differs')
        return
    row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s',(source['source_id'],project)).fetchone()
    if not row or row.get('user_id',row.get('created_by',owner))!=owner:raise ValueError('Research source owner differs')
    column=('sha256' if kind in ('original_file','bio_analysis_artifact','external_evidence_version','bio_insight_result_member') else 'content_sha256' if kind in ('research_finding_version','research_report_version') else 'manifest_sha256')
    if row[column]!=source['sha256']:raise ValueError('Research source hash differs')
    if kind in ('bio_insight_result_version','bio_insight_result_member'):
        from app.adapters.task_store import DatasetTaskAssets
        from app.core.config import get_data_dir
        from app.domain.bio_insights.service import BioInsightsService
        from app.domain.bio_insights.results import checked_members
        service=BioInsightsService(DatasetTaskAssets(owner,db.config,get_data_dir()))
        result=service.require(db,'bio_insight_result_versions',project,row['result_version_id'] if kind=='bio_insight_result_member' else row['id'])
        task=service.store.require_task(db,result['task_id'])
        if task['status']!='succeeded':raise ValueError('Insight source incomplete')
        service.require_sources(db,task,runtime=False)
        checked_members(service,db,project,result)
    if row.get('task_id'):
        task=db.execute('SELECT * FROM tasks WHERE id=%s AND project_id=%s AND user_id=%s',(row['task_id'],project,owner)).fetchone()
        if not task or task['status']!='succeeded':raise ValueError('Research source incomplete')
    if 'content_json' in row and digest(row['content_json'])!=row['content_sha256']:raise ValueError('Research source content differs')


def validate_research_task_source(db,task):
    input_version(task);project=task['project_id'];owner=task['user_id'];snapshot=task['input_snapshot']
    actual=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()
    if not actual or actual['owner_id']!=owner:raise ValueError('Research task owner differs')
    cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if not cp or cp['state_json'].get('input_version')!=input_version(task):raise ValueError('Research checkpoint differs')
    if task['task_type']=='delivery_package':
        row=db.execute('SELECT * FROM delivery_snapshots WHERE id=%s AND delivery_id=%s AND project_id=%s AND user_id=%s',(snapshot['snapshot_id'],snapshot['delivery_id'],project,owner)).fetchone()
        if not row or digest(row['snapshot_json'])!=row['sha256'] or snapshot['snapshot_sha256']!=row['sha256']:raise ValueError('Delivery snapshot differs')
        if task['status']=='succeeded':
            if cp['next_node']!='done' or cp['state_json'].get('result_id')!=row['id']:raise ValueError('Delivery result differs')
            from app.adapters.bio_analysis_store import object_by_key
            prepared=cp['state_json']['prepared']
            object_by_key(db,project,owner,prepared['manifest_ref'])
            for member in prepared['members']:object_by_key(db,project,owner,member)
        return row
    table,column,result_column={
        'research_figure':('research_figure_versions','figure_version_id','result_research_figure_version_id'),
        'research_report':('research_report_versions','report_version_id','result_research_report_version_id'),
        'research_fact_draft':('research_manuscript_candidates','candidate_id','result_research_candidate_id')}[task['task_type']]
    row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',(snapshot[column],project,owner)).fetchone()
    if not row or row['task_id']!=task['id']:raise ValueError('Research producer differs')
    for source in source_refs(snapshot):validate_source(db,project,owner,source)
    if task['task_type'] in ('research_figure','research_report'):
        parent_column='figure_version_id' if task['task_type']=='research_figure' else 'report_version_id'
        for binding in db.execute('SELECT * FROM research_source_bindings WHERE '+parent_column+'=%s AND project_id=%s',(row['id'],project)):
            if binding['user_id']!=owner:raise ValueError('Research binding owner differs')
            validate_source(db,project,owner,dict(source_kind=binding['source_kind'],source_id=binding['source_id'],sha256=binding['source_sha256']))
    if task['task_type']=='research_figure' and (row['config_json']!=snapshot['config'] or digest(row['config_json'])!=row['config_sha256']):raise ValueError('Figure config differs')
    if task['task_type']=='research_report':
        if (digest(row['content_json'])!=row['content_sha256'] or row['content_sha256']!=snapshot['content_sha256']
                or row['finding_version_id']!=snapshot['request']['finding_version_id']):raise ValueError('Report content differs')
        for source in source_refs(row['content_json']):validate_source(db,project,owner,source)
    if task['task_type']=='research_fact_draft':
        from app.domain.research_results.fact_draft import compose
        if digest(snapshot['request'])!=row['request_digest'] or any(row[k]!=snapshot['request'][k] for k in ('delivery_id','manuscript_id','base_version_id','expected_revision')):raise ValueError('Candidate input differs')
        if row['scope_json']!=dict(sections=snapshot['request']['sections'],writing_scope='results_methods'):raise ValueError('Candidate scope differs')
        if row['candidate_json'] is not None and row['candidate_json']!=compose(snapshot['payload']):raise ValueError('Candidate projection differs')
    if task['status']=='succeeded':
        if task.get(result_column)!=row['id'] or cp['next_node']!='done':raise ValueError('Research result differs')
        if task['task_type']=='research_fact_draft':
            if not row['candidate_json'] or digest(row['candidate_json'])!=row['candidate_sha256']:raise ValueError('Candidate differs')
        else:
            obj=scoped_object(db,project,owner,row['manifest_object_id'])
            if obj['sha256']!=row['manifest_sha256']:raise ValueError('Research manifest differs')
            members_table='research_figure_members' if task['task_type']=='research_figure' else 'research_report_members'
            members=db.execute('SELECT * FROM '+members_table+' WHERE '+column+'=%s AND project_id=%s AND user_id=%s',(row['id'],project,owner)).fetchall()
            if not members:raise ValueError('Research members missing')
            for member in members:
                obj=scoped_object(db,project,owner,member['storage_object_id'])
                if any(obj[k]!=member[k] for k in ('sha256','size_bytes')):raise ValueError('Research member identity differs')
    return row


def audit_research_task_sources(db,limit=200):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid audit limit')
    rows=db.execute('SELECT * FROM tasks WHERE task_type=ANY(%s) ORDER BY id LIMIT %s',(list(RESEARCH_TASKS),limit)).fetchall();invalid=0
    for task in rows:
        try:validate_research_task_source(db,task)
        except Exception:invalid+=1
    total=db.execute('SELECT count(*) AS n FROM tasks WHERE task_type=ANY(%s)',(list(RESEARCH_TASKS),)).fetchone()['n']
    return [dict(table='tasks',column='research_typed_sources',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid)]
