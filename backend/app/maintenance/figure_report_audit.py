"""Read-only integrity checks for configuration and collection histories.

These checks inspect saved relational/JSON contracts. Asset-byte validation is
performed separately by consumers/downloads and migration retention manifests.
"""
import json
import re
from app.adapters.report_store import digest


def audit_figure_reports(db):
    checks=[]
    names=('figure_configurations','figure_config_versions','figure_projection_decisions','figure_projection_results',
           'report_collections','report_collection_versions','report_collection_items','report_build_requests','collection_reports')
    rows={name:{r['id']:r for r in db.execute('SELECT * FROM '+name)} for name in names}
    projects={r['id']:r for r in db.execute('SELECT id,owner_id FROM projects')}
    runs={r['id']:r for r in db.execute('SELECT * FROM analysis_runs')}
    files={r['id']:r for r in db.execute('SELECT id,project_id FROM files')}
    tasks={r['id']:r for r in db.execute('SELECT * FROM tasks')}
    figures={r['id']:r for r in db.execute('SELECT * FROM figures')}
    explanations={r['id']:r for r in db.execute('SELECT * FROM explanations')}
    def check(table,predicate):
        invalid=0
        for row in rows[table].values():
            try:
                if not predicate(row): invalid+=1
            except (KeyError,TypeError,ValueError,IndexError): invalid+=1
        checks.append(dict(table=table,column='figure_report_integrity',rows=len(rows[table]),invalid=invalid))
    def config(v): return rows['figure_configurations'][v['configuration_id']]
    def version(row): return rows['report_collection_versions'][row['version_id']]
    def collection(v): return rows['report_collections'][v['collection_id']]
    def hexadecimal(value): return isinstance(value,str) and bool(re.fullmatch(r'[0-9a-f]{64}',value))
    def config_valid(row):
        return (files[runs[row['analysis_run_id']]['file_id']]['project_id']==row['project_id']
                and projects[row['project_id']]['owner_id']==row['created_by']
                and row['current_revision']==max(v['revision'] for v in rows['figure_config_versions'].values() if v['configuration_id']==row['id']))
    check('figure_configurations',config_valid)
    def config_version_valid(r):
        result=json.loads(runs[config(r)['analysis_run_id']]['result_json'])
        expected={'source':result['source'],'result_sha256':digest(result),'analysis_plan':result['analysis_plan']}
        if 'figure_contract' in r['source_json']:
            if type(r['source_json']['figure_contract']) is not int or r['source_json']['figure_contract'] not in (2,3):return False
            expected['figure_contract']=r['source_json']['figure_contract']
        return (r['created_by']==config(r)['created_by'] and r['source_json']==expected
            and r['sha256']==digest({'config':r['config_json'],'source':r['source_json']})
            and (r['parent_version_id'] is None or rows['figure_config_versions'][r['parent_version_id']]['configuration_id']==r['configuration_id']))
    check('figure_config_versions',config_version_valid)
    def decision_valid(r):
        cfg=config(rows['figure_config_versions'][r['config_version_id']]); task=tasks[r['task_id']]
        return (r['approved_by']==cfg['created_by']==task['user_id'] and task['project_id']==cfg['project_id']
                and task['task_type']=='figure_projection' and task['status']=='succeeded'
                and hexadecimal(r['input_sha256']) and isinstance(r['decision_json'],dict))
    check('figure_projection_decisions',decision_valid)
    check('figure_projection_results',lambda r: r['sha256']==digest(r['result_json']) and (
        r['decision_id'] is None or rows['figure_projection_decisions'][r['decision_id']]['config_version_id']==r['config_version_id']))
    check('report_collections',lambda r: projects[r['project_id']]['owner_id']==r['created_by']
        and r['current_version_id'] is not None and rows['report_collection_versions'][r['current_version_id']]['collection_id']==r['id'])
    def snapshot_sources_valid(snapshot,v):
        # A request/task/report can share a forged digest. Anchor every frozen
        # input to its collection's ordered results and the actual saved runs.
        return (snapshot['language']==v['language'] and snapshot['sources']==[v['source_json']]
            and bool(snapshot['items']) and len(snapshot['items'])==len(v['content_json']['items'])
            and files[v['source_json']['file_id']]['project_id']==collection(v)['project_id']
            and all(item['result']==frozen['result']==json.loads(runs[item['result']['id']]['result_json'])
                and item['result']['source']==v['source_json']
                for item,frozen in zip(snapshot['items'],v['content_json']['items'])))
    def collection_version_valid(r):
        return r['sha256']==digest(r['content_json']) and snapshot_sources_valid(r['content_json'],r)
    check('report_collection_versions',collection_version_valid)
    def item_valid(r):
        v=version(r); saved=v['content_json']['items'][r['position']-1]
        if r['item_json']!=saved or r['sha256']!=digest(saved) or r['figure_number']!=r['position']: return False
        if r['analysis_run_id']!=saved['result']['id'] or saved['result']!=json.loads(runs[r['analysis_run_id']]['result_json']): return False
        if r['figure_id'] is not None and (figures[r['figure_id']]['analysis_run_id']!=r['analysis_run_id'] or saved['figure']['id']!=r['figure_id']): return False
        if r.get('figure_config_version_id') is not None and r['figure_config_version_id']!=saved['configuration']['id']: return False
        if r['explanation_id'] is not None and (explanations[r['explanation_id']]['figure_id']!=r['figure_id'] or saved['explanation']['id']!=r['explanation_id']): return False
        return True
    check('report_collection_items',item_valid)
    def request_valid(r):
        v=version(r); c=collection(v)
        if r['request_digest']!=digest({'version_id':v['id'],'sha256':v['sha256'],'request_key':r['request_key']}): return False
        if r['input_json'] is None: return r['input_sha256'] is None and r['task_id'] is None and r['status'] in ('waiting','blocked')
        t=tasks[r['task_id']]
        return (r['input_sha256']==digest(r['input_json']) and t['input_snapshot']==r['input_json']
                and snapshot_sources_valid(r['input_json'],v)
                and t['task_type']=='collection_word_report' and t['project_id']==c['project_id'] and t['user_id']==c['created_by']
                and r['input_json']['collection_version_id']==v['id'] and r['input_json']['export_revision']==r['export_revision'])
    check('report_build_requests',request_valid)
    def report_valid(r):
        q=rows['report_build_requests'][r['build_request_id']]; m=r['report_json']
        return (q['version_id']==r['version_id'] and q['export_revision']==r['export_revision'] and q['status']=='succeeded'
                and r['input_json']==q['input_json'] and m['input_sha256']==digest(r['input_json'])
                and snapshot_sources_valid(r['input_json'],version(r))
                and m['sha256']==r['sha256'] and hexadecimal(r['sha256']) and m['id']==r['id'])
    check('collection_reports',report_valid)
    invalid=total=0
    for r in figures.values():
        if r['figure_config_version_id'] is None: continue
        total+=1
        try:
            v=rows['figure_config_versions'][r['figure_config_version_id']]; m=json.loads(r['figure_json'])
            p=rows['figure_projection_results'][m['projection_id']]
            if (r['analysis_run_id']!=config(v)['analysis_run_id'] or m['figure_config_version_id']!=v['id']
                    or m['configuration_sha256']!=v['sha256'] or m['projection_sha256']!=p['sha256']
                    or m['numbering_mode']!='external' or m['figure_number'] is not None): invalid+=1
        except (KeyError,TypeError,ValueError): invalid+=1
    checks.append(dict(table='figures',column='configuration_binding',rows=total,invalid=invalid))
    return checks
