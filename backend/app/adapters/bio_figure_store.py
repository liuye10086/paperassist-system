"""Independent immutable figures; default plots retain their analysis task owner."""
import json
from uuid import UUID,uuid5
from app.adapters.bio_analysis_store import BioAnalysisStore,identity,base_row,insert,lock,now,error,scoped_object,object_by_key
from app.adapters.bio_objects import BioFigureObjects
from app.domain.bioinformatics.analysis_contracts import input_version,BioFigureConfig
from app.domain.bioinformatics.analysis_settings import runtime_identity,BioAnalysisLimits
from app.domain.bioinformatics.contracts import digest,conflict
from app.domain.bioinformatics.service import require_key,append_checkpoint


class BioFigureStore(BioAnalysisStore):
    def __init__(self,assets):super().__init__(assets);self.figure_objects=BioFigureObjects(assets.directory)
    def reader(self,record):return self.figure_objects if record['object_key'].startswith('bio-figures/') else self.objects

    def get(self,project,identifier):
        with self.store.connection() as db:
            row=self.require(db,'bio_figure_versions',project,identifier);task=self.store.require_task(db,row['task_id'])
            processed,manifest,_=self.processed_record(db,project,row['processed_dataset_version_id'])
            members=[]
            for m in db.execute('SELECT * FROM bio_figure_members WHERE figure_version_id=%s AND project_id=%s ORDER BY key',(identifier,project)):
                record=scoped_object(db,project,self.store.user_id,m['storage_object_id'])
                if record['sha256']!=m['sha256'] or record['size_bytes']!=m['size_bytes']:raise conflict('bio_input_integrity_changed')
                members.append({**{k:m[k] for k in ('id','key','format','size_bytes','sha256')},
                    'download_url':f'/api/v1/projects/{project}/bio-figures/{identifier}/members/{m["id"]}/download'})
            if row['manifest_object_id']:
                obj=scoped_object(db,project,self.store.user_id,row['manifest_object_id'])
                if obj['sha256']!=row['manifest_sha256']:raise conflict('bio_input_integrity_changed')
                self.reader(obj).read(obj)
            return dict(id=row['id'],root_id=row['root_id'],version=row['version'],task=self.store.public_task(task),task_id=task['id'],
                processed_source=self.processed_source(processed,manifest),annotation_version_id=row['annotation_version_id'],config=row['config_json'],
                manifest_sha256=row['manifest_sha256'],members=members)

    def member(self,project,identifier,member_id):
        with self.store.connection() as db:
            figure=self.require(db,'bio_figure_versions',project,identifier)
            self.processed_record(db,project,figure['processed_dataset_version_id'])
            row=db.execute('SELECT * FROM bio_figure_members WHERE id=%s AND figure_version_id=%s AND project_id=%s',(member_id,identifier,project)).fetchone()
            if not row:raise error('bio_member_not_found',404)
            record=scoped_object(db,project,self.store.user_id,row['storage_object_id'])
            if record['sha256']!=row['sha256'] or record['size_bytes']!=row['size_bytes']:raise conflict('bio_input_integrity_changed')
            return {**dict(row),'filename':row['key']+'.'+row['format']},self.reader(record).read(record)

    def create(self,project,request,key,root_id=None):
        require_key(key);sha=digest(request.model_dump());identifier=identity(project,'figure',key)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);lock(db,project,'figure:'+str(root_id or key))
            replay=db.execute('SELECT * FROM bio_figure_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha or (root_id and replay['root_id']!=root_id):raise error('task_idempotency_conflict')
                selected=replay['id']
            else:
                row,manifest,members=self.processed_record(db,project,request.processed_source.processed_dataset_version_id)
                if self.processed_source(row,manifest)!=request.processed_source.model_dump():raise conflict('bio_input_integrity_changed')
                if request.annotation_version_id:
                    annotation=self.require(db,'bio_annotation_versions',project,request.annotation_version_id)
                    if annotation['processed_dataset_version_id']!=row['id']:raise error('bio_annotation_invalid',422)
                if request.config.gene_ids:
                    import csv,io
                    feature=next(m for m in members if m['key']=='features')
                    ids={r['feature_id'] for r in csv.DictReader(io.StringIO(self.objects.read(feature).decode()),delimiter='\t') if r['kept'] in ('true','True')}
                    if not set(request.config.gene_ids)<=ids:raise error('bio_recipe_invalid',422)
                parent=None;version=1
                if root_id:
                    parent=db.execute('SELECT * FROM bio_figure_versions WHERE root_id=%s AND project_id=%s ORDER BY version DESC LIMIT 1',(root_id,project)).fetchone()
                    if not parent:raise error('bio_figure_not_found',404)
                    if parent['version']!=request.expected_version or parent['processed_dataset_version_id']!=row['id']:raise conflict('bio_revision_conflict')
                    version=parent['version']+1
                elif request.expected_version!=0:raise conflict('bio_revision_conflict')
                environment=runtime_identity()
                if not environment['available']:raise error('bio_environment_unavailable')
                root_id=root_id or identifier;task_id=identity(project,'figure-task',key);moment=now()
                snapshot=dict(schema_version=1,kind='bio_figure',workflow_version='bio_figure_v1',project_id=project,figure_version_id=identifier,
                    processed_source=request.processed_source.model_dump(),annotation_version_id=request.annotation_version_id,config=request.config.model_dump(),
                    engine_version=environment['engine_version'],environment_digest=environment['environment_digest'],code_digest=environment['code_digest'],
                    output_language=request.config.output_language,limits=BioAnalysisLimits().model_dump())
                task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='bio_figure',idempotency_key='bio_figure:'+task_id,input_digest=digest(snapshot),
                    input_snapshot=snapshot,workflow_version='bio_figure_v1',status='queued',phase='compute',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,task,validated_file_ids=request.processed_source.raw_source.source_file_ids)
                insert(db,'bio_figure_versions',{**base_row(identifier,project,self.store.user_id),'root_id':root_id,'version':version,'parent_id':parent['id'] if parent else None,
                    'processed_dataset_version_id':row['id'],'annotation_version_id':request.annotation_version_id,'task_id':task_id,'config_json':request.config.model_dump(),
                    'config_sha256':digest(request.config.model_dump()),'renderer_version':'bio_plots_v1','manifest_object_id':None,'manifest_sha256':None,'request_key':key,'request_digest':sha})
                append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='figure',candidate=None,decision_id=None,result_id=None))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);selected=identifier
        return self.get(project,selected)

    def publish(self,db,task,checkpoint,moment,prepared,*,progress=None):
        from app.domain.bioinformatics.analysis_service import finish
        identifier=task['input_snapshot']['figure_version_id'];row=self.require(db,'bio_figure_versions',task['project_id'],identifier)
        stored=object_by_key(db,task['project_id'],task['user_id'],prepared['manifest_ref'])
        db.execute('UPDATE bio_figure_versions SET manifest_object_id=%s,manifest_sha256=%s WHERE id=%s AND manifest_object_id IS NULL',(stored['id'],stored['sha256'],identifier))
        for member in prepared['members']:
            if progress is not None:progress()
            record=object_by_key(db,task['project_id'],task['user_id'],member)
            insert(db,'bio_figure_members',{**base_row(member['id'],task['project_id'],task['user_id']),'figure_version_id':identifier,
                **{k:member[k] for k in ('key','format','size_bytes','sha256')},'storage_object_id':record['id']})
        if progress is not None:progress()
        return finish(db,task,checkpoint,moment,'result_bio_figure_version_id',identifier)

    def publish_defaults(self,db,task,processed_id,prepared,*,progress=None):
        members={m['key']:m for m in prepared['members']}
        for key,png in members.items():
            if progress is not None:progress()
            if png['format']!='png' or not key.endswith('_png'):continue
            prefix=key[:-4];manifest=members.get(prefix+'_manifest')
            if not manifest or prefix+'_pdf' not in members or prefix+'_data' not in members:raise error('bio_output_invalid')
            identifier=str(uuid5(UUID(processed_id),'figure:'+prefix));record=object_by_key(db,task['project_id'],task['user_id'],manifest)
            rendered=json.loads(self.objects.read(manifest));raw_config=rendered.get('config',{})
            kind='qc' if prefix.startswith('qc') else 'spatial_gene' if prefix.startswith('spatial_gene') else 'spatial_cluster' if prefix.startswith('spatial') else 'marker_dotplot' if 'dotplot' in prefix else 'marker_heatmap' if 'heatmap' in prefix else 'pca' if prefix.startswith('pca') else 'umap'
            dpi=rendered.get('dpi',raw_config.get('dpi',300))
            config={k:v for k,v in raw_config.items() if k in BioFigureConfig.model_fields}
            panel={'pca':'scores','pca_variance':'variance','umap':'scores','qc_distribution':'distribution','qc_scatter':'scatter',
                'qc_violin':'violin','qc_mitochondrial':'mitochondrial','qc_by_sample_id':'sample_id','qc_by_section':'section','qc_by_batch':'batch'}.get(prefix,'default')
            if raw_config.get('kind',kind)!=kind or raw_config.get('panel',panel)!=panel:raise error('bio_output_invalid')
            config.update(kind=kind,title=raw_config.get('title',prefix),
                panel=panel,
                palette='tab20' if kind=='spatial_cluster' else raw_config.get('cmap',raw_config.get('palette','viridis')),
                dpi=dpi,width=round(rendered.get('width_inches',raw_config.get('width_inches',6))*dpi),
                height=round(rendered.get('height_inches',raw_config.get('height_inches',5))*dpi))
            try:config=BioFigureConfig.model_validate(config).model_dump()
            except ValueError as exc:raise error('bio_output_invalid') from exc
            insert(db,'bio_figure_versions',{**base_row(identifier,task['project_id'],task['user_id']),'root_id':identifier,'version':1,'parent_id':None,
                'processed_dataset_version_id':processed_id,'annotation_version_id':None,'task_id':task['id'],'config_json':config,'config_sha256':digest(config),
                'renderer_version':'bio_plots_v1','manifest_object_id':record['id'],'manifest_sha256':record['sha256'],
                'request_key':'default:'+identifier,'request_digest':digest(dict(processed_id=processed_id,key=prefix))})
            for suffix in ('png','pdf','data','manifest'):
                if progress is not None:progress()
                member=members[prefix+'_'+suffix];stored=object_by_key(db,task['project_id'],task['user_id'],member)
                insert(db,'bio_figure_members',{**base_row(str(uuid5(UUID(identifier),suffix)),task['project_id'],task['user_id']),'figure_version_id':identifier,
                    **{k:member[k] for k in ('key','format','size_bytes','sha256')},'storage_object_id':stored['id']})
