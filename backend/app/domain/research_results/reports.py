"""Fixed report intents and atomic multi-format publication."""
from app.adapters.research_results_store import ResearchResultsStore,base,insert,identity,now,invalid
from app.adapters.research_objects import ResearchObjects
from app.adapters.bio_analysis_store import scoped_object,object_by_key
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import require_key,append_checkpoint
from .contracts import ResearchReportRequest
from .sources import ResearchSourceReader
from .findings import ResearchFindingService
from .figures import ResearchFigureService
from .report_tables import _collect_tables_in_phase
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard
from .task_contracts import input_version
from app.adapters.research_method_text import METHOD_PRESENTATION_VERSION


class ResearchReportService(ResearchResultsStore):
    def freeze(self,db,project,request,*,progress=None):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._freeze_in_phase(db,project,request,phase=phase,progress=progress)

    @phase_guard
    def _freeze_in_phase(self,db,project,request,*,phase,progress=None):
        require_phase(phase,db,self.assets,project)
        if progress is not None:progress()
        reader=ResearchSourceReader(self.assets)
        found=self.require(db,'research_finding_versions',project,request.finding_version_id)
        # One complete validation of this binding already checks the finding's
        # exact source closure. Pin the row read above, then only format its view.
        binding=reader._read_source_in_phase(project,dict(source_kind='research_finding_version',source_id=found['id'],sha256=found['content_sha256']),db=db,phase=phase,progress=progress)
        verified=self.verify_content(found)
        if binding.content!=verified:raise invalid()
        finding=ResearchFindingService.format_view(found,verified)
        if len(finding['content']['claims'])>100:raise invalid('research_export_limit_exceeded',422)
        figures=[];images=[];files=[];bindings=[binding]
        for index,identifier in enumerate(request.figure_version_ids,1):
            svc=ResearchFigureService(self.assets);view=svc._get_in_phase(db,project,identifier,phase=phase,progress=progress)
            if view['task']['status']!='succeeded':raise invalid('research_source_incomplete',422)
            source=reader._read_source_in_phase(project,dict(source_kind='research_figure_version',source_id=identifier),db=db,phase=phase,progress=progress);bindings.append(source)
            fixed=dict(id=identifier,config=view['config'],manifest_sha256=view['manifest_sha256'])
            figures.append(fixed);selected=None;selected_member=None
            for member in view['members']:
                if progress is not None:progress()
                # get() has just checked the complete fixed source closure and
                # member manifest. Re-read each exact member's own bytes once;
                # do not rescan the upstream raw matrices for every format.
                saved=self.require(db,'research_figure_members',project,member['id'])
                if saved['figure_version_id']!=identifier:raise invalid()
                obj=scoped_object(db,project,self.store.user_id,saved['storage_object_id'])
                if any(obj[k]!=member[k] or saved[k]!=member[k] for k in ('sha256','size_bytes')):raise invalid()
                raw=ResearchObjects(self.assets.directory).read(obj)
                if progress is not None:progress()
                files.append(dict(name=f'figures/figure_{index:02d}/'+member['key']+'.'+member['format'],raw=raw))
                priority={'png':0,'tiff':1,'svg':2,'pdf':3}
                if member['role']=='figure' and member['format'] in priority and (selected_member is None or priority[member['format']]<priority[selected_member['format']]):
                    selected=raw;selected_member=member
            if selected is None:raise invalid('research_source_unsupported',422)
            fixed['document_image']={k:selected_member[k] for k in ('key','format','sha256')}
            images.append(dict(config=view['config'],raw=selected,format=selected_member['format']))
        tables,table_raws=_collect_tables_in_phase(reader,db,project,finding['content']['sources'],phase=phase,progress=progress)
        pdf=None
        if request.include_pdf_id:
            if progress is not None:progress()
            if not request.root_id:raise invalid('research_source_conflict',422)
            from app.domain.pdf_exports.service import PdfExportService
            service=PdfExportService(self.assets);row=service.row(db,project,request.include_pdf_id)
            member=db.execute('SELECT m.*,v.root_id,v.finding_version_id,v.content_json FROM research_report_members m JOIN research_report_versions v ON v.id=m.report_version_id WHERE m.id=%s AND m.project_id=%s',(row['source_id'],project)).fetchone()
            if (row['source_kind']!='research_report' or not member or member['root_id']!=request.root_id or member['finding_version_id']!=request.finding_version_id
                or [f['id'] for f in member['content_json']['figures']]!=request.figure_version_ids or member['content_json']['title']!=request.title
                or member['content_json']['language']!=request.language):raise invalid()
            metadata,raw=service.download(project,request.include_pdf_id,progress=progress)
            pdf=dict(id=row['id'],source_id=row['source_id'],sha256=metadata['sha256'],source_report_version_id=member['report_version_id'])
            files.append(dict(name='analysis.pdf',raw=raw))
        content=dict(schema_version=1,method_presentation_version=METHOD_PRESENTATION_VERSION,title=request.title,language=request.language,finding=finding,figures=figures,tables=tables,
            included_pdf=pdf,real_model_calls=0)
        if progress is not None:progress()
        return content,bindings,dict(snapshot=content,tables=tables,table_raws=table_raws,figures=images,package_files=files)

    def create(self,project,request,key,root_id=None):
        require_key(key);request=ResearchReportRequest.model_validate(request);body=request.model_dump(mode='json');sha=digest(body)
        if root_id and root_id!=request.root_id:raise invalid('research_revision_conflict')
        with self.store.connection(write=True) as db:
            self.lock(db,project,'report:'+str(request.root_id or key))
            replay=db.execute('SELECT * FROM research_report_versions WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise invalid('research_idempotency_conflict')
                identifier=replay['id'];status=200
            else:
                parent=None;revision=1
                if request.root_id:
                    parent=db.execute('SELECT * FROM research_report_versions WHERE root_id=%s AND project_id=%s AND user_id=%s ORDER BY revision DESC LIMIT 1',(request.root_id,project,self.store.user_id)).fetchone()
                    if not parent:raise invalid('research_source_not_found',404)
                    if parent['revision']!=request.expected_revision:raise invalid('research_revision_conflict')
                    revision=parent['revision']+1
                content,bindings,_=self.freeze(db,project,request);identifier=identity(project,'report',key);task_id=identity(project,'report-task',key);moment=now()
                # JSON-compatible creation time and frozen source fields, without
                # internal paths or table byte payloads.
                import json
                content=json.loads(json.dumps(content,default=lambda v:v.isoformat()))
                from app.adapters.research_report_render import renderer_identity
                snapshot=dict(schema_version=1,kind='research_report',workflow_version='research_report_v1',project_id=project,report_version_id=identifier,renderer_identity=renderer_identity(),
                    request=body,content_sha256=digest(content),source_file_ids=sorted({f for s in bindings for f in s.source_file_ids}),
                    output_language=request.language,real_model_calls=False,real_network_calls=False)
                task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='research_report',idempotency_key='research_report:'+task_id,
                    input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version='research_report_v1',status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,task,validated_file_ids=snapshot['source_file_ids'])
                insert(db,'research_report_versions',{**base(identifier,project,self.store.user_id),'root_id':request.root_id or identifier,'revision':revision,
                    'parent_id':parent['id'] if parent else None,'finding_version_id':request.finding_version_id,'task_id':task_id,'language':request.language,
                    'content_json':content,'content_sha256':digest(content),'manifest_object_id':None,'manifest_sha256':None,'request_key':key,'request_digest':sha})
                for source in bindings:self.bind(db,project,'report',identifier,source)
                append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='report'))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);status=201
        return self.get(project,identifier),status

    def require_sources(self,db,task,*,progress=None):
        with VerificationPhase(db,self.assets,task['project_id']) as phase:
            return self._require_sources_in_phase(db,task,phase=phase,progress=progress)

    @phase_guard
    def _require_sources_in_phase(self,db,task,*,phase,progress=None):
        require_phase(phase,db,self.assets,task['project_id'])
        import json
        input_version(task);snapshot=task['input_snapshot'];row=self.require(db,'research_report_versions',task['project_id'],snapshot['report_version_id'])
        from app.adapters.research_report_render import renderer_identity
        if snapshot.get('renderer_identity')!=renderer_identity():raise invalid()
        if row['task_id']!=task['id'] or digest(row['content_json'])!=row['content_sha256'] or row['content_sha256']!=snapshot['content_sha256']:raise invalid()
        content,_,payload=self._freeze_in_phase(db,task['project_id'],ResearchReportRequest.model_validate(snapshot['request']),phase=phase,progress=progress)
        normalized=json.loads(json.dumps(content,default=lambda v:v.isoformat()))
        if normalized!=row['content_json']:raise invalid()
        payload['snapshot']=normalized;return payload

    def checked_members(self,db,project,row,*,progress=None):
        import json
        objects=ResearchObjects(self.assets.directory);obj=scoped_object(db,project,self.store.user_id,row['manifest_object_id'])
        if obj['sha256']!=row['manifest_sha256']:raise invalid()
        manifest=json.loads(objects.read(obj));expected={m['id']:m for m in manifest['members']};members=[]
        for member in db.execute('SELECT * FROM research_report_members WHERE report_version_id=%s AND project_id=%s AND user_id=%s ORDER BY key',(row['id'],project,self.store.user_id)):
            if progress is not None:progress()
            obj=scoped_object(db,project,self.store.user_id,member['storage_object_id']);match=expected.get(member['id'])
            if not match or any(member[k]!=match[k] for k in ('key','role','format','sha256','size_bytes')) or any(obj[k]!=member[k] for k in ('sha256','size_bytes')):raise invalid()
            objects.read(obj);members.append({k:member[k] for k in ('id','key','role','format','sha256','size_bytes','properties_json')})
            if progress is not None:progress()
        if {m['id'] for m in members}!=set(expected):raise invalid()
        return manifest,members

    def get(self,project,identifier):
        with self.store.connection() as db:
            row=self.require(db,'research_report_versions',project,identifier);self.verify_content(row);task=self.store.require_task(db,row['task_id'])
            manifest=None;members=[]
            if row['manifest_object_id']:
                if task['status']!='succeeded':raise invalid()
                ResearchSourceReader(self.assets).read_source(project,dict(source_kind='research_report_version',source_id=identifier),db=db)
                manifest,members=self.checked_members(db,project,row)
                for member in members:member['download_url']=f'/api/v1/projects/{project}/research-reports/{identifier}/members/{member["id"]}/download'
            return dict(id=identifier,root_id=row['root_id'],revision=row['revision'],parent_id=row['parent_id'],content=row['content_json'],sha256=row['content_sha256'],
                manifest=manifest,manifest_sha256=row['manifest_sha256'],members=members,task_id=row['task_id'],task=self.store.public_task(task))

    def list(self,project,page=1):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            ids=db.execute('SELECT id FROM research_report_versions WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT 20 OFFSET %s',(project,self.store.user_id,(page-1)*20)).fetchall()
            total=db.execute('SELECT count(*) AS n FROM research_report_versions WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()['n']
        return dict(items=[self.get(project,r['id']) for r in ids],total=total,page=page,page_size=20)

    def member(self,project,identifier,member_id,*,progress=None):
        with self.store.connection() as db:
            with VerificationPhase(db,self.assets,project) as phase:
                return self._member_in_phase(db,project,identifier,member_id,phase=phase,progress=progress)

    @phase_guard
    def _member_in_phase(self,db,project,identifier,member_id,*,phase,progress=None):
        require_phase(phase,db,self.assets,project)
        row=self.require(db,'research_report_versions',project,identifier)
        if not row['manifest_object_id'] or self.store.require_task(db,row['task_id'])['status']!='succeeded':raise invalid('research_source_incomplete',422)
        ResearchSourceReader(self.assets)._read_source_in_phase(project,dict(source_kind='research_report_version',source_id=identifier),db=db,phase=phase,progress=progress)
        _,members=self.checked_members(db,project,row,progress=progress)
        member=next((m for m in members if m['id']==member_id),None)
        if not member:raise invalid('research_source_not_found',404)
        original=self.require(db,'research_report_members',project,member_id)
        obj=scoped_object(db,project,self.store.user_id,original['storage_object_id'])
        return dict(member,filename=member['key']+'.'+member['format']),ResearchObjects(self.assets.directory).read(obj)


    def publish(self,db,task,checkpoint,moment,prepared,*,progress):
        from app.domain.bioinformatics.analysis_service import finish
        identifier=task['input_snapshot']['report_version_id'];row=self.require(db,'research_report_versions',task['project_id'],identifier)
        if row['manifest_object_id']:raise invalid()
        manifest=object_by_key(db,task['project_id'],task['user_id'],prepared['manifest_ref'])
        for member in prepared['members']:
            progress();obj=object_by_key(db,task['project_id'],task['user_id'],member)
            insert(db,'research_report_members',{**base(member['id'],task['project_id'],task['user_id']),'report_version_id':identifier,
                **{k:member[k] for k in ('key','role','format','sha256','size_bytes')},'storage_object_id':obj['id'],'properties_json':member.get('properties',{})})
        db.execute('UPDATE research_report_versions SET manifest_object_id=%s,manifest_sha256=%s WHERE id=%s AND manifest_object_id IS NULL',(manifest['id'],manifest['sha256'],identifier))
        progress();return finish(db,task,checkpoint,moment,'result_research_report_version_id',identifier)
