"""Resolve complete selected B02 tables; preview rows never define exports."""
import csv
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard
import io
from .sources import ResearchSourceReader
from app.adapters.research_results_store import invalid


def collect_tables(reader,db,project,sources,*,progress=None):
    with VerificationPhase(db,reader.assets,project) as phase:
        return _collect_tables_in_phase(reader,db,project,sources,phase=phase,progress=progress)


@phase_guard
def _collect_tables_in_phase(reader,db,project,sources,*,phase,progress=None):
    require_phase(phase,db,reader.assets,project)
    processed=set();artifacts=set();insights=set()
    def visit(source,depth=0):
        if depth>16:raise invalid()
        kind=source['source_kind'];content=source.get('content',{})
        if kind=='bio_processed_dataset_version':processed.add(source['source_id'])
        elif kind=='bio_analysis_artifact':artifacts.add(source['source_id'])
        elif kind=='bio_insight_result_version':insights.add(source['source_id'])
        elif kind=='bio_insight_result_member':
            identifier=content.get('result_version_id')
            if identifier:insights.add(identifier)
            else:
                from app.adapters.bio_insights_store import BioInsightsStore
                member=BioInsightsStore(reader.assets).require(db,'bio_insight_result_members',project,source['source_id'])
                insights.add(member['result_version_id'])
        for child in content.get('sources',[]):visit(child,depth+1)
        if kind=='research_report_version':
            for child in content.get('finding',{}).get('content',{}).get('sources',[]):visit(child,depth+1)
    for source in sources:visit(source)
    for identity in artifacts:
        row=reader.bio.require(db,'bio_analysis_artifacts',project,identity)
        processed.add(row['processed_dataset_version_id'])
    tables=[];raws=[];cells=0
    for identity in sorted(processed):
        if progress is not None:progress()
        _,_,members=reader.bio._processed_lineage_in_phase(db,project,identity,phase=phase,progress=progress)
        for member in members:
            if member['format']!='tsv' or (member['key'] not in ('observations','features','cluster_summary','markers') and member['id'] not in artifacts):continue
            if progress is not None:progress()
            raw=reader.bio.objects.read(member);csvreader=csv.reader(io.StringIO(raw.decode('utf-8')),delimiter='\t',strict=True)
            columns=next(csvreader,None)
            if not columns or len(set(columns))!=len(columns):raise invalid('research_output_invalid',422)
            count=0
            for row in csvreader:
                if len(row)!=len(columns):raise invalid('research_output_invalid',422)
                count+=1
                if progress is not None and count%1024==0:progress()
            cells+=(count+1)*len(columns)
            if cells>5_000_000:raise invalid('research_export_limit_exceeded',422)
            tables.append(dict(key=member['key'],columns=columns,expected_rows=count,source=dict(source_kind='bio_analysis_artifact',source_id=member['id'],processed_version_id=identity),sha256=member['sha256']))
            raws.append(raw)
            if progress is not None:progress()
    if insights:
        from app.domain.bio_insights.service import BioInsightsService
        from app.domain.bio_insights.results import checked_members
        service=BioInsightsService(reader.assets)
        for identifier in sorted(insights):
            row=service.require(db,'bio_insight_result_versions',project,identifier)
            service._require_sources_in_phase(db,service.store.require_task(db,row['task_id']),phase=phase,runtime=False,progress=progress)
            _,members=checked_members(service,db,project,row,progress=progress)
            for member in members:
                if member['format'] not in ('tsv','csv'):continue
                if progress:progress()
                raw=service.objects.read(member);csvreader=csv.reader(io.StringIO(raw.decode('utf-8-sig')),delimiter='\t' if member['format']=='tsv' else ',',strict=True)
                columns=next(csvreader,None)
                if not columns or len(columns)!=len(set(columns)):raise invalid('research_output_invalid',422)
                count=0
                for item in csvreader:
                    if len(item)!=len(columns):raise invalid('research_output_invalid',422)
                    count+=1
                    if progress and count%1024==0:progress()
                cells+=(count+1)*len(columns)
                if cells>5000000:raise invalid('research_export_limit_exceeded',422)
                tables.append(dict(key=member['key'],columns=columns,expected_rows=count,
                    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],result_version_id=identifier),
                    sha256=member['sha256'],provenance=row['provenance'],inference_scope=row['inference_scope']))
                raws.append(raw)
    return tables,raws
