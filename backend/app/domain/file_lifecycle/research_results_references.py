"""Formal research history rooted in frozen file identities and source bindings."""
from app.domain.bioinformatics.contracts import digest
from app.maintenance.research_results_audit import validate_research_task_source,source_refs


def read_groups(db,file,user_id):
    from .references import file_ids
    project=file['project_id'];groups={};selected={}
    tasks={r['id']:r for r in db.execute("SELECT * FROM tasks WHERE project_id=%s AND task_type IN ('research_figure','research_report','research_fact_draft')",(project,))}
    linked_tasks={key for key,task in tasks.items() if file['id'] in file_ids(task['input_snapshot'])}
    for table in ('research_finding_versions','research_figure_versions','research_report_versions','research_manuscript_candidates','manuscript_research_sources'):
        rows=[]
        for raw in db.execute('SELECT * FROM '+table+' WHERE project_id=%s',(project,)):
            row=dict(raw);content=row.get('content_json',row.get('source_json',{}));linked=row.get('task_id') in linked_tasks
            linked |= any(file['id'] in s.get('source_file_ids',[]) or s['source_kind']=='original_file' and s['source_id']==file['id'] for s in source_refs(content))
            if not linked:continue
            valid=row['user_id']==user_id
            try:
                if row.get('task_id'):validate_research_task_source(db,tasks[row['task_id']])
                elif 'content_json' in row:valid &= digest(row['content_json'])==row['content_sha256']
            except Exception:valid=False
            row['_integrity_valid']=bool(valid);rows.append(row)
        groups[table]=rows;selected[table]={r['id'] for r in rows}
    for table,parent,column in (
        ('research_figure_members','research_figure_versions','figure_version_id'),
        ('research_report_members','research_report_versions','report_version_id')):
        rows=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE '+column+'=ANY(%s)',(list(selected[parent]),))]
        valid={r['id']:r['_integrity_valid'] for r in groups[parent]}
        for row in rows:row['_integrity_valid']=bool(valid.get(row[column]) and row['user_id']==user_id and row['project_id']==project)
        groups[table]=rows
    rows=[dict(r) for r in db.execute('SELECT * FROM research_source_bindings WHERE file_id=%s OR finding_version_id=ANY(%s) OR figure_version_id=ANY(%s) OR report_version_id=ANY(%s)',
        (file['id'],list(selected['research_finding_versions']),list(selected['research_figure_versions']),list(selected['research_report_versions'])))]
    for row in rows:row['_integrity_valid']=row['user_id']==user_id and row['project_id']==project
    groups['research_source_bindings']=rows
    return groups
