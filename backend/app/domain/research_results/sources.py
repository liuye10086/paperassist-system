"""Resolve typed formal sources with exact ownership, bytes and locations."""
import csv
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard
from datetime import date,datetime
import hashlib
import io
import json

from app.adapters.bio_analysis_store import BioAnalysisStore,scoped_object
from app.adapters.bio_figure_store import BioFigureStore
from app.adapters.research_results_store import ResearchResultsStore,invalid
from app.domain.bioinformatics.contracts import digest
from .contracts import FrozenResearchSource,ResearchSourceSelection,ResearchLocator,ResearchFactCatalog
from .bio_projection import project_bio_facts
from .external_projection import project_external_facts


def document_page_items(items,page):
    selected=[item for item in items if item.get('location',{}).get('page_number')==page]
    if not selected:raise invalid('research_locator_invalid',422)
    return selected


class ResearchSourceReader(ResearchResultsStore):
    def __init__(self,assets):
        super().__init__(assets);self.bio=BioAnalysisStore(assets)

    def read_source(self,project,selection,*,db=None,chain=(),progress=None):
        if db is None:
            with self.store.connection() as connection:
                return self.read_source(project,selection,db=connection,chain=chain,progress=progress)
        with VerificationPhase(db,self.assets,project) as phase:
            return self._read_source_in_phase(project,selection,db=db,phase=phase,chain=chain,progress=progress)

    @phase_guard
    def _read_source_in_phase(self,project,selection,*,db,phase,chain=(),progress=None):
        require_phase(phase,db,self.assets,project)
        if progress is not None:progress()
        selection=ResearchSourceSelection.model_validate(selection)
        token=(selection.source_kind,selection.source_id)
        if token in chain or len(chain)>=16:raise invalid()
        self.store.require_project(db,project)
        kind=selection.source_kind
        allowed={'analysis_run':('object','field','image'),'bio_processed_dataset_version':('object','field'),'bio_analysis_artifact':('object','row'),
            'bio_figure_version':('object','image'),'original_file':('object','cell','page','image'),
            'external_evidence_version':('object',),'research_finding_version':('object',),
            'research_report_version':('object',),'research_figure_version':('object','image'),
            'bio_insight_result_version':('object','field','image'),'bio_insight_result_member':('object','row','image')}
        if selection.locator.kind not in allowed[kind]:raise invalid('research_locator_invalid',422)
        if kind!='original_file' and (selection.locator.parse_version_id or selection.locator.original_sha256):
            raise invalid('research_locator_invalid',422)
        if kind=='analysis_run':
            from .statistics_sources import read_statistics_source
            value=read_statistics_source(self,db,project,selection,progress=progress)
        elif kind in ('bio_processed_dataset_version','bio_analysis_artifact'):
            value=self._bio(db,project,selection,phase=phase,progress=progress)
        elif kind in ('bio_insight_result_version','bio_insight_result_member'):
            from .insight_sources import read_insight_source
            value=read_insight_source(self,db,project,selection,progress,phase=phase)
        elif kind=='bio_figure_version':value=self._bio_figure(db,project,selection)
        elif kind=='original_file':value=self._original(db,project,selection)
        elif kind=='external_evidence_version':
            from app.domain.external_evidence.service import ExternalEvidenceService
            value=ExternalEvidenceService(self.assets).get(project,selection.source_id)
            value=dict(title=value['title'],sha256=value['sha256'],provenance='external_result',
                source_file_ids=[value['file_id']],content={'evidence':value})
        elif kind in ('research_finding_version','research_report_version','research_figure_version'):
            table={'research_finding_version':'research_finding_versions','research_report_version':'research_report_versions','research_figure_version':'research_figure_versions'}[kind]
            row=self.require(db,table,project,selection.source_id)
            if kind=='research_figure_version':
                if not row['manifest_object_id']:raise invalid('research_source_incomplete',422)
                value={'config':row['config_json']}
                if digest(row['config_json'])!=row['config_sha256']:raise invalid()
                sha=row['manifest_sha256'];value.update(manifest_sha256=sha)
                from .figure_members import research_figure_source
                value.update(research_figure_source(self,db,project,row,progress=progress))
            else:
                value=self.verify_content(row);sha=row['content_sha256']
                if kind=='research_report_version':
                    if not row['manifest_object_id']:raise invalid('research_source_incomplete',422)
                    from .reports import ResearchReportService
                    ResearchReportService(self.assets).checked_members(db,project,row,progress=progress)
            if kind!='research_finding_version':self._completed(db,row['task_id'])
            bindings=db.execute('SELECT * FROM research_source_bindings WHERE project_id=%s AND '+{'research_finding_version':'finding','research_report_version':'report','research_figure_version':'figure'}[kind]+'_version_id=%s ORDER BY id',(project,row['id'])).fetchall()
            source_files=set();resolved={}
            for ref in bindings:
                src=self._read_source_in_phase(project,dict(source_kind=ref['source_kind'],source_id=ref['source_id'],sha256=ref['source_sha256'],locator=ref['locator_json']),db=db,phase=phase,chain=(*chain,token),progress=progress)
                source_files.update(src.source_file_ids)
                resolved[(ref['source_kind'],ref['source_id'],digest(ref['locator_json']),ref['source_sha256'])]=src
            if kind=='research_finding_version':
                expected=value['sources']
                expected_ids={(s['source_kind'],s['source_id'],digest(s['locator']),s['sha256']) for s in expected}
                actual_ids={(s['source_kind'],s['source_id'],digest(s['locator_json']),s['source_sha256']) for s in bindings}
                if actual_ids!=expected_ids:raise invalid()
                for frozen in expected:
                    # The exact binding was fully validated above in this same
                    # transaction and recursion chain; compare its frozen value
                    # without hashing every upstream matrix a second time.
                    current=resolved[(frozen['source_kind'],frozen['source_id'],digest(frozen['locator']),frozen['sha256'])]
                    if current.model_dump(mode='json')!=frozen:raise invalid()
            value=dict(title=value.get('title',row['id']),sha256=sha,provenance='research_derived',source_file_ids=sorted(source_files),content=value)
        else:raise invalid('research_source_unsupported',422)
        if selection.sha256 is not None and selection.sha256!=value['sha256']:raise invalid()
        if progress is not None:progress()
        try:return FrozenResearchSource(**{**selection.model_dump(mode='json'),**value,'project_id':project})
        except ValueError as exc:
            if kind=='analysis_run':raise invalid('research_source_limit_exceeded',422) from exc
            raise

    def _completed(self,db,task_id):
        task=self.store.require_task(db,task_id)
        if task['status']!='succeeded':raise invalid('research_source_incomplete',422)
        return task

    def _bio(self,db,project,selection,*,phase,progress=None):
        artifact=None
        if selection.source_kind=='bio_analysis_artifact':
            artifact=self.bio.require(db,'bio_analysis_artifacts',project,selection.source_id)
            processed_id=artifact['processed_dataset_version_id']
        else:processed_id=selection.source_id
        row,manifest,members=self.bio._processed_lineage_in_phase(db,project,processed_id,phase=phase,progress=progress)
        self._completed(db,row['task_id'])
        raw=manifest.get('raw_source') or manifest['identity']['raw_source']
        _,raw_manifest=self.bio.raw_store.require_version(db,project,raw['dataset_id'],raw['dataset_version_id'])
        accessions=raw_manifest.get('source_accessions') or raw_manifest.get('checks',{}).get('source_accessions',{})
        provenance='public_reanalysis' if any(accessions.values()) else 'system_computed'
        content={k:manifest[k] for k in ('summary','params','steps','engine_version','code_digest','environment_digest','identity','tables','observation_level','assay','scale','layers','methods') if k in manifest}
        content.update(processed_version_id=processed_id,raw_source=raw,source_accessions=accessions)
        sha=row['manifest_sha256'];title=('Single-cell analysis ' if manifest.get('observation_level')=='cell' else '样本定量分析 / Sample quantitative analysis ' if manifest.get('observation_level')=='sample' else '空间分析 / Spatial analysis ')+processed_id
        if artifact:
            member=next(m for m in members if m['id']==artifact['id'])
            if member['format'] not in ('tsv','txt','json'):raise invalid('research_source_unsupported',422)
            raw_bytes=self.bio.objects.read(member);sha=member['sha256'];title=member['key']
            if member['format']=='tsv':
                rows=[];total=0;wanted=selection.locator.row_key;matches=0
                reader=csv.DictReader(io.StringIO(raw_bytes.decode('utf-8')),delimiter='\t',strict=True)
                if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)):raise invalid()
                for item in reader:
                    total+=1
                    if None in item:raise invalid()
                    match=not wanted or all(item.get(k)==v for k,v in wanted.items())
                    if match:
                        matches+=1
                        if len(rows)<50:rows.append(item)
                if wanted and matches!=1:raise invalid('research_locator_invalid',422)
                content={'table_key':member['key'],'rows':rows,'total_rows':total,'processed_version_id':processed_id}
                if selection.locator.kind=='row' and selection.locator.column not in reader.fieldnames:raise invalid('research_locator_invalid',422)
            elif member['format']=='txt':content={'text':raw_bytes.decode('utf-8'),'processed_version_id':processed_id}
            else:
                parsed=json.loads(raw_bytes)
                if len(raw_bytes)>2*1024*1024:raise invalid('research_source_limit_exceeded',422)
                content={'metadata':parsed,'processed_version_id':processed_id}
        if manifest.get('observation_level') in ('sample','cell'):content.update(observation_level=manifest['observation_level'],assay=manifest['assay'])
        return dict(title=title,sha256=sha,provenance=provenance,source_file_ids=raw['source_file_ids'],content=content)

    def _bio_figure(self,db,project,selection):
        figures=BioFigureStore(self.assets);row=figures.require(db,'bio_figure_versions',project,selection.source_id)
        self._completed(db,row['task_id']);view=figures.get(project,row['id'])
        if not row['manifest_sha256']:raise invalid('research_source_incomplete',422)
        return dict(title=view['config'].get('kind','Figure'),sha256=row['manifest_sha256'],provenance='research_derived',
            source_file_ids=view['processed_source']['raw_source']['source_file_ids'],
            content={'figure':view},figures=[{'figure_version_id':row['id'],**m} for m in view['members']])

    def _original(self,db,project,selection):
        row=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(selection.source_id,project)).fetchone()
        if not row:raise invalid('research_source_not_found',404)
        row=dict(row);raw=self.assets.original(row)
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise invalid()
        locator=selection.locator;content={'file_type':row['file_type'],'filename':row['filename'],'size_bytes':row['size_bytes']}
        if locator.original_sha256 is not None and locator.original_sha256!=row['sha256']:raise invalid()
        if locator.kind=='cell':
            if row['file_type']!='xlsx':raise invalid('research_locator_invalid',422)
            if row['parse_status']!='parsed':raise invalid('research_source_incomplete',422)
            from openpyxl import load_workbook
            workbook=load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
            try:
                if locator.sheet not in workbook.sheetnames:raise invalid('research_locator_invalid',422)
                cell=workbook[locator.sheet][locator.cell]
                if cell.data_type=='f':
                    content.update(cell_value=None,gaps=['公式单元格未重算；请提供固定结果值。'])
                else:
                    value=cell.value
                    if isinstance(value,(datetime,date)):value=value.isoformat()
                    if not (value is None or type(value) in (str,int,float,bool)):raise invalid('research_locator_invalid',422)
                    content['cell_value']=value
            finally:workbook.close()
        elif locator.parse_version_id:
            from app.domain.external_evidence.service import ExternalEvidenceService
            source,items,_,_=ExternalEvidenceService(self.assets)._source(project,row['id'],'document_version',locator.parse_version_id)
            if locator.kind=='page':items=document_page_items(items,locator.page)
            content.update(parsed_source=source,items=items)
        elif locator.kind not in ('object','image'):
            raise invalid('research_locator_invalid',422)
        return dict(title=row['filename'],sha256=row['sha256'],provenance='external_result',source_file_ids=[row['id']],content=content)

    def catalog(self,source):
        if source.source_kind=='analysis_run':
            from .statistics_projection import project_statistics_facts
            try:return project_statistics_facts(source)
            except (ValueError,KeyError,TypeError) as exc:raise invalid('research_locator_invalid',422) from exc
        if source.source_kind in ('bio_insight_result_version','bio_insight_result_member'):
            from .insight_projection import project_insight_facts
            try:return project_insight_facts(source)
            except (ValueError,KeyError,TypeError) as exc:raise invalid('research_output_invalid',422) from exc
        if source.source_kind in ('bio_processed_dataset_version','bio_analysis_artifact'):
            try:
                result=project_bio_facts(source)
                if source.locator.kind in ('field','row'):
                    result.facts=[f for f in result.facts if (f.locator.field_path==source.locator.field_path
                        if source.locator.kind=='field' else f.locator.column==source.locator.column and f.locator.row_key==source.locator.row_key)]
                    if not result.facts:raise invalid('research_locator_invalid',422)
                return result
            except ValueError as exc:raise invalid('research_output_invalid',422) from exc
        if source.source_kind in ('original_file','external_evidence_version'):return project_external_facts(source)
        if source.source_kind=='research_finding_version':
            return ResearchFactCatalog(source=source,**{k:source.content.get(k,[]) for k in ('facts','methods','gaps','warnings','limitations','conflicts') if k!='conflicts'})
        return ResearchFactCatalog(source=source)

    def preview(self,project,selections):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            sources=[self.read_source(project,s,db=db) for s in selections]
        catalogs=[self.catalog(source).model_dump(mode='json') for source in sources]
        return {'catalogs':catalogs,'sha256':digest(catalogs),'real_model_calls':0,'external_results_recomputed':False}
