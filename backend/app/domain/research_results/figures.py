"""Immutable research figure requests with CAS and no synchronous publication."""
from app.adapters.research_results_store import ResearchResultsStore,base,insert,identity,now,invalid
from app.adapters.research_objects import ResearchObjects
from app.adapters.bio_analysis_store import scoped_object,object_by_key
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import require_key,append_checkpoint
from .contracts import ResearchFigureRequest
from .figure_members import read_figure_panel,research_figure_source
from .task_contracts import input_version
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard


class ResearchFigureService(ResearchResultsStore):
    table='research_figure_versions'
    def reader(self):
        from .sources import ResearchSourceReader
        return ResearchSourceReader(self.assets)

    def frozen(self,db,project,request,*,progress=None):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._frozen_in_phase(db,project,request,phase=phase,progress=progress)

    @phase_guard
    def _frozen_in_phase(self,db,project,request,*,phase,progress=None):
        require_phase(phase,db,self.assets,project)
        reader=self.reader();sources=[];panels=[];raws=[]
        for panel in request.panels:
            source,member,raw=read_figure_panel(reader,db,project,panel,phase=phase,progress=progress);sources.append(source);panels.append(member);raws.append(raw)
        columns=min(request.columns,len(panels));width=round(request.width_mm/25.4*request.dpi);margin=round(request.margin_mm/25.4*request.dpi)
        cell=(width-(columns+1)*margin)//columns
        from app.adapters.research_figure_render import label_font
        try:label_font(request.model_dump(mode='json'),panels,cell)
        except ValueError as exc:raise invalid('research_figure_limit_exceeded',422) from exc
        label_height=round(request.font_size_pt/72*request.dpi)+4 if request.mode=='composite' or any(p['label'] for p in panels) else 0
        heights=[max(1,round(cell*p['height']/p['width'])) for p in panels]
        row_heights=[max(heights[i:i+columns])+label_height for i in range(0,len(panels),columns)]
        height=sum(row_heights)+(len(row_heights)+1)*margin
        if cell<1 or max(width,height)>8000 or width*height>40_000_000:raise invalid('research_figure_limit_exceeded',422)
        caption_sources=[reader._read_source_in_phase(project,s,db=db,phase=phase,progress=progress) for s in request.caption_sources]
        facts={fact.id:fact.model_dump(mode='json') for source in [*sources,*caption_sources] for fact in reader.catalog(source).facts}
        if not set(request.caption_fact_ids)<=facts.keys():raise invalid('research_fact_unresolved',422)
        return sources,panels,raws,caption_sources,[facts[k] for k in request.caption_fact_ids]

    def create(self,project,request,key,root_id=None):
        require_key(key);material=request.model_dump(mode='json');sha=digest(material);identifier=identity(project,'figure',key)
        if root_id is not None and request.root_id!=root_id:raise invalid('research_revision_conflict')
        with self.store.connection(write=True) as db:
            self.lock(db,project,'figure:'+str(root_id or request.root_id or key))
            replay=db.execute('SELECT * FROM research_figure_versions WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise invalid('research_idempotency_conflict')
                selected=replay['id'];status=200
            else:
                sources,panels,_,caption_sources,facts=self.frozen(db,project,request)
                parent=None;revision=1
                if request.root_id:
                    parent=db.execute('SELECT * FROM research_figure_versions WHERE root_id=%s AND project_id=%s AND user_id=%s ORDER BY revision DESC LIMIT 1',(request.root_id,project,self.store.user_id)).fetchone()
                    if not parent:raise invalid('research_source_not_found',404)
                    if parent['revision']!=request.expected_revision:raise invalid('research_revision_conflict')
                    revision=parent['revision']+1
                task_id=identity(project,'figure-task',key);moment=now()
                from app.adapters.research_figure_render import renderer_identity
                snapshot=dict(schema_version=1,kind='research_figure',workflow_version='research_figure_v1',project_id=project,
                    figure_version_id=identifier,config=material,panels=panels,caption_sources=[s.model_dump(mode='json') for s in caption_sources],
                    caption_facts=facts,source_file_ids=sorted({file for s in [*sources,*caption_sources] for file in s.source_file_ids}),
                    renderer_identity=renderer_identity(),output_language=request.language,real_model_calls=False,real_network_calls=False)
                task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='research_figure',idempotency_key='research_figure:'+task_id,input_digest=digest(snapshot),
                    input_snapshot=snapshot,workflow_version='research_figure_v1',status='queued',phase='compute',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,task,validated_file_ids=sorted({file for s in [*sources,*caption_sources] for file in s.source_file_ids}))
                insert(db,self.table,{**base(identifier,project,self.store.user_id),'root_id':request.root_id or identifier,
                    'revision':revision,'parent_id':parent['id'] if parent else None,'task_id':task_id,'config_json':material,'config_sha256':sha,
                    'manifest_object_id':None,'manifest_sha256':None,'request_key':key,'request_digest':sha})
                for source in sources:self.bind(db,project,'figure',identifier,source,'panel')
                for source in caption_sources:self.bind(db,project,'figure',identifier,source,'caption')
                append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='figure'))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);selected=identifier;status=201
        return self.get(project,selected),status

    def require_sources(self,db,task,*,runtime=True,progress=None):
        with VerificationPhase(db,self.assets,task['project_id']) as phase:
            return self._require_sources_in_phase(db,task,phase=phase,runtime=runtime,progress=progress)

    @phase_guard
    def _require_sources_in_phase(self,db,task,*,phase,runtime=True,progress=None):
        require_phase(phase,db,self.assets,task['project_id'])
        input_version(task);snapshot=task['input_snapshot'];row=self.require(db,self.table,task['project_id'],snapshot['figure_version_id'])
        from app.adapters.research_figure_render import renderer_identity
        if runtime and snapshot.get('renderer_identity')!=renderer_identity():raise invalid()
        if row['task_id']!=task['id'] or row['config_json']!=snapshot['config'] or digest(row['config_json'])!=row['config_sha256']:raise invalid()
        request=ResearchFigureRequest.model_validate(snapshot['config'])
        _,panels,raws,caption_sources,facts=self._frozen_in_phase(db,task['project_id'],request,phase=phase,progress=progress)
        if panels!=snapshot['panels'] or facts!=snapshot['caption_facts'] or [s.model_dump(mode='json') for s in caption_sources]!=snapshot['caption_sources']:raise invalid()
        return dict(config=snapshot['config'],panels=panels,raws=raws,caption_facts=facts)

    def get(self,project,identifier,*,progress=None):
        with self.store.connection() as db:
            with VerificationPhase(db,self.assets,project) as phase:
                return self._get_in_phase(db,project,identifier,phase=phase,progress=progress)

    @phase_guard
    def _get_in_phase(self,db,project,identifier,*,phase,progress=None):
        require_phase(phase,db,self.assets,project)
        row=self.require(db,self.table,project,identifier);task=self.store.require_task(db,row['task_id'])
        if digest(row['config_json'])!=row['config_sha256']:raise invalid()
        members=[];manifest=None
        if row['manifest_object_id']:
            if task['status']!='succeeded':raise invalid()
            self._require_sources_in_phase(db,task,phase=phase,runtime=False,progress=progress)
            checked=research_figure_source(self,db,project,row,progress=progress);manifest=checked['manifest']
            members=[{**m,'download_url':f'/api/v1/projects/{project}/research-figures/{identifier}/members/{m["id"]}/download'} for m in checked['members']]
        return dict(id=row['id'],root_id=row['root_id'],revision=row['revision'],parent_id=row['parent_id'],config=row['config_json'],
            task=self.store.public_task(task),task_id=row['task_id'],manifest_sha256=row['manifest_sha256'],manifest=manifest,members=members)


    def list(self,project,page=1,page_size=20):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            rows=db.execute('SELECT id FROM research_figure_versions WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s',(project,self.store.user_id,page_size,(page-1)*page_size)).fetchall()
            total=db.execute('SELECT count(*) AS n FROM research_figure_versions WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()['n']
        return dict(items=[self.get(project,r['id']) for r in rows],page=page,page_size=page_size,total=total)

    def member(self,project,identifier,member_id):
        with self.store.connection() as db:
            row=self.require(db,self.table,project,identifier)
            task=self.store.require_task(db,row['task_id'])
            if not row['manifest_object_id'] or task['status']!='succeeded':raise invalid('research_source_incomplete',422)
            self.require_sources(db,task,runtime=False)
            member=db.execute('SELECT * FROM research_figure_members WHERE id=%s AND figure_version_id=%s AND project_id=%s AND user_id=%s',(member_id,identifier,project,self.store.user_id)).fetchone()
            if not member:raise invalid('research_source_not_found',404)
            obj=scoped_object(db,project,self.store.user_id,member['storage_object_id'])
            if any(obj[k]!=member[k] for k in ('sha256','size_bytes')):raise invalid()
            return dict(member),ResearchObjects(self.assets.directory).read(obj)

    def publish(self,db,task,checkpoint,moment,prepared,*,progress):
        from app.domain.bioinformatics.analysis_service import finish
        identifier=task['input_snapshot']['figure_version_id'];row=self.require(db,self.table,task['project_id'],identifier)
        if row['manifest_object_id']:raise invalid()
        manifest=object_by_key(db,task['project_id'],task['user_id'],prepared['manifest_ref'])
        for member in prepared['members']:
            progress();obj=object_by_key(db,task['project_id'],task['user_id'],member)
            insert(db,'research_figure_members',{**base(member['id'],task['project_id'],task['user_id']),'figure_version_id':identifier,
                **{k:member[k] for k in ('key','format','role','sha256','size_bytes')},'storage_object_id':obj['id'],'properties_json':member.get('properties',{})})
        db.execute('UPDATE research_figure_versions SET manifest_object_id=%s,manifest_sha256=%s WHERE id=%s AND manifest_object_id IS NULL',(manifest['id'],manifest['sha256'],identifier))
        progress();return finish(db,task,checkpoint,moment,'result_research_figure_version_id',identifier)
