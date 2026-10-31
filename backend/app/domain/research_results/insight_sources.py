"""Exact B04 version/member resolution into the existing B03 source contract."""
import csv
import io

from app.adapters.bio_insights_store import BioInsightsStore
from app.adapters.research_results_store import invalid
from app.domain.bio_insights.service import BioInsightsService
from app.domain.bio_insights.sources import InsightSourceReader
from app.domain.bio_insights.results import checked_members


def read_insight_source(reader,db,project,selection,progress=None,*,phase):
    service=BioInsightsService(reader.assets);member=None
    if selection.source_kind=='bio_insight_result_member':
        member=service.require(db,'bio_insight_result_members',project,selection.source_id)
        identifier=member['result_version_id']
    else:identifier=selection.source_id
    row=service.require(db,'bio_insight_result_versions',project,identifier)
    task=service.store.require_task(db,row['task_id'])
    if task['status']!='succeeded':raise invalid('research_source_incomplete',422)
    payload=service._require_sources_in_phase(db,task,phase=phase,runtime=False,progress=progress)
    manifest,members=checked_members(service,db,project,row,progress=progress)
    source_files=sorted({s['source_id'] for s in payload['sources'] if s['source_kind']=='original_file'}|
        {fid for s in payload['sources'] for fid in s.get('metadata',{}).get('source_file_ids',[])})
    content=dict(result_version_id=identifier,kind=row['kind'],inference_scope=row['inference_scope'],provenance=row['provenance'],
        summary=row['summary_json'],methods=row['methods_json'],config=payload['config'],
        engine_version=payload['identity'].get('engine_version'),code_digest=row['code_digest'],environment_digest=row['environment_digest'],
        members=[{key:m[key] for key in ('id','key','role','format','sha256','size_bytes')} for m in members])
    scopes={row['inference_scope']} if row['inference_scope'] not in ('derived','visualization') else set()
    for source in payload['sources']:
        scope=source['metadata'].get('inference_scope')
        if scope and scope not in ('derived','visualization'):scopes.add(scope)
        scopes.update(source['metadata'].get('upstream_inference_scopes',[]))
    content['upstream_inference_scopes']=sorted(scopes)
    content['data_driven_grouping']=bool(payload['config'].get('data_driven_grouping')) or any(s['metadata'].get('data_driven_grouping') for s in payload['sources'])
    sha=row['manifest_sha256'];title=row['kind']+' / '+identifier
    if member:
        current=next((m for m in members if m['id']==member['id']),None)
        if current is None:raise invalid()
        sha=member['sha256'];title=member['key'];content['member']=dict(current)
        # Internal storage keys are used only by this reader, never in frozen
        # content or the public source/preview response.
        content['member'].pop('object_key',None)
        content['member'].pop('storage_object_id',None)
        content['member'].pop('user_id',None);content['member'].pop('created_at',None)
        if member['format'] in ('csv','tsv'):
            raw=service.objects.read(current);rows=[];total=matches=0;columns=[]
            table=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')),delimiter='\t' if member['format']=='tsv' else ',',strict=True)
            columns=table.fieldnames or []
            if not columns or len(columns)!=len(set(columns)):raise invalid('research_output_invalid',422)
            locator=selection.locator
            if locator.table and locator.table!=member['key']:raise invalid('research_locator_invalid',422)
            if locator.kind=='row' and locator.column not in columns:raise invalid('research_locator_invalid',422)
            for item in table:
                total+=1
                if None in item or any(value is None for value in item.values()):raise invalid('research_output_invalid',422)
                if locator.row_key and not all(item.get(key)==value for key,value in locator.row_key.items()):continue
                matches+=1
                if len(rows)<50:rows.append(item)
                if progress and total%1024==0:progress()
            if locator.row_key and matches!=1:raise invalid('research_locator_invalid',422)
            content.update(table_key=member['key'],columns=columns,rows=rows,total_rows=total)
        elif selection.locator.kind not in ('object','image'):raise invalid('research_locator_invalid',422)
    elif selection.locator.kind=='field':
        path=selection.locator.field_path
        if not path or not path.startswith(('summary.','methods.')):raise invalid('research_locator_invalid',422)
        value=content
        for key in path.split('.'):
            if not isinstance(value,dict) or key not in value:raise invalid('research_locator_invalid',422)
            value=value[key]
        if not (value is None or type(value) in (str,int,float,bool)):raise invalid('research_locator_invalid',422)
    figures=[m for m in content['members'] if m['format'] in ('png','jpeg','tiff','svg','pdf')]
    return dict(title=title,sha256=sha,provenance=row['provenance'],source_file_ids=source_files,content=content,figures=figures)
