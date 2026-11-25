"""Immutable research figure requests with CAS and no synchronous publication."""
from app.adapters.research_results_store import ResearchResultsStore,base,insert,identity,now,invalid
from app.adapters.research_objects import ResearchObjects
from app.adapters.bio_analysis_store import scoped_object,object_by_key
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import require_key,append_checkpoint
from .contracts import PaperFigureRequest, ResearchFigureRequest
from .figure_members import read_figure_panel,research_figure_source
from .paper_figure_assembly import assembly_cancelled, assembly_library, require_available_originals
from .task_contracts import input_version
from .frozen_projection import frozen_source_projection,matches_frozen_source
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard


SCI_FIGURE_ENTRYPOINT = 'sci_figures'
THESIS_FIGURE_ENTRYPOINT = 'thesis_figures'
_CUSTOMER_FIGURE_ENTRYPOINTS = (SCI_FIGURE_ENTRYPOINT, THESIS_FIGURE_ENTRYPOINT)


def customer_figure_entrypoint(task):
    if task['task_type'] != 'research_figure':
        return None
    entrypoint = task['input_snapshot'].get('entrypoint')
    return entrypoint if entrypoint in _CUSTOMER_FIGURE_ENTRYPOINTS else None


class ResearchFigureService(ResearchResultsStore):
    table='research_figure_versions'

    def __init__(self, assets, *, entrypoint=None):
        super().__init__(assets)
        if entrypoint is not None and entrypoint not in _CUSTOMER_FIGURE_ENTRYPOINTS:
            raise ValueError('Unknown customer figure entrypoint')
        self.entrypoint = entrypoint

    def _figure_task(self, db, row):
        task = self.store.require_task(db, row['task_id'])
        if self.entrypoint is not None and self.entrypoint != customer_figure_entrypoint(task):
            raise invalid('research_source_not_found', 404)
        return task

    def reader(self):
        from .sources import ResearchSourceReader
        return ResearchSourceReader(self.assets)

    def frozen(self,db,project,request,*,progress=None):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._frozen_in_phase(db,project,request,phase=phase,progress=progress,customer_originals=self.entrypoint is not None)

    @phase_guard
    def _frozen_in_phase(self,db,project,request,*,phase,progress=None,frozen_panels=None,allow_stale_labels=False,customer_originals=False):
        require_phase(phase,db,self.assets,project)
        reader=self.reader();reader.allow_stale_labels=allow_stale_labels;sources=[];panels=[];raws=[]
        if frozen_panels is not None and len(frozen_panels)!=len(request.panels):raise invalid()
        if customer_originals and request.caption_sources:raise invalid('research_source_unsupported',422)
        for index,panel in enumerate(request.panels):
            source,member,raw=read_figure_panel(reader,db,project,panel,phase=phase,progress=progress,figure_language=request.figure_language,
                frozen_panel=frozen_panels[index] if frozen_panels is not None else None,customer_originals=customer_originals)
            if frozen_panels is not None:
                member['source']=frozen_source_projection(member['source'],frozen_panels[index]['source'])
            sources.append(source);panels.append(member);raws.append(raw)
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

    def create(self,project,request,key,root_id=None,*,base_revision=None):
        require_key(key)
        request_model = ResearchFigureRequest
        if self.entrypoint is not None:
            workspace = self.entrypoint.removesuffix('_figures')
            key = f'{workspace}-figure:{digest(key)}'
            request_model = PaperFigureRequest
        request = request_model.model_validate(
            request.model_dump(mode='json') if isinstance(request, ResearchFigureRequest) else request)
        material=request.model_dump(mode='json');sha=digest(material);identifier=identity(project,'figure',key)
        request_sha = sha if base_revision is None else digest(dict(config=material, base_revision=base_revision))
        if root_id is not None and request.root_id!=root_id:raise invalid('research_revision_conflict')
        with self.store.connection(write=True) as db:
            self.lock(db,project,'figure:'+str(root_id or request.root_id or key))
            replay=db.execute('SELECT * FROM research_figure_versions WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=request_sha:raise invalid('research_idempotency_conflict')
                selected=replay['id'];status=200
            else:
                parent=None;revision=1
                if request.root_id:
                    parent=db.execute('SELECT * FROM research_figure_versions WHERE root_id=%s AND project_id=%s AND user_id=%s ORDER BY revision DESC LIMIT 1',(request.root_id,project,self.store.user_id)).fetchone()
                    parent_task = self.store.require_task(db, parent['task_id']) if parent else None
                    if not parent_task or self.entrypoint != customer_figure_entrypoint(parent_task):
                        raise invalid('research_source_not_found',404)
                    if parent['revision']!=request.expected_revision:raise invalid('research_revision_conflict')
                    # A retry can publish the latest attempt under the same figure revision.
                    if base_revision is not None and base_revision < parent['revision'] and parent_task['status'] == 'succeeded':
                        raise invalid('research_revision_conflict')
                    revision=parent['revision']+1
                if self.entrypoint is not None:
                    require_available_originals(db, project, self.store.user_id, self.entrypoint,
                                                [panel.source.source_id for panel in request.panels], request.root_id)
                sources,panels,_,caption_sources,facts=self.frozen(db,project,request)
                task_id=identity(project,'figure-task',key);moment=now()
                from app.adapters.research_figure_render import renderer_identity
                snapshot=dict(schema_version=1,kind='research_figure',workflow_version='research_figure_v1',project_id=project,
                    figure_version_id=identifier,config=material,panels=panels,caption_sources=[s.model_dump(mode='json') for s in caption_sources],
                    caption_facts=facts,source_file_ids=sorted({file for s in [*sources,*caption_sources] for file in s.source_file_ids}),
                    renderer_identity=renderer_identity(),output_language=request.language,real_model_calls=False,real_network_calls=False)
                if self.entrypoint is not None:
                    snapshot['entrypoint'] = self.entrypoint
                if any('statistics_png' in panel for panel in panels):
                    import json
                    if len(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')).encode())>4*1024**2:
                        raise invalid('research_source_limit_exceeded',422)
                task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='research_figure',idempotency_key='research_figure:'+task_id,input_digest=digest(snapshot),
                    input_snapshot=snapshot,workflow_version='research_figure_v1',status='queued',phase='compute',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,task,validated_file_ids=sorted({file for s in [*sources,*caption_sources] for file in s.source_file_ids}))
                insert(db,self.table,{**base(identifier,project,self.store.user_id),'root_id':request.root_id or identifier,
                    'revision':revision,'parent_id':parent['id'] if parent else None,'task_id':task_id,'config_json':material,'config_sha256':sha,
                    'manifest_object_id':None,'manifest_sha256':None,'request_key':key,'request_digest':request_sha})
                for source in sources:self.bind(db,project,'figure',identifier,source,'panel')
                for source in caption_sources:self.bind(db,project,'figure',identifier,source,'caption')
                append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='figure'))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);selected=identifier;status=201
        return self.get(project,selected),status

    def require_sources(self,db,task,*,runtime=True,progress=None,allow_stale_labels=False):
        with VerificationPhase(db,self.assets,task['project_id']) as phase:
            return self._require_sources_in_phase(db,task,phase=phase,runtime=runtime,progress=progress,allow_stale_labels=allow_stale_labels)

    @phase_guard
    def _require_sources_in_phase(self,db,task,*,phase,runtime=True,progress=None,allow_stale_labels=False):
        require_phase(phase,db,self.assets,task['project_id'])
        input_version(task);snapshot=task['input_snapshot'];row=self.require(db,self.table,task['project_id'],snapshot['figure_version_id'])
        if row['task_id']!=task['id'] or row['config_json']!=snapshot['config'] or digest(row['config_json'])!=row['config_sha256']:raise invalid()
        if runtime:
            from app.adapters.research_figure_render import renderer_identity
            if snapshot.get('renderer_identity') != renderer_identity():
                raise StorageError('research_figure_renderer_retired',
                                   '此图件任务使用的旧版绘图流程已停用。请使用当前流程新建图件。', 409)
        from .contracts import FrozenResearchFigureRequest
        request=FrozenResearchFigureRequest.model_validate(snapshot['config'])
        _,panels,raws,caption_sources,facts=self._frozen_in_phase(db,task['project_id'],request,phase=phase,progress=progress,
            frozen_panels=snapshot['panels'],allow_stale_labels=allow_stale_labels,
            customer_originals=customer_figure_entrypoint(task) is not None)
        if (panels!=snapshot['panels'] or facts!=snapshot['caption_facts']
            or len(caption_sources)!=len(snapshot['caption_sources'])
            or any(not matches_frozen_source(s.model_dump(mode='json'),old) for s,old in zip(caption_sources,snapshot['caption_sources']))):raise invalid()
        return dict(config=snapshot['config'],panels=[{k:v for k,v in panel.items() if k!='statistics_png'} for panel in panels],raws=raws,caption_facts=facts)

    def get(self,project,identifier,*,progress=None):
        with self.store.connection() as db:
            with VerificationPhase(db,self.assets,project) as phase:
                return self._get_in_phase(db,project,identifier,phase=phase,progress=progress,allow_stale_labels=True)

    @phase_guard
    def _get_in_phase(self,db,project,identifier,*,phase,progress=None,allow_stale_labels=False):
        require_phase(phase,db,self.assets,project)
        row=self.require(db,self.table,project,identifier);task=self._figure_task(db,row)
        if digest(row['config_json'])!=row['config_sha256']:raise invalid()
        members=[];manifest=None
        if row['manifest_object_id']:
            if task['status']!='succeeded':raise invalid()
            self._require_sources_in_phase(db,task,phase=phase,runtime=False,progress=progress,allow_stale_labels=allow_stale_labels)
            checked=research_figure_source(self,db,project,row,progress=progress);manifest=checked['manifest']
            route=self.entrypoint.replace('_','-') if self.entrypoint is not None else 'research-figures'
            members=[{**m,'download_url':f'/api/v1/projects/{project}/{route}/{identifier}/members/{m["id"]}/download'} for m in checked['members']]
        return dict(id=row['id'],root_id=row['root_id'],revision=row['revision'],parent_id=row['parent_id'],config=row['config_json'],
            task=self.store.public_task(task),task_id=row['task_id'],manifest_sha256=row['manifest_sha256'],manifest=manifest,members=members)


    def assembly(self, project, page, group_page, page_size):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            return assembly_library(db, self.assets, project, self.entrypoint, page, group_page, page_size)

    def cancel_assembly(self, project, root_id, expected_revision):
        with self.store.connection(write=True) as db:
            self.lock(db, project, 'figure:' + root_id)
            root = self.require(db, self.table, project, root_id)
            if self.entrypoint is None or root['root_id'] != root_id:
                raise invalid('research_source_not_found', 404)
            self._figure_task(db, root)
            versions = db.execute('''SELECT v.id,v.revision,t.status FROM research_figure_versions v
                JOIN tasks t ON (t.id,t.project_id,t.user_id)=(v.task_id,v.project_id,v.user_id)
                WHERE v.root_id=%s AND v.project_id=%s AND v.user_id=%s ORDER BY v.revision DESC''',
                (root_id, project, self.store.user_id)).fetchall()
            if versions[0]['revision'] != expected_revision:
                raise invalid('research_revision_conflict')
            if assembly_cancelled(db, root_id):
                return
            statuses = {version['status'] for version in versions}
            if 'succeeded' not in statuses or statuses & {'queued', 'running'}:
                raise invalid('research_revision_conflict')
            db.execute('''INSERT INTO paper_figure_cancellations(root_id,project_id,user_id,cancelled_at)
                VALUES (%s,%s,%s,%s)''', (root_id, project, self.store.user_id, now()))
            version_ids = {version['id'] for version in versions}
            if self.entrypoint == SCI_FIGURE_ENTRYPOINT:
                from app.domain.research_intake.sci_resources import remove_sci_figure_placements

                remove_sci_figure_placements(db, self.store.require_project(db, project), version_ids)
            else:
                from app.domain.school_templates.thesis_figure_resources import remove_thesis_figure_placements

                remove_thesis_figure_placements(db, self.assets, project, version_ids)

    def list(self,project,page=1,page_size=20):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            parameters = (project, self.store.user_id)
            page_bounds = (page_size, (page - 1) * page_size)
            scope = ' FROM research_figure_versions f WHERE f.project_id=%s AND f.user_id=%s'
            if self.entrypoint is None:
                rows = db.execute('SELECT f.id' + scope + ' ORDER BY f.created_at DESC,f.id LIMIT %s OFFSET %s',
                                  (*parameters, *page_bounds)).fetchall()
                total = db.execute('SELECT count(*) AS n' + scope, parameters).fetchone()['n']
            else:
                scope = ''' FROM research_figure_versions f
                    JOIN tasks t ON (t.id,t.project_id,t.user_id)=(f.task_id,f.project_id,f.user_id)
                    WHERE f.project_id=%s AND f.user_id=%s AND t.task_type='research_figure'
                      AND t.input_snapshot->>'entrypoint'=%s
                      AND NOT EXISTS (SELECT 1 FROM paper_figure_cancellations c WHERE c.root_id=f.root_id)'''
                parameters += (self.entrypoint,)
                rows = db.execute('''WITH attempts AS (
                    SELECT f.id, f.root_id, f.revision, t.status,
                           max(f.revision) OVER by_figure AS latest_revision,
                           max(f.created_at) OVER by_figure AS latest_submission''' + scope + '''
                    WINDOW by_figure AS (PARTITION BY f.root_id)
                ), current_figures AS (
                    SELECT DISTINCT ON (root_id) id, root_id, latest_revision, latest_submission FROM attempts
                    ORDER BY root_id, CASE
                        WHEN revision=latest_revision AND status IN ('queued','running') THEN 0
                        WHEN status='succeeded' THEN 1 ELSE 2 END, revision DESC
                ) SELECT id, latest_revision FROM current_figures
                ORDER BY latest_submission DESC, root_id LIMIT %s OFFSET %s''', (*parameters, *page_bounds)).fetchall()
                total = db.execute('SELECT count(DISTINCT f.root_id) AS n' + scope, parameters).fetchone()['n']
        items = []
        for row in rows:
            item = self.get(project, row['id'])
            if self.entrypoint is not None:
                item['latest_revision'] = row['latest_revision']
            items.append(item)
        return dict(items=items, page=page, page_size=page_size, total=total)

    def member(self,project,identifier,member_id):
        with self.store.connection() as db:
            row=self.require(db,self.table,project,identifier)
            task=self._figure_task(db,row)
            if not row['manifest_object_id'] or task['status']!='succeeded':raise invalid('research_source_incomplete',422)
            self.require_sources(db,task,runtime=False,allow_stale_labels=True)
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
