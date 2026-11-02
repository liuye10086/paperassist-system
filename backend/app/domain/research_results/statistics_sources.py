"""Owner/project-bound immutable analysis runs with their original receipt identity."""
from app.adapters.research_results_store import invalid
from app.domain.bioinformatics.contracts import digest

def read_statistics_source(reader,db,project,selection,*,progress=None):
    row=db.execute('SELECT r.* FROM analysis_runs r JOIN files f ON f.id=r.file_id WHERE r.id=%s AND f.project_id=%s',
        (selection.source_id,project)).fetchone()
    if not row:raise invalid('research_source_not_found',404)
    if not row['completed_at']:raise invalid('research_source_incomplete',422)
    from app.adapters.storage import ProjectStore
    import hashlib
    result=ProjectStore.analysis_run_value(row)
    ProjectStore.validate_analysis_result(reader.assets,project,row['file_id'],result)
    record=reader.assets.file(project,row['file_id'])
    if hashlib.sha256(reader.assets.original(record)).hexdigest()!=result['source_sha256']:raise invalid()
    if result.get('source') and not result.get('result_type'):
        from app.domain.dataset_analysis import load_dataset
        load_dataset(reader.assets,project,row['file_id'],result['source']['dataset_id'],expected_source=result['source'])
    if not result.get('completed_at') or result['completed_at']!=row['completed_at']:raise invalid('research_source_incomplete',422)
    from app.domain.statistics_execution.verification import require_receipt
    verified=require_receipt(reader.assets,project,row['file_id'],result)
    task=db.execute("SELECT id,status,input_snapshot FROM tasks WHERE project_id=%s AND task_type='statistics_compute' AND result_analysis_run_id=%s ORDER BY created_at DESC LIMIT 1",(project,row['id'])).fetchone()
    if task and task['status']!='succeeded':raise invalid('research_source_incomplete',422)
    language=result.get('analysis_context',{}).get('plan',{}).get('research_request',{}).get('output_language','unknown')
    content=dict(result=result,result_sha256=digest(result),execution_verification='verified' if verified else 'legacy_unverified',
        output_language=language,task_id=task['id'] if task else None,
        source_identity=dict(project_id=project,analysis_run_id=row['id'],source_file_id=row['file_id'],source_sha256=result['source_sha256'],
            setup_revision=result['setup_revision'],prepared_source=result.get('source'),analysis_plan=result.get('analysis_plan')))
    roles=result.get('selection',{}).get('data_roles')
    if roles and result.get('source'):
        from app.domain.dataset_analysis import load_dataset
        from app.domain.statistics_roles import StatisticsDataRoles,sheet_records
        _,_,sheet=load_dataset(reader.assets,project,row['file_id'],result['source']['dataset_id'],expected_source=result['source'])
        content['role_records']=sheet_records(sheet,StatisticsDataRoles.model_validate(roles))
        if result['selection']['task_type']=='descriptive_boxplot':
            from openpyxl.utils.cell import column_index_from_string
            from app.domain.dataset_profile.scan import missing
            cells={(c.row,c.column):c for c in sheet.cells};included=[];excluded=[]
            s=result['selection'];columns=[s['numeric_column']]+([s['group_column']] if s.get('group_column') else [])
            for item in content['role_records']:
                row_index=item['row'];absent=[col+str(row_index) for col in columns if missing(cells.get((row_index,column_index_from_string(col))))]
                if absent:excluded.append(dict(row=row_index,coordinates=absent,reason='selected_missing'))
                else:included.append(row_index)
            content['frozen_role_audit']=dict(included_rows=included,excluded_rows=excluded,origin='reconstructed_from_frozen_source_not_a_new_test')
    if result.get('result_type')=='group_comparison':
        from app.domain.comparison.service import load_comparison_input
        content['frozen_plot']=dict(groups=load_comparison_input(reader.assets,project,row['file_id'],result)['groups'],included_rows=result['row_audit']['included_rows'],group_rows=result['row_audit']['group_rows'])
    elif result.get('result_type')=='correlation':
        from app.domain.correlation.service import load_correlation_input
        content['frozen_plot']=dict(rows=load_correlation_input(reader.assets,project,row['file_id'],result)['rows'],included_rows=result['row_audit']['included_rows'])
    if progress:progress()
    return dict(title=result['filename']+' / '+result['selection'].get('method','descriptive_statistics'),sha256=digest(result),
        provenance='system_computed',source_file_ids=[row['file_id']],content=content)
