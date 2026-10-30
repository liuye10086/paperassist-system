"""Scoped persistent mapping, recipes and bounded processed-result reads."""
import csv
import io
import json
import hashlib
from datetime import datetime,timezone
from uuid import UUID,uuid5
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore
from app.adapters.bio_objects import BioAnalysisObjects,BioMappingObjects
from app.adapters.bio_dataset_store import BioDatasetStore
from app.domain.bioinformatics.contracts import canonical,digest,conflict
from app.domain.bioinformatics.service import BioDatasetService,require_key
from app.domain.bioinformatics.analysis_contracts import (BioObservationRow,BioObservationMapPreviewRequest,
    BioProcessedDatasetSourceV1,BioRecipeParameters,ENGINE_VERSION)
from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits,runtime_identity
from app.core.exceptions import StorageError
from app.domain.storage_governance import service as ledger
from app.db.bio_analysis_schema import TABLE_NAMES

NAMESPACE=UUID('b7ced6d2-cd28-4fb1-9627-3d9cdd7ec7ae')

def identity(project,kind,key):return str(uuid5(NAMESPACE,project+':'+kind+':'+key))
def now():return datetime.now(timezone.utc)
def error(code,status=409):return StorageError(code,'生信来源、参数或版本需要重新核对。',status)
def insert(db,table,row):
    if table not in TABLE_NAMES:raise ValueError('Unregistered table')
    columns=list(row)
    if any(not k.replace('_','').isalnum() for k in columns):raise ValueError('Invalid column')
    db.execute('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join(['%s']*len(columns))+')',
        tuple(Jsonb(row[k]) if isinstance(row[k],(dict,list)) else row[k] for k in columns))
def lock(db,project,key):db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(project+':'+key,))
def base_row(identifier,project,owner):return dict(id=identifier,project_id=project,created_by=owner,created_at=now(),schema_version=1)

def scoped_object(db,project,owner,identifier):
    row=db.execute('''SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id
        WHERE o.id=%s AND o.state='present' AND r.project_id=%s AND r.owner_id=%s''',(identifier,project,owner)).fetchone()
    if not row:raise conflict('bio_input_integrity_changed')
    return dict(row)

def object_by_key(db,project,owner,record):
    row=db.execute('''SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id
        WHERE o.namespace='local:assets-v1' AND o.object_key=%s AND o.state='present'
          AND r.project_id=%s AND r.owner_id=%s''',(record['object_key'],project,owner)).fetchone()
    if not row or any(row[k]!=record[k] for k in ('sha256','size_bytes')):raise conflict('bio_input_integrity_changed')
    return dict(row)


class BioAnalysisStore:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
        self.raw_store=BioDatasetStore(assets);self.objects=BioAnalysisObjects(assets.directory)
        self.mapping_objects=BioMappingObjects(assets.directory)

    def require(self,db,table,project,identifier):
        self.store.require_project(db,project)
        if table not in TABLE_NAMES:raise ValueError('Invalid table')
        row=db.execute(f'SELECT * FROM {table} WHERE id=%s AND project_id=%s',(identifier,project)).fetchone()
        if not row:raise error({'bio_analysis_runs':'bio_analysis_not_found','bio_analysis_recipe_versions':'bio_recipe_not_found',
            'bio_observation_map_versions':'bio_mapping_not_found','bio_processed_dataset_versions':'bio_processed_not_found',
            'bio_figure_versions':'bio_figure_not_found','bio_annotation_versions':'bio_annotation_not_found'}.get(table,'bio_analysis_not_found'),404)
        if row['created_by']!=self.store.user_id:raise error('bio_input_integrity_changed')
        return dict(row)

    def raw(self,db,project,source,*,verify=True):
        if hasattr(source,'model_dump'):source=source.model_dump(mode='json')
        self.store.require_project(db,project)
        if source['project_id']!=project:raise conflict('bio_input_integrity_changed')
        row,manifest=self.raw_store.require_version(db,project,source['dataset_id'],source['dataset_version_id'])
        expected=BioDatasetService.source(row,[f['id'] for f in manifest['source_files']])
        if expected!=source:raise conflict('bio_input_integrity_changed')
        members=self.raw_store.members(db,row);frozen={m['id']:m for m in manifest['members']}
        if {m['id'] for m in members}!=set(frozen):raise conflict('bio_input_integrity_changed')
        for member in members:
            self.raw_store.verify_member(member,frozen.get(member['id']))
            member['key']=frozen[member['id']]['key']
            if verify:self.raw_store.objects.read(member)
        if verify:
            task=self.store.require_task(db,row['task_id'])
            BioDatasetService(self.assets).require_sources(db,task)
        return row,manifest,members

    def axes(self,db,project,source):
        raw,manifest,members=self.raw(db,project,source)
        lookup={m['key']:m for m in members}
        read=lambda key:json.loads(self.raw_store.objects.read(lookup[key]))
        return raw,manifest,members,read('barcodes_index')['barcodes'],read('features_index')

    def design(self,db,project,identifier):
        if identifier is None:return None
        row=db.execute('SELECT * FROM research_design_versions WHERE id=%s AND project_id=%s',(identifier,project)).fetchone()
        if not row or row['created_by']!=self.store.user_id:raise error('bio_mapping_invalid',422)
        return dict(row)

    def validate_rows(self,db,project,source,rows,design_id):
        _,_,_,barcodes,_=self.axes(db,project,source);known=set(barcodes)
        design=self.design(db,project,design_id)
        samples={s['id'] for s in design['content_json']['samples']} if design else set()
        seen=set()
        for value in rows:
            row=BioObservationRow.model_validate(value).model_dump()
            if row['barcode'] in seen or row['barcode'] not in known:raise error('bio_mapping_invalid',422)
            seen.add(row['barcode'])
            if row['sample_id']['status']=='known' and row['sample_id']['value'] not in samples:raise error('bio_mapping_invalid',422)
        return dict(mapped=len(rows),unmapped=len(barcodes)-len(rows),total=len(barcodes))

    def admit_documents(self,project,identifier,kind,objects,documents):
        entries=[(key,objects.describe(identifier,content,json=False),content) for key,content in documents.items()]
        reservations=[]
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project)
            for key,record,_ in entries:
                row=ledger.reserve(db,self.assets.directory,project,kind+':'+identifier+':'+key,
                    objects.path(record['object_key']),record['size_bytes'],sha256=record['sha256'],kind=kind)
                reservations.append(dict(row))
            for row in reservations:ledger._journal(db,self.assets.directory,row)
        for _,record,content in entries:objects.write(record,content)
        return {key:record for key,record,_ in entries},reservations

    def settle_documents(self,db,project,records,reservations):
        for row in reservations:ledger.settle(db,self.assets.directory,row['id'])
        return {key:object_by_key(db,project,self.store.user_id,record) for key,record in records.items()}

    def mapping(self,project,set_id,version_id,page=1,page_size=50):
        with self.store.connection() as db:
            row=self.require(db,'bio_observation_map_versions',project,version_id)
            if row['set_id']!=set_id:raise error('bio_mapping_not_found',404)
            root=self.require(db,'bio_observation_map_sets',project,set_id)
            obj=scoped_object(db,project,self.store.user_id,row['mapping_object_id'])
            if obj['sha256']!=row['mapping_sha256']:raise conflict('bio_input_integrity_changed')
            value=json.loads(self.mapping_objects.read(obj));self.raw(db,project,value['raw_source'])
            rows=value['rows'];start=(page-1)*page_size
            return dict(id=row['id'],set_id=set_id,name=value['name'],version=row['version'],revision=row['version'],
                raw_source=value['raw_source'],design_version_id=row['design_version_id'],counts=row['counts_json'],
                rows=rows[start:start+page_size],total=len(rows),page=page,page_size=page_size)

    def save_mapping(self,project,request,key,set_id=None):
        require_key(key);material=request.model_dump(mode='json');sha=digest(material)
        identifier=identity(project,'map',key);root_id=set_id or identifier
        with self.store.connection() as db:
            self.store.require_project(db,project)
            replay=db.execute('SELECT * FROM bio_observation_map_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha or (set_id and replay['set_id']!=set_id):raise error('task_idempotency_conflict')
                return self.mapping(project,replay['set_id'],replay['id'])
        rows=[r.model_dump() for r in request.rows]
        if request.table_source:
            parsed=self.preview_mapping(project,BioObservationMapPreviewRequest(raw_source=request.raw_source,
                file_id=request.table_source.file_id,sheet=request.table_source.sheet,mapping=request.table_source.mapping,
                design_version_id=request.design_version_id),internal=True)
            if parsed['source']['sha256']!=request.table_source.sha256 or parsed['errors']:raise error('bio_mapping_invalid',422)
            rows=parsed['all_rows']
        with self.store.connection() as db:
            counts=self.validate_rows(db,project,request.raw_source,rows,request.design_version_id)
        content=canonical(dict(schema_version=1,name=request.name,raw_source=request.raw_source.model_dump(),design_version_id=request.design_version_id,
            table_source=request.table_source.model_dump() if request.table_source else None,rows=rows))
        records,reserved=self.admit_documents(project,identifier,'bio_mapping',self.mapping_objects,{'mapping':content})
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);lock(db,project,'map:'+key)
            replay=db.execute('SELECT * FROM bio_observation_map_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise error('task_idempotency_conflict')
            else:
                counts=self.validate_rows(db,project,request.raw_source,rows,request.design_version_id)
                if set_id:
                    db.execute('SELECT id FROM bio_observation_map_sets WHERE id=%s AND project_id=%s FOR UPDATE',(set_id,project))
                    root=self.require(db,'bio_observation_map_sets',project,set_id)
                    if root['revision']!=request.expected_revision or root['raw_dataset_version_id']!=request.raw_source.dataset_version_id:raise conflict('bio_revision_conflict')
                    parent=root['current_version_id'];version=root['revision']+1
                else:
                    if request.expected_revision!=0:raise conflict('bio_revision_conflict')
                    parent=None;version=1
                    insert(db,'bio_observation_map_sets',{**base_row(root_id,project,self.store.user_id),'raw_dataset_version_id':request.raw_source.dataset_version_id,
                        'name':request.name,'revision':1,'current_version_id':None,'updated_at':now()})
                objects=self.settle_documents(db,project,records,reserved)
                insert(db,'bio_observation_map_versions',{**base_row(identifier,project,self.store.user_id),'set_id':root_id,'version':version,
                    'parent_id':parent,'raw_dataset_version_id':request.raw_source.dataset_version_id,'design_version_id':request.design_version_id,
                    'mapping_object_id':objects['mapping']['id'],'mapping_sha256':records['mapping']['sha256'],'counts_json':counts,
                    'table_source_file_id':request.table_source.file_id if request.table_source else None,'request_key':key,'request_digest':sha})
                # First pointer assignment is performed with the same CAS progression as later versions.
                changed=db.execute('UPDATE bio_observation_map_sets SET revision=CASE WHEN current_version_id IS NULL THEN revision ELSE revision+1 END,current_version_id=%s,name=%s,updated_at=%s WHERE id=%s AND revision=%s',
                    (identifier,request.name,now(),root_id,version if set_id is None else request.expected_revision))
                if changed.rowcount!=1:raise conflict('bio_revision_conflict')
        return self.mapping(project,root_id,identifier)

    def preview_mapping(self,project,request,internal=False):
        from app.domain.research_intake.service import _xlsx_sample_text
        with self.store.connection() as db:
            self.store.require_project(db,project);self.raw(db,project,request.raw_source)
            row=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(request.file_id,project)).fetchone()
            if not row:raise error('bio_mapping_invalid',422)
            file=dict(row)
            if file['file_type']=='xlsx' and file['parse_status']=='parsed':
                text,sheet_name=_xlsx_sample_text(self.assets,file,request.sheet,max_rows=20000,max_text_bytes=16777216);delimiter=','
            elif file['file_type']=='bio_component' and file['filename'].lower().endswith(('.csv','.tsv')):
                if file['size_bytes']>16777216:raise error('bio_resource_exceeded')
                text=self.assets.original(file).decode('utf-8-sig');delimiter='\t' if file['filename'].lower().endswith('.tsv') else ',';sheet_name=None
            else:raise error('bio_mapping_invalid',422)
            reader=csv.DictReader(io.StringIO(text),delimiter=delimiter,strict=True);headers=reader.fieldnames or []
            if len(headers)!=len(set(headers)) or len(headers)>100 or any(v not in headers for v in request.mapping.values()):raise error('bio_mapping_invalid',422)
            _,_,_,barcodes,_=self.axes(db,project,request.raw_source);known=set(barcodes)
            design=self.design(db,project,request.design_version_id);samples={s['id'] for s in design['content_json']['samples']} if design else set()
            rows=[];errors=[];seen=set();total=0
            try:
                for number,row in enumerate(reader,2):
                    total+=1
                    if total>20000:raise error('bio_resource_exceeded')
                    try:
                        if None in row or any(v is None for v in row.values()):raise ValueError('columns')
                        values={k:(row[column] or '').strip() for k,column in request.mapping.items()}
                        value=BioObservationRow.model_validate({k:v if k=='barcode' else {'status':'known' if v else 'pending','value':v or None} for k,v in values.items()}).model_dump()
                        if value['barcode'] not in known or value['barcode'] in seen:raise ValueError('barcode')
                        if value['sample_id']['status']=='known' and value['sample_id']['value'] not in samples:raise ValueError('sample')
                        seen.add(value['barcode']);rows.append(value)
                    except ValueError:
                        if len(errors)<100:errors.append(dict(row=number,code='bio_mapping_invalid',message='Invalid barcode, sample or columns'))
            except (csv.Error,UnicodeError) as exc:raise error('bio_mapping_invalid',422) from exc
            result=dict(source=dict(file_id=file['id'],sha256=file['sha256'],sheet_name=sheet_name),headers=headers,preview_rows=rows[:20],
                total=total,valid=len(rows),errors=errors,counts=dict(mapped=len(rows),unmapped=len(barcodes)-len(rows),total=len(barcodes)),
                table_source=dict(file_id=file['id'],sha256=file['sha256'],sheet=request.sheet,mapping=request.mapping))
            if internal:result['all_rows']=rows
            return result

    def recipe_view(self,db,row):
        raw=db.execute('SELECT * FROM bio_dataset_versions WHERE id=%s AND project_id=%s',(row['raw_dataset_version_id'],row['project_id'])).fetchone()
        _,manifest=self.raw_store.require_version(db,row['project_id'],raw['dataset_id'],raw['id'])
        mapping=db.execute('SELECT set_id FROM bio_observation_map_versions WHERE id=%s',(row['observation_map_version_id'],)).fetchone() if row['observation_map_version_id'] else None
        return dict(id=row['id'],setup_id=row['setup_id'],version=row['version'],revision=row['version'],raw_source=BioDatasetService.source(raw,[f['id'] for f in manifest['source_files']]),
            observation_map_version_id=row['observation_map_version_id'],observation_map_set_id=mapping['set_id'] if mapping else None,
            design_version_id=row['design_version_id'],recipe_code=row['recipe_code'],params=row['params_json'])

    def recipe(self,project,setup_id,version_id):
        with self.store.connection() as db:
            row=self.require(db,'bio_analysis_recipe_versions',project,version_id)
            if row['setup_id']!=setup_id:raise error('bio_recipe_not_found',404)
            return self.recipe_view(db,row)

    def setup(self,project,setup_id):
        with self.store.connection() as db:
            row=self.require(db,'bio_analysis_setups',project,setup_id)
            recipe=self.recipe_view(db,self.require(db,'bio_analysis_recipe_versions',project,row['current_recipe_version_id']))
            return dict(id=row['id'],name=row['name'],revision=row['revision'],raw_source=recipe['raw_source'],current_recipe_version_id=row['current_recipe_version_id'],current_recipe=recipe)

    def save_recipe(self,project,request,key,setup_id=None):
        require_key(key);sha=digest(request.model_dump(mode='json'));identifier=identity(project,'recipe',key)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);lock(db,project,'recipe:'+key)
            replay=db.execute('SELECT * FROM bio_analysis_recipe_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha or (setup_id and replay['setup_id']!=setup_id):raise error('task_idempotency_conflict')
                return self.recipe_view(db,replay)
            _,_,_,barcodes,features=self.axes(db,project,request.raw_source)
            if not set(request.params.exclude_barcodes)<=set(barcodes) or not set(request.params.mt_rule.feature_ids)<=set(features['feature_ids']):raise error('bio_recipe_invalid',422)
            self.design(db,project,request.design_version_id)
            if request.observation_map_version_id:
                mapping=self.require(db,'bio_observation_map_versions',project,request.observation_map_version_id)
                if mapping['raw_dataset_version_id']!=request.raw_source.dataset_version_id or mapping['design_version_id']!=request.design_version_id:raise conflict('bio_input_integrity_changed')
            root_id=setup_id or identifier
            if setup_id:
                db.execute('SELECT id FROM bio_analysis_setups WHERE id=%s AND project_id=%s FOR UPDATE',(setup_id,project))
                root=self.require(db,'bio_analysis_setups',project,setup_id)
                if root['revision']!=request.expected_revision or root['raw_dataset_version_id']!=request.raw_source.dataset_version_id:raise conflict('bio_revision_conflict')
                version=root['revision']+1;parent=root['current_recipe_version_id']
            else:
                if request.expected_revision!=0:raise conflict('bio_revision_conflict')
                version=1;parent=None
                insert(db,'bio_analysis_setups',{**base_row(root_id,project,self.store.user_id),'raw_dataset_version_id':request.raw_source.dataset_version_id,
                    'name':request.name,'revision':1,'current_recipe_version_id':None,'updated_at':now()})
            insert(db,'bio_analysis_recipe_versions',{**base_row(identifier,project,self.store.user_id),'setup_id':root_id,'version':version,'parent_id':parent,
                'raw_dataset_version_id':request.raw_source.dataset_version_id,'observation_map_version_id':request.observation_map_version_id,
                'design_version_id':request.design_version_id,'recipe_code':'visium_explore_v1','params_json':request.params.model_dump(),
                'default_figures_json':['qc','pca','umap','marker_dotplot','marker_heatmap','spatial_cluster','spatial_gene'],
                'engine_contract_version':ENGINE_VERSION,'request_key':key,'request_digest':sha})
            changed=db.execute('UPDATE bio_analysis_setups SET revision=CASE WHEN current_recipe_version_id IS NULL THEN revision ELSE revision+1 END,current_recipe_version_id=%s,name=%s,updated_at=%s WHERE id=%s AND revision=%s',
                (identifier,request.name,now(),root_id,version if not setup_id else request.expected_revision))
            if changed.rowcount!=1:raise conflict('bio_revision_conflict')
            return self.recipe_view(db,self.require(db,'bio_analysis_recipe_versions',project,identifier))


    def capabilities(self,project,dataset_id,version_id):
        with self.store.connection() as db:
            row,manifest=self.raw_store.require_version(db,project,dataset_id,version_id)
            source=BioDatasetService.source(row,[f['id'] for f in manifest['source_files']])
            self.raw(db,project,source,verify=False)
        runtime=runtime_identity();blockers=list(runtime['blockers'])
        shape=manifest.get('input_shape',{})
        if shape.get('observations',0)>20000 or shape.get('features',0)>100000:blockers.append('bio_resource_exceeded')
        return dict(raw_source=source,available=not blockers,blockers=blockers,limits=BioAnalysisLimits().model_dump(),
            recipes=['visium_explore_v1'],design_gaps=['independent_donor_design_not_confirmed'],default_params=BioRecipeParameters().model_dump(),runtime=runtime)

    def processed_record(self,db,project,identifier):
        row=self.require(db,'bio_processed_dataset_versions',project,identifier)
        obj=scoped_object(db,project,self.store.user_id,row['manifest_object_id'])
        if obj['sha256']!=row['manifest_sha256']:raise conflict('bio_input_integrity_changed')
        manifest=self.objects.read_json(obj)
        if manifest.get('identity',{}).get('recipe_version_id')!=row['recipe_version_id']:raise conflict('bio_input_integrity_changed')
        raw_source=manifest.get('raw_source') or manifest.get('identity',{}).get('raw_source')
        self.raw(db,project,raw_source)
        rows=db.execute('SELECT * FROM bio_analysis_artifacts WHERE processed_dataset_version_id=%s AND project_id=%s ORDER BY key',(identifier,project)).fetchall()
        frozen={m['id']:m for m in manifest['members']};members=[]
        if set(frozen)!={m['id'] for m in rows}:raise conflict('bio_input_integrity_changed')
        for item in rows:
            expected=frozen[item['id']]
            if any(item[k]!=expected[k] for k in ('key','role','format','sha256','size_bytes')):raise conflict('bio_input_integrity_changed')
            record=scoped_object(db,project,self.store.user_id,item['storage_object_id'])
            if record['sha256']!=item['sha256'] or record['size_bytes']!=item['size_bytes']:raise conflict('bio_input_integrity_changed')
            members.append({**dict(item),'object_key':record['object_key']})
        return row,manifest,members

    @staticmethod
    def processed_source(row,manifest):
        return BioProcessedDatasetSourceV1(project_id=row['project_id'],processed_dataset_version_id=row['id'],analysis_run_id=row['run_id'],
            raw_source=manifest.get('raw_source') or manifest['identity']['raw_source'],recipe_version_id=row['recipe_version_id'],
            manifest_sha256=row['manifest_sha256'],engine_version=row['engine_version'],environment_digest=row['environment_digest']).model_dump(mode='json')

    def public_member(self,project,version,item):
        result={k:item[k] for k in ('id','key','role','format','sha256','size_bytes')}
        result.update(analysis_artifact_id=item['id'],filename=item['key']+'.'+item['format'],
            download_url=f'/api/v1/projects/{project}/bio-processed-datasets/{version}/members/{item["id"]}/download')
        return result

    def processed(self,project,identifier):
        with self.store.connection() as db:
            row,manifest,members=self.processed_record(db,project,identifier)
            figures=[dict(r) for r in db.execute('SELECT id FROM bio_figure_versions WHERE processed_dataset_version_id=%s AND project_id=%s ORDER BY created_at,id',(identifier,project))]
        from app.adapters.bio_figure_store import BioFigureStore
        return dict(id=identifier,source=self.processed_source(row,manifest),manifest_sha256=row['manifest_sha256'],shape=row['shape_json'],steps=row['steps_json'],
            manifest=manifest,tables=manifest.get('tables',[]),members=[self.public_member(project,identifier,m) for m in members],
            figures=[BioFigureStore(self.assets).get(project,f['id']) for f in figures])

    def member(self,project,identifier,member_id):
        with self.store.connection() as db:
            _,_,members=self.processed_record(db,project,identifier)
            member=next((m for m in members if m['id']==member_id),None)
            if not member:raise error('bio_member_not_found',404)
            return {**member,'filename':member['key']+'.'+member['format']},self.objects.read(member)

    def table(self,project,identifier,key,page=1,page_size=50,query=None,cluster=None,sort_by=None,order='asc'):
        with self.store.connection() as db:
            _,manifest,members=self.processed_record(db,project,identifier)
            allowed={t['key'] for t in manifest.get('tables',[])}
            member=next((m for m in members if m['key']==key and m['format']=='tsv'),None)
            if key not in allowed or not member:raise error('bio_member_not_found',404)
            content=self.objects.read(member).decode('utf-8')
        reader=csv.DictReader(io.StringIO(content),delimiter='\t');columns=reader.fieldnames or []
        if sort_by is not None and sort_by not in columns:raise error('bio_recipe_invalid',422)
        total=0;items=[];start=(page-1)*page_size;sorted_rows=[]
        for row in reader:
            if query and not any(query.casefold() in (row.get(k) or '').casefold() for k in ('feature_id','symbol','barcode')):continue
            if cluster is not None and row.get('cluster')!=cluster:continue
            if sort_by:
                if total>=100000:raise error('bio_resource_exceeded')
                sorted_rows.append(row)
            elif start<=total<start+page_size:items.append(row)
            total+=1
        if sort_by:
            def keyfn(row):
                value=row.get(sort_by) or ''
                try:return (0,float(value))
                except ValueError:return (1,value)
            sorted_rows.sort(key=keyfn,reverse=order=='desc');items=sorted_rows[start:start+page_size]
        return dict(key=key,columns=columns,items=items,total=total,page=page,page_size=page_size,sort_by=sort_by,order=order)

    def coordinates(self,project,identifier):
        with self.store.connection() as db:
            _,manifest,members=self.processed_record(db,project,identifier)
            raw_source=manifest.get('raw_source') or manifest['identity']['raw_source']
            _,raw_manifest,raw_members=self.raw(db,project,raw_source)
            observation=next((m for m in members if m['key']=='observations'),None)
            if not observation:raise error('bio_output_invalid')
            rows=list(csv.DictReader(io.StringIO(self.objects.read(observation).decode('utf-8')),delimiter='\t'))
            if len(rows)>20000:raise error('bio_resource_exceeded')
            points=[dict(barcode=r['barcode'],raw_index=int(r['raw_index']),x=float(r['x']) if r.get('x') else None,
                y=float(r['y']) if r.get('y') else None,kept=r['kept'] in ('True','true'),exclusion=(r.get('exclusion_reasons') or '').split(';') if r.get('exclusion_reasons') else [],cluster=r.get('cluster') or None) for r in rows]
            spatial=raw_manifest.get('spatial',{});images=[]
            for info in spatial.get('images',[]):
                item=next((m for m in raw_members if m.get('source_member_name')==info.get('source_member_name')),None)
                if item and info.get('scale_field'):
                    images.append(dict(id=item['id'],width=info['width'],height=info['height'],scale=spatial['scalefactors'][info['scale_field']],
                        download_url=self.raw_store.base(project,raw_source['dataset_id'],raw_source['dataset_version_id'])+f'/members/{item["id"]}/download'))
            value=dict(points=points,total=len(points),coordinate_space='fullres',spatial=spatial,images=images,
                spot_diameter_fullres=spatial.get('scalefactors',{}).get('spot_diameter_fullres'))
            if len(canonical(value))>2097152:raise error('bio_resource_exceeded')
            return value

    def matrix_preview(self,project,identifier,layer='log1p',features_page=1,observations_page=1):
        import numpy as np
        with self.store.connection() as db:
            _,manifest,members=self.processed_record(db,project,identifier)
            if layer not in ('counts','normalized','log1p') or layer not in manifest['layers']:raise error('bio_recipe_invalid',422)
            lookup={m['key']:m for m in members}
            def read(key):
                item=lookup[key];self.objects.read(item)
                return self.objects.path(item['object_key'])
            data=np.load(read(layer+'_data'),mmap_mode='r',allow_pickle=False);indices=np.load(read(layer+'_indices'),mmap_mode='r',allow_pickle=False);indptr=np.load(read(layer+'_indptr'),mmap_mode='r',allow_pickle=False)
            axes=json.loads(read('raw_axes').read_bytes());om=np.load(read('observation_mask'),allow_pickle=False);fm=np.load(read('feature_mask'),allow_pickle=False)
            feature_ids=[(i,v) for i,v in enumerate(axes['feature_ids']) if fm[i]];barcodes=[b for i,b in enumerate(axes['barcodes']) if om[i]]
            f0,o0=(features_page-1)*40,(observations_page-1)*20;chosen=feature_ids[f0:f0+40];selected=barcodes[o0:o0+20];values=[]
            for obs in range(o0,o0+len(selected)):
                row=[0]*len(chosen)
                for index,value in zip(indices[indptr[obs]:indptr[obs+1]],data[indptr[obs]:indptr[obs+1]]):
                    if f0<=index<f0+len(chosen):row[int(index)-f0]=value.item()
                values.append(row)
            return dict(features=[dict(id=v,symbol=axes['feature_symbols'][i],feature_type=axes['feature_types'][i]) for i,v in chosen],observations=selected,
                values=values,features_total=len(feature_ids),observations_total=len(barcodes),features_page=features_page,observations_page=observations_page)

    def request(self,project,key,kind):
        require_key(key)
        mapping={'map':('bio_observation_map_versions','set_id'),'recipe':('bio_analysis_recipe_versions','setup_id'),
            'run':('bio_analysis_runs',None),'annotation':('bio_annotation_versions','set_id'),'figure':('bio_figure_versions','root_id')}
        with self.store.connection() as db:
            self.store.require_project(db,project)
            if kind in ('import','import_confirmation'):
                if kind=='import':
                    rows=db.execute('SELECT id,dataset_id,task_id,request_digest FROM bio_imports WHERE project_id=%s AND request_key=%s',(project,key)).fetchall()
                else:
                    rows=db.execute("""SELECT i.id,i.dataset_id,i.task_id,c.state_json->'decision'->>'request_digest' AS request_digest
                        FROM bio_imports i JOIN tasks t ON t.id=i.task_id AND t.user_id=%s
                        JOIN LATERAL (SELECT state_json FROM task_checkpoints WHERE task_id=t.id ORDER BY seq DESC LIMIT 1) c ON true
                        WHERE i.project_id=%s AND c.state_json->'decision'->>'request_key'=%s LIMIT 2""",(self.store.user_id,project,key)).fetchall()
                if not rows:raise error('bio_request_not_found',404)
                if len(rows)!=1:raise error('task_idempotency_conflict')
                row=rows[0]
                return dict(kind=kind,id=row['id'],root_id=row['dataset_id'],request_digest=row['request_digest'],task_id=row['task_id'])
            if kind=='confirmation':
                rows=db.execute("""SELECT t.id,t.input_snapshot,c.state_json FROM tasks t
                    JOIN LATERAL (SELECT state_json FROM task_checkpoints WHERE task_id=t.id ORDER BY seq DESC LIMIT 1) c ON true
                    WHERE t.project_id=%s AND t.user_id=%s AND t.task_type='bio_analysis'
                    AND c.state_json->'decision'->>'request_key'=%s LIMIT 2""",(project,self.store.user_id,key)).fetchall()
                if not rows:raise error('bio_request_not_found',404)
                if len(rows)!=1:raise error('task_idempotency_conflict')
                row=rows[0];decision=row['state_json']['decision'];return dict(kind=kind,id=row['input_snapshot']['run_id'],root_id=None,request_digest=decision['request_digest'],task_id=row['id'])
            if kind not in mapping:raise error('bio_request_not_found',404)
            table,root=mapping[kind]
            row=db.execute(f'SELECT * FROM {table} WHERE project_id=%s AND created_by=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if not row:raise error('bio_request_not_found',404)
            return dict(kind=kind,id=row['id'],root_id=row[root] if root else None,request_digest=row['request_digest'],task_id=row.get('task_id'))
