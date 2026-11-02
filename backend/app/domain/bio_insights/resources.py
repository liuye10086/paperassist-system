"""Versioned project resources on the shared task/outbox and storage ledger."""
import json

from app.adapters.bio_insights_store import base,insert,identity,invalid,now
from app.adapters.bio_analysis_store import scoped_object,object_by_key
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import require_key
from .contracts import ResourceImportRequest
from .task_contracts import InsightTaskSnapshot,input_version
from .service import BioInsightsService,portable,source_digest
from .results import checked_members,BioInsightResultService


def resource_filename_matches(filename,format):
    # .cif is the standard filename alias of the explicit mmCIF contract.
    suffixes=('.'+format,)
    if format in ('mmcif','mmcif.gz'):suffixes+=('.'+format.replace('mmcif','cif'),)
    return filename.lower().endswith(suffixes)


class BioResourceService(BioInsightsService):
    def initial_resource_members(self,db,task):
        rows=db.execute('SELECT * FROM bio_resource_members WHERE resource_version_id=%s AND project_id=%s AND user_id=%s ORDER BY key',
            (task['input_snapshot']['resource_version_id'],task['project_id'],task['user_id'])).fetchall()
        initial=next((r for r in rows if r['role']=='input_snapshot'),None)
        if not initial:raise invalid()
        return [{key:row[key] for key in ('id','key','role','format','sha256','size_bytes')}|{'shape':row['shape_json']} for row in rows]
    def _files(self,db,project,request,progress=None):
        sources=[];total_bytes=expanded_budget=0
        for file in request.files:
            row,metadata,members=self.reader().original(db,project,file.file_id,file.parse_version_id,progress)
            if row['sha256']!=file.sha256:raise invalid()
            fmt=file.format.removesuffix('.gz')
            if not resource_filename_matches(row['filename'],file.format):raise invalid('bio_insight_resource_format_mismatch',422)
            if fmt in ('csv','tsv','xlsx') and file.parse_version_id is None:
                raise invalid('bio_insight_parse_required',422)
            total_bytes+=row['size_bytes']
            expanded_budget+=file.max_uncompressed_bytes if file.format.endswith('.gz') or file.format=='xlsx' else row['size_bytes']
            if total_bytes>536870912 or expanded_budget>2147483648:
                raise invalid('bio_insight_limit_exceeded',422)
            metadata.update(resource_file=file.model_dump(mode='json'),source_file_ids=[row['id']])
            members['original_file'].update(format=file.format,role=file.role)
            sources.append(dict(source_kind='original_file',source_id=file.file_id,role=file.role,project_id=project,sha256=file.sha256,
                locator=dict(kind='object',member_key=None,table=None,row_key=None,field=None,parse_version_id=file.parse_version_id),
                metadata=metadata,members=members))
        return sources

    def preview_resource(self,project,request):
        request=ResourceImportRequest.model_validate(request)
        with self.store.connection() as db:sources=self._files(db,project,request)
        return dict(executable=True,blocking_reasons=[],source_digest=source_digest(sources),files=[dict(file_id=s['source_id'],sha256=s['sha256'],
            filename=s['metadata']['filename'],role=s['role']) for s in sources],usage=request.usage.model_dump(mode='json'),
            species_taxon_id=request.species_taxon_id,namespace=request.namespace,release=request.release,
            warnings=['此预览只核对文件身份与配置；完整资源内容由隔离worker扫描和发布。'],real_model_calls=False,real_network_calls=False)

    def create(self,project,request,key,root_id=None):
        request=ResourceImportRequest.model_validate(request);require_key(key)
        sha=digest(dict(root_id=root_id,request=request.model_dump(mode='json')));identifier=identity(project,'resource',key)
        with self.store.connection(write=True) as db:
            self.lock(db,project,'resource:'+str(root_id or key))
            replay=db.execute('SELECT * FROM bio_resource_versions WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise invalid('bio_insight_idempotency_conflict')
                selected=replay['id'];status=200
            else:
                sources=self._files(db,project,request);runtime=self._runtime_for(request);parent=None;version=1
                if root_id:
                    parent=db.execute('SELECT * FROM bio_resource_versions WHERE root_id=%s AND project_id=%s AND user_id=%s ORDER BY version DESC LIMIT 1',
                        (root_id,project,self.store.user_id)).fetchone()
                    if not parent:raise invalid('bio_insight_not_found',404)
                    if parent['version']!=request.expected_revision or parent['kind']!=request.kind:raise invalid('bio_insight_revision_conflict')
                    version=parent['version']+1
                elif request.expected_revision!=0:raise invalid('bio_insight_revision_conflict')
                task_id=identity(project,'resource-task',key);source_sha=source_digest(sources)
                payload=dict(schema_version=1,kind='bio_resource_import',config=request.model_dump(mode='json'),
                    identity=dict(project_id=project,task_id=task_id,resource_version_id=identifier,source_digest=source_sha,
                        config_sha256=digest(request.model_dump(mode='json')),**runtime),sources=sources)
                snapshot_obj=self.write_document(db,project,identifier,'execution_snapshot',portable(payload))
                snapshot=InsightTaskSnapshot(kind='bio_resource_import',workflow_version='bio_resource_import_v1',project_id=project,
                    resource_version_id=identifier,source_digest=source_sha,output_language=request.output_language).model_dump(mode='json',exclude_none=True)
                self._new_task(db,project,task_id,'bio_resource_import',snapshot,[s['source_id'] for s in sources])
                insert(db,'bio_resource_versions',{**base(identifier,project,self.store.user_id),'root_id':root_id or identifier,'version':version,
                    'parent_id':parent['id'] if parent else None,'kind':request.kind,'title':request.title,'species_taxon_id':request.species_taxon_id,
                    'namespace':request.namespace,'release':request.release,'source_json':request.source.model_dump(mode='json'),
                    'usage_json':request.usage.model_dump(mode='json'),'config_json':request.model_dump(mode='json'),'config_sha256':digest(request.model_dump(mode='json')),
                    'task_id':task_id,'task_type':'bio_resource_import','manifest_object_id':None,'manifest_sha256':None,'request_key':key,'request_digest':sha})
                insert(db,'bio_resource_members',{**base(identity(project,'resource-input',identifier),project,self.store.user_id),'resource_version_id':identifier,
                    'key':'execution_snapshot','role':'input_snapshot','format':'json','storage_object_id':snapshot_obj['id'],'size_bytes':snapshot_obj['size_bytes'],
                    'sha256':snapshot_obj['sha256'],'shape_json':{},'original_file_id':None,'parse_version_id':None})
                # File FKs are retained before publication; normalized output may
                # use distinct keys, while these original members remain formal.
                for index,file in enumerate(request.files):
                    row=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(file.file_id,project)).fetchone()
                    obj=db.execute("SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id WHERE o.object_key=%s AND o.namespace='local:assets-v1' AND o.state='present' AND r.project_id=%s AND r.owner_id=%s",
                        (row['object_key'],project,self.store.user_id)).fetchone()
                    if not obj or obj['sha256']!=file.sha256:raise invalid()
                    insert(db,'bio_resource_members',{**base(identity(project,'resource-original',identifier+':'+str(index)),project,self.store.user_id),
                        'resource_version_id':identifier,'key':'original_'+str(index),'role':'original_resource','format':file.format,
                        'storage_object_id':obj['id'],'size_bytes':obj['size_bytes'],'sha256':obj['sha256'],'shape_json':{'input_role':file.role},
                        'original_file_id':file.file_id,'parse_version_id':file.parse_version_id})
                selected=identifier;status=202
        return self.get(project,selected),status

    def _require_resource_sources(self,db,task,*,runtime=True,progress=None):
        input_version(task);snapshot=task['input_snapshot'];project=task['project_id']
        row=self.require(db,'bio_resource_versions',project,snapshot['resource_version_id'])
        if row['task_id']!=task['id'] or digest(row['config_json'])!=row['config_sha256']:raise invalid()
        request=ResourceImportRequest.model_validate(row['config_json']);sources=self._files(db,project,request,progress)
        if source_digest(sources)!=snapshot['source_digest']:raise invalid()
        member=db.execute("SELECT * FROM bio_resource_members WHERE resource_version_id=%s AND project_id=%s AND role='input_snapshot'",(row['id'],project)).fetchone()
        if not member:raise invalid()
        obj=scoped_object(db,project,self.store.user_id,member['storage_object_id'])
        if obj['sha256']!=member['sha256']:raise invalid()
        frozen=json.loads(self.objects.read(obj))
        payload=dict(schema_version=1,kind='bio_resource_import',config=request.model_dump(mode='json'),identity=frozen['identity'],sources=sources)
        if portable(payload)!=frozen or frozen['identity'].get('task_id')!=task['id']:raise invalid()
        if runtime:
            current=self._runtime_for(request)
            if any(payload['identity'].get(key)!=value for key,value in current.items()):raise invalid('bio_insights_environment_unavailable',422)
        return payload

    def get(self,project,identifier):
        with self.store.connection() as db:
            row=self.require(db,'bio_resource_versions',project,identifier);task=self.store.require_task(db,row['task_id'])
            members=[];manifest=None
            if row['manifest_object_id']:
                self._require_resource_sources(db,task,runtime=False)
                manifest,records=checked_members(self,db,project,row,resource=True)
                members=[BioInsightResultService.public_member(project,identifier,m,resource=True) for m in records if m['role']!='input_snapshot']
            return dict(id=row['id'],root_id=row['root_id'],version=row['version'],revision=row['version'],parent_id=row['parent_id'],kind=row['kind'],
                title=row['title'],species_taxon_id=row['species_taxon_id'],namespace=row['namespace'],release=row['release'],source=row['source_json'],usage=row['usage_json'],
                config=row['config_json'],task_id=task['id'],task=self.store.public_task(task),manifest_sha256=row['manifest_sha256'],manifest=manifest,members=members)

    def list(self,project,page=1,page_size=20):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            total=db.execute('SELECT count(*) AS n FROM bio_resource_versions WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()['n']
            rows=db.execute('SELECT id FROM bio_resource_versions WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s',
                (project,self.store.user_id,page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.get(project,r['id']) for r in rows],total=total,page=page,page_size=page_size)

    def member(self,project,identifier,member_id):return BioInsightResultService(self.assets).member(project,identifier,member_id,resource=True)

    def _publish_resource(self,db,task,checkpoint,moment,prepared,*,progress):
        from app.domain.bioinformatics.analysis_service import finish
        self._require_resource_sources(db,task,progress=progress)
        identifier=task['input_snapshot']['resource_version_id'];row=self.require(db,'bio_resource_versions',task['project_id'],identifier)
        if row['manifest_object_id']:raise invalid()
        manifest=object_by_key(db,task['project_id'],task['user_id'],prepared['manifest_ref'])
        for member in prepared['members']:
            progress();obj=object_by_key(db,task['project_id'],task['user_id'],member)
            insert(db,'bio_resource_members',{**base(member['id'],task['project_id'],task['user_id']),'resource_version_id':identifier,
                **{key:member[key] for key in ('key','role','format','sha256','size_bytes')},'storage_object_id':obj['id'],'shape_json':member.get('shape',{}),
                'original_file_id':None,'parse_version_id':None})
        db.execute('UPDATE bio_resource_versions SET manifest_object_id=%s,manifest_sha256=%s WHERE id=%s AND manifest_object_id IS NULL',
            (manifest['id'],manifest['sha256'],identifier))
        progress();return finish(db,task,checkpoint,moment,'result_bio_resource_version_id',identifier)
