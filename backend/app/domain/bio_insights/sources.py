"""Resolve seven fixed source types into verified, owner-scoped worker leaves."""
import csv
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard, RAW_MATRIX_KEYS
import hashlib
import io
import json
from pathlib import Path

from app.adapters.bio_analysis_store import BioAnalysisStore,scoped_object
from app.adapters.bio_insights_store import BioInsightsStore,invalid
from app.domain.bioinformatics.contracts import digest
from .contracts import FrozenInsightSource,InsightSourceSelection


def _tick(progress):
    if progress:progress()


def _truth(value):return value in (True,'True','true','1',1)


class InsightSourceReader(BioInsightsStore):
    def __init__(self,assets):
        super().__init__(assets);self.bio=BioAnalysisStore(assets)

    def _leaf(self,record,objects,progress=None):
        _tick(progress)
        path=objects.path(record['object_key'])
        self._verify(path,record,progress)
        return {key:record[key] for key in ('sha256','size_bytes')}|{'path':str(path),'format':record.get('format','json'),'role':record.get('role','input')}

    @staticmethod
    def _verify(path,record,progress=None):
        path=Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=record['size_bytes']:raise invalid()
        sha=hashlib.sha256()
        with path.open('rb') as stream:
            while chunk:=stream.read(1024*1024):
                sha.update(chunk);_tick(progress)
        if sha.hexdigest()!=record['sha256']:raise invalid()

    def original(self,db,project,file_id,parse_version_id=None,progress=None):
        self.store.require_project(db,project)
        file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s AND uploader_id=%s',
                        (file_id,project,self.store.user_id)).fetchone()
        if not file:raise invalid('bio_insight_not_found',404)
        file=dict(file)
        from app.adapters.object_storage import validate_key
        from app.domain.storage_governance.service import _key
        validate_key(file['object_key']);path=Path(self.assets.directory)/file['object_key']
        _key(self.assets.directory,path);self._verify(path,file,progress)
        parse=None
        if parse_version_id:
            parse=db.execute('SELECT p.*,t.status FROM file_parse_results p JOIN tasks t ON t.id=p.task_id WHERE p.id=%s AND p.file_id=%s AND t.project_id=%s AND t.user_id=%s',
                (parse_version_id,file_id,project,self.store.user_id)).fetchone()
            if not parse or parse['status']!='succeeded' or parse['source_sha256']!=file['sha256'] or not parse['result_json'] or not parse['completed_at']:
                raise invalid('bio_insight_parse_conflict')
            parse=dict(parse)
        fmt=file['filename'].lower().split('.')[-1]
        metadata=dict(filename=file['filename'],file_type=file['file_type'],parse_version_id=parse_version_id,
                      parser_version='bio_insight_table_v1',encoding='utf-8-sig',delimiter='\t' if fmt=='tsv' else ',',header_row=1,sheet=None)
        if parse:metadata.update(parsed_with=parse['parser_version'],parse_settings=parse['settings_json'],parse_summary=parse['result_json'])
        return file,metadata,{'original_file':dict(path=str(path),size_bytes=file['size_bytes'],sha256=file['sha256'],format=fmt,role='original_file')}

    def resolve(self,db,project,selection,*,progress=None):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._resolve_in_phase(db,project,selection,phase=phase,progress=progress)

    @phase_guard
    def _resolve_in_phase(self,db,project,selection,*,phase,lineage_only=False,progress=None,comparison_proof=False):
        require_phase(phase,db,self.assets,project)
        selection=InsightSourceSelection.model_validate(selection)
        kind=selection.source_kind;sid=selection.source_id;metadata={};members={};raw=None
        _tick(progress)
        self.store.require_project(db,project)
        if kind=='original_file':
            row,metadata,members=self.original(db,project,sid,selection.locator.parse_version_id,progress)
            sha=row['sha256']
        elif kind=='bio_processed_dataset_version':
            row,manifest,records=self.bio._processed_lineage_in_phase(db,project,sid,phase=phase,progress=progress)
            if self.store.require_task(db,row['task_id'])['status']!='succeeded':raise invalid('bio_insight_source_incomplete',422)
            sha=row['manifest_sha256']
            manifest_obj=scoped_object(db,project,self.store.user_id,row['manifest_object_id'])
            members={'manifest':self._leaf(manifest_obj,self.bio.objects,progress)}
            members.update({m['key']:self._leaf(m,self.bio.objects,progress) for m in records})
            raw_source=manifest.get('raw_source') or manifest['identity']['raw_source']
            _,raw_manifest,raw_records=self.bio._raw_lineage_in_phase(db,project,raw_source,phase=phase,progress=progress)
            raw_members={}
            for member in raw_records:
                if lineage_only and member['key'] in RAW_MATRIX_KEYS:
                    objects=self.bio.raw_store.objects
                    phase.verify_object(db,self.assets,project,objects,member,progress=progress)
                    # Unconsumed ancestry only. Scientific runtime keeps _leaf's full hash.
                    raw_members[member['key']]={key:member[key] for key in ('sha256','size_bytes')}|{'path':str(objects.path(member['object_key'])),'format':member.get('format','json'),'role':member.get('role','input')}
                else:raw_members[member['key']]=self._leaf(member,self.bio.raw_store.objects,progress)
            raw=dict(manifest=raw_manifest,members=raw_members)
            if raw_manifest.get('schema_version')==3:
                canonical=digest({key:raw_members[key]['sha256'] for key in ('matrix_values','matrix_missing','features_index','samples_index')})
                axes=json.loads(Path(raw_members['features_index']['path']).read_bytes())
                observations=[{**item,'processed_version_id':sid,'retained':_truth(item.get('kept'))} for item in self.read_rows(members['samples'])]
                scale=raw_manifest['scale'];feature_rows=list(self.read_rows(members['features']))
                metadata=dict(canonical_dataset_id=canonical,raw_dataset_version_id=raw_source['dataset_version_id'],raw_source=raw_source,
                    manifest=manifest,shape=row['shape_json'],source_file_ids=raw_source['source_file_ids'],observations=observations,
                    observation_level='sample',assay=raw_manifest['assay'],scale=scale,layers=manifest['layers'],feature_ids=axes['feature_ids'],
                    retained_feature_ids=[r['feature_id'] for r in feature_rows if _truth(r.get('kept'))],
                    **{field:scale.get(field) for field in ('species_taxon_id','namespace','reference_version')})
            else:
                canonical=digest({key:raw['members'][key]['sha256'] for key in ('matrix_data','matrix_indices','matrix_indptr','features_index','barcodes_index')})
                metadata=dict(canonical_dataset_id=canonical,raw_dataset_version_id=raw_source['dataset_version_id'],raw_source=raw_source,
                    manifest=manifest,shape=row['shape_json'],source_file_ids=raw_source['source_file_ids'])
                observations=[]
                for item in self.read_rows(members['observations']):
                    observations.append(dict(processed_version_id=sid,barcode=item['barcode'],donor=item.get('donor') or None,
                        condition=item.get('group') or None,batch=item.get('batch') or None,sample=item.get('sample_id') or None,
                        section=item.get('section') or None,retained=_truth(item.get('kept')),library_counts=int(item['total_counts']) if item.get('total_counts') else None))
                metadata['observations']=observations
                metadata.update(assay=raw_manifest.get('assay','visium'),observation_level='cell' if raw_manifest.get('assay')=='single_cell' else 'spot')
                axes=json.loads(Path(raw['members']['features_index']['path']).read_bytes())
                metadata['feature_ids']=[fid for fid,ft in zip(axes['feature_ids'],axes['feature_types']) if ft=='Gene Expression']
                for field in ('species_taxon_id','namespace','reference_version'):
                    metadata[field]=manifest.get(field) or raw_manifest.get(field)
        elif kind in ('bio_observation_map_version','bio_annotation_version'):
            table='bio_observation_map_versions' if kind=='bio_observation_map_version' else 'bio_annotation_versions'
            row=self.bio.require(db,table,project,sid)
            if kind=='bio_observation_map_version':
                obj=scoped_object(db,project,self.store.user_id,row['mapping_object_id'])
                if obj['sha256']!=row['mapping_sha256']:raise invalid()
                metadata=self.bio.mapping_objects.read_json(obj) if obj['object_key'].endswith('.json') else json.loads(self.bio.mapping_objects.read(obj))
                members={'observation_map':self._leaf(obj,self.bio.mapping_objects,progress)};sha=row['mapping_sha256']
                metadata['raw_dataset_version_id']=row['raw_dataset_version_id']
            else:
                from app.adapters.bio_objects import BioAnnotationObjects
                objects=BioAnnotationObjects(self.assets.directory)
                geometry=scoped_object(db,project,self.store.user_id,row['geometry_object_id'])
                assignments=scoped_object(db,project,self.store.user_id,row['assignments_object_id'])
                if geometry['sha256']!=row['geometry_sha256'] or assignments['sha256']!=row['assignments_sha256']:raise invalid()
                metadata=dict(geometry=json.loads(objects.read(geometry)),assignments=json.loads(objects.read(assignments)),
                    labels=row['labels_json'],checks=row['checks_json'],processed_dataset_version_id=row['processed_dataset_version_id'])
                sha=digest({'geometry_sha256':row['geometry_sha256'],'assignments_sha256':row['assignments_sha256']})
                members={'geometry':self._leaf(geometry,objects,progress),'assignments':self._leaf(assignments,objects,progress)}
        elif kind=='external_evidence_version':
            from app.domain.external_evidence.service import ExternalEvidenceService
            view=ExternalEvidenceService(self.assets).get(project,sid)
            if not view.get('typed_evidence'):raise invalid('bio_insight_source_incomplete',422)
            _,original,members=self.original(db,project,view['file_id'],progress=progress)
            sha=view['sha256'];metadata=dict(typed_evidence=view['typed_evidence'],locator_verification=view['locator_verification'],evidence_snapshot={k:v for k,v in view.items() if k!='sha256'},original_sha256=view['source']['source_sha256'],source_file_ids=[view['file_id']],filename=original['filename'])
        elif kind=='research_design_version':
            row=self.bio.design(db,project,sid)
            metadata=row['content_json'];sha=row['sha256']
            if digest(metadata)!=sha:raise invalid()
        elif kind in ('bio_resource_version','bio_insight_result_version'):
            resource=kind=='bio_resource_version';table='bio_resource_versions' if resource else 'bio_insight_result_versions'
            row=self.require(db,table,project,sid)
            task=self.store.require_task(db,row['task_id'])
            if task['status']!='succeeded' or not row['manifest_object_id']:raise invalid('bio_insight_source_incomplete',422)
            from .service import BioInsightsService
            upstream=BioInsightsService(self.assets)._require_sources_in_phase(db,task,phase=phase,runtime=False,progress=progress)
            from .results import checked_members
            manifest,records=checked_members(self,db,project,row,resource=resource,progress=progress)
            members={m['key']:self._leaf(m,self.objects,progress) for m in records if m['role'] not in ('input_snapshot','original_resource')}
            sha=row['manifest_sha256']
            metadata=dict(kind=row['kind'],manifest={key:manifest[key] for key in ('identity','summary','methods','engine_version','kind') if key in manifest},
                source_file_ids=sorted({s['source_id'] for s in upstream['sources'] if s['source_kind']=='original_file'}|
                    {fid for s in upstream['sources'] for fid in s.get('metadata',{}).get('source_file_ids',[])}),
                canonical_dataset_ids=sorted({s['metadata']['canonical_dataset_id'] for s in upstream['sources'] if s.get('metadata',{}).get('canonical_dataset_id')}|
                    {v for s in upstream['sources'] for v in s.get('metadata',{}).get('canonical_dataset_ids',[])}))
            if resource:
                metadata.update({key:row[key] for key in ('species_taxon_id','namespace','release','source_json','usage_json')})
                metadata['plan_config']=row['config_json']
                metadata.update({key:row['config_json'].get(key) for key in ('mapping_source_namespace','mapping_target_namespace')})
            else:
                metadata.update({key:row[key] for key in ('provenance','inference_scope','summary_json','methods_json')})
                plan=self.require(db,'bio_insight_plan_versions',project,row['plan_version_id'])
                metadata['plan_config']=plan['config_json']
                # Only C requests freeze this proof; shared/old result envelopes stay unchanged.
                if comparison_proof and row['kind']=='comparison':
                    fields=('canonical_dataset_id','species_taxon_id','namespace','reference_version','feature_ids','observations')
                    metadata['comparison_inputs']=[{key:s[key] for key in ('source_kind','source_id','sha256')}|
                        {'metadata':{key:s['metadata'].get(key) for key in fields}}
                        for s in upstream['sources'] if s['source_kind']=='bio_processed_dataset_version']
                for field in ('species_taxon_id','namespace','reference_version'):
                    value=plan['config_json'].get(field)
                    if value is None:
                        values={s.get('metadata',{}).get(field) for s in upstream['sources'] if s['source_kind']=='bio_insight_result_version'}-{None}
                        value=next(iter(values)) if len(values)==1 else None
                    if row['kind']=='feature_extract':value=row['methods_json'].get(field)
                    metadata[field]=value
                if row['kind']=='result_import' or plan['config_json'].get('schema_version')==3:
                    metadata['canonical_dataset_ids']=sorted(set(metadata['canonical_dataset_ids'])|
                        {'original_file_sha256:'+s['sha256'] for s in upstream['sources'] if s['source_kind']=='original_file'})
                    metadata['canonical_identity_scope']='exact_original_bytes_only; cross_format_data_identity_unknown'
                scopes={row['inference_scope']} if row['inference_scope'] not in ('derived','visualization') else set()
                for source in upstream['sources']:
                    scope=source['metadata'].get('inference_scope')
                    if scope and scope not in ('derived','visualization'):scopes.add(scope)
                    scopes.update(source['metadata'].get('upstream_inference_scopes',[]))
                metadata['upstream_inference_scopes']=sorted(scopes)
                metadata['data_driven_grouping']=bool(plan['config_json'].get('data_driven_grouping')) or any(s['metadata'].get('data_driven_grouping') for s in upstream['sources'])
        else:raise invalid('bio_insight_source_unsupported',422)
        if sha!=selection.sha256:raise invalid()
        self.verify_locator(selection,metadata,members,progress)
        frozen=FrozenInsightSource(**selection.model_dump(mode='json'),project_id=project)
        result={**frozen.model_dump(mode='json'),'metadata':metadata,'members':members}
        if raw:result['raw']=raw
        _tick(progress)
        return result

    @classmethod
    def verify_locator(cls,selection,metadata,members,progress=None):
        locator=selection.locator
        if locator.parse_version_id and selection.source_kind!='original_file':raise invalid('bio_insight_locator_invalid',422)
        if locator.member_key and locator.member_key not in members:raise invalid('bio_insight_locator_invalid',422)
        if locator.table and locator.table not in members:raise invalid('bio_insight_locator_invalid',422)
        if locator.kind=='object':return
        key=locator.member_key or locator.table
        if locator.kind in ('table','row'):
            if key is None:
                tables=[key for key,member in members.items() if member['format'] in ('csv','tsv')]
                if len(tables)!=1:raise invalid('bio_insight_locator_invalid',422)
                key=tables[0]
            if key not in members:raise invalid('bio_insight_locator_invalid',422)
            member=members[key]
            if locator.kind=='table':return
            if member['format'] not in ('csv','tsv'):raise invalid('bio_insight_locator_invalid',422)
            matches=0
            for number,row in enumerate(cls.read_rows(member)):
                if progress and number%1024==0:progress()
                if not set(locator.row_key)<=set(row) or locator.field and locator.field not in row:
                    raise invalid('bio_insight_locator_invalid',422)
                if all(row.get(field)==value for field,value in locator.row_key.items()):matches+=1
            if matches!=1:raise invalid('bio_insight_locator_invalid',422)
        elif locator.kind=='field':
            value=metadata
            for field in locator.field.split('.'):
                if not isinstance(value,dict) or field not in value:raise invalid('bio_insight_locator_invalid',422)
                value=value[field]
            if not (value is None or type(value) in (str,int,float,bool)):raise invalid('bio_insight_locator_invalid',422)

    @staticmethod
    def read_rows(member):
        if member['format'] not in ('tsv','csv'):raise invalid('bio_insight_table_unsupported',422)
        if member['size_bytes']>268435456:raise invalid('bio_insight_limit_exceeded',422)
        with Path(member['path']).open('r',encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream,delimiter='\t' if member['format']=='tsv' else ',',strict=True)
            if not reader.fieldnames or len(reader.fieldnames)>256 or len(set(reader.fieldnames))!=len(reader.fieldnames):raise invalid()
            for number,row in enumerate(reader):
                if number>=1000000 or None in row or any(v is None for v in row.values()):raise invalid('bio_insight_limit_exceeded',422)
                yield row

    def resolve_many(self,db,project,selections,config=None,progress=None):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._resolve_many_in_phase(db,project,selections,config,progress,phase=phase)

    @phase_guard
    def _resolve_many_in_phase(self,db,project,selections,config=None,progress=None,*,phase,lineage_only=False):
        require_phase(phase,db,self.assets,project)
        proof_ids={r.result_source_id for r in config.independent_support_requests} if config and config.kind=='candidate' and getattr(config,'schema_version',None)==2 else set()
        sources=[self._resolve_in_phase(db,project,s,phase=phase,lineage_only=lineage_only,progress=progress,
            **({'comparison_proof':True} if s.source_id in proof_ids and s.source_kind=='bio_insight_result_version' else {})) for s in selections]
        if config and config.kind=='comparison':
            processed=[s for s in sources if s['source_kind']=='bio_processed_dataset_version']
            for source in processed:
                if source['metadata'].get('observation_level')=='sample':continue
                metadata=source['metadata']
                for key in ('species_taxon_id','namespace','reference_version'):
                    if metadata.get(key) is None:metadata[key]=getattr(config,key)
                metadata['reference_metadata_origin']='upstream_if_available_else_explicit_plan_declaration'
                for mapping in [s for s in sources if s['source_kind']=='bio_observation_map_version']:
                    if mapping['metadata']['raw_dataset_version_id']!=metadata['raw_dataset_version_id']:continue
                    rows={r['barcode']:r for r in mapping['metadata']['rows']}
                    for obs in metadata['observations']:
                        row=rows.get(obs['barcode'],{})
                        for target,field in [('donor','donor'),('condition','group'),('batch','batch'),('sample','sample_id'),('section','section')]:
                            value=row.get(field,{})
                            obs[target]=value.get('value') if value.get('status')=='known' else None
            common=set.intersection(*(set(s['metadata']['feature_ids']) for s in processed)) if processed else set()
            for source in processed:source['metadata']['common_feature_count']=len(common)
        return sources

    def catalog(self,project,kind,page=1,page_size=20):
        from app.db.bio_insights_schema import SOURCE_TARGETS
        if kind not in SOURCE_TARGETS:raise invalid('bio_insight_source_unsupported',422)
        table=SOURCE_TARGETS[kind][1]
        owner='uploader_id' if kind=='original_file' else 'created_by' if kind in ('bio_processed_dataset_version','bio_observation_map_version','bio_annotation_version','research_design_version') else 'user_id'
        with self.store.connection() as db:
            self.store.require_project(db,project)
            total=db.execute('SELECT count(*) AS n FROM '+table+' WHERE project_id=%s AND '+owner+'=%s',(project,self.store.user_id)).fetchone()['n']
            rows=db.execute('SELECT * FROM '+table+' WHERE project_id=%s AND '+owner+'=%s ORDER BY '+('uploaded_at' if kind=='original_file' else 'created_at')+' DESC,id LIMIT %s OFFSET %s',
                            (project,self.store.user_id,page_size,(page-1)*page_size)).fetchall()
            items=[]
            for row in rows:
                sha=row.get('manifest_sha256') or row.get('mapping_sha256') or row.get('content_sha256') or row.get('sha256')
                if kind=='bio_annotation_version':sha=digest({'geometry_sha256':row['geometry_sha256'],'assignments_sha256':row['assignments_sha256']})
                item=dict(source_kind=kind,source_id=row['id'],sha256=sha,title=row.get('title') or row.get('name') or row.get('filename') or row['id'])
                if kind=='bio_processed_dataset_version':
                    raw=db.execute('SELECT v.version,d.name,d.assay FROM bio_dataset_versions v JOIN bio_datasets d ON d.id=v.dataset_id AND d.project_id=v.project_id WHERE v.id=%s AND v.project_id=%s',
                        (row['raw_dataset_version_id'],project)).fetchone()
                    if raw:item.update(assay=raw['assay'],observation_level='cell' if raw['assay']=='single_cell' else 'spot' if raw['assay']=='visium' else 'sample',title=raw['name']+' / processed '+row['id'][:8],dataset_name=raw['name'],raw_version=raw['version'],recipe_version_id=row['recipe_version_id'])
                if kind=='bio_insight_result_version':
                    plan=db.execute('SELECT p.name FROM bio_insight_plan_versions v JOIN bio_insight_plans p ON p.id=v.plan_id WHERE v.id=%s AND v.project_id=%s',(row['plan_version_id'],project)).fetchone()
                    item.update(title=row['kind']+' / '+(plan['name'] if plan else row['id']),kind=row['kind'],inference_scope=row['inference_scope'])
                if kind=='external_evidence_version':item.update(title=row['snapshot_json']['title'],kind=(row['snapshot_json'].get('typed_evidence') or {}).get('evidence_type'))
                if kind=='original_file':
                    parse=db.execute('SELECT id FROM file_parse_results WHERE file_id=%s AND completed_at IS NOT NULL AND result_json IS NOT NULL ORDER BY version DESC LIMIT 1',(row['id'],)).fetchone()
                    item.update(parse_version_id=parse['id'] if parse else None,filename=row['filename'],file_type=row['file_type'])
                items.append(item)
        return dict(items=items,total=total,page=page,page_size=page_size)

    def observations(self,project,kind,identifier,page=1,page_size=100):
        catalog=self.catalog(project,kind,page=1,page_size=100000)
        item=next((i for i in catalog['items'] if i['source_id']==identifier),None)
        if not item:raise invalid('bio_insight_not_found',404)
        with self.store.connection() as db:
            source=self.resolve(db,project,dict(source_kind=kind,source_id=identifier,sha256=item['sha256']))
            rows=source['metadata'].get('observations') or source['metadata'].get('rows') or []
            if kind=='bio_processed_dataset_version' and source['metadata'].get('observation_level')!='sample':
                original={r['barcode']:r for r in self.read_rows(source['members']['observations'])}
                rows=[{**row,'cluster':original[row['barcode']].get('cluster') or None} for row in rows]
            if kind=='bio_annotation_version':rows=source['metadata']['assignments'].get('rows',[])
        groups={field:sorted({str(r[field]) for r in rows if r.get(field) is not None}) for field in ('cluster','condition','donor','batch','section','label_id')}
        return dict(assay=source['metadata'].get('assay'),observation_level=source['metadata'].get('observation_level','spot'),layers=source['metadata'].get('layers'),scale=source['metadata'].get('scale'),items=rows[(page-1)*page_size:page*page_size],total=len(rows),page=page,page_size=page_size,sha256=item['sha256'],groups=groups,
            raw_dataset_version_id=source['metadata'].get('raw_dataset_version_id'),
            processed_dataset_version_id=identifier if kind=='bio_processed_dataset_version' else source['metadata'].get('processed_dataset_version_id'))
