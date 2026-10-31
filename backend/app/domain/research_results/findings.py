"""Immutable findings freeze actual facts, conflict decisions and reviewer identity."""
from app.adapters.research_results_store import ResearchResultsStore,base,identity,insert,invalid,now
from app.domain.bioinformatics.contracts import canonical,digest
from app.domain.dataset_preparation.service import require_key
from copy import deepcopy
from .contracts import FindingVersionRequest,ResearchConflict
from .sources import ResearchSourceReader


class ResearchFindingService(ResearchResultsStore):
    def __init__(self,assets):
        super().__init__(assets);self.reader=ResearchSourceReader(assets)

    def _content(self,db,project,request):
        sources=[self.reader.read_source(project,s,db=db) for s in request.sources]
        catalogs=[self.reader.catalog(s) for s in sources]
        all_facts={f.id:f for c in catalogs for f in c.facts}
        selected=request.selected_fact_ids or list(all_facts)
        if not set(selected)<=set(all_facts):raise invalid('research_fact_unresolved',422)
        facts=[all_facts[k].model_dump(mode='json') for k in selected]
        conflicts={}
        for source in sources:
            if source.source_kind!='research_finding_version':continue
            for raw in source.content.get('conflicts',[]):
                inherited=ResearchConflict.model_validate(raw)
                if inherited.id in conflicts and conflicts[inherited.id]!=inherited:raise invalid('research_fact_unresolved',422)
                conflicts[inherited.id]=inherited
        inherited_ids=set(conflicts)
        def source_fact_ids(source):
            content=source.get('content',{})
            return {f['id'] for f in content.get('facts',[])} | set().union(
                *(source_fact_ids(s) for s in content.get('sources',[])))
        closure_facts=set(all_facts).union(*(source_fact_ids(s.model_dump(mode='json')) for s in sources))
        for conflict in request.conflicts:
            if conflict.id in conflicts and conflict.fact_ids!=conflicts[conflict.id].fact_ids:raise invalid('research_fact_unresolved',422)
            conflicts[conflict.id]=conflict
        if len(conflicts)>100:raise invalid('research_source_limit_exceeded',422)
        for conflict in conflicts.values():
            if not set(conflict.fact_ids)<=set(closure_facts if conflict.id in inherited_ids else selected):raise invalid('research_fact_unresolved',422)
            if conflict.decision!='unresolved' and not conflict.basis.strip():raise invalid('research_fact_unresolved',422)
        for claim in request.claims:
            if not set(claim.fact_ids)<=set(selected) or not set(claim.conflicts)<=set(conflicts):
                raise invalid('research_fact_unresolved',422)
            attached=[c for c in conflicts.values() if set(c.fact_ids)&set(claim.fact_ids) or c.id in claim.conflicts]
            if claim.review_decision=='adopt' and (not claim.fact_ids and not claim.figure_refs or any(c.decision=='unresolved' for c in attached)):
                raise invalid('research_fact_unresolved',422)
            figures={s.source_id for s in sources if s.source_kind in ('bio_figure_version','research_figure_version','original_file')}
            figures.update(s.source_id for s in sources if s.source_kind in ('bio_insight_result_version','bio_insight_result_member') and s.content.get('kind')=='figure' and s.figures)
            if not set(claim.figure_refs)<=figures:raise invalid('research_fact_unresolved',422)
            if claim.review_decision=='adopt' and any(all_facts[f].verification_status in ('missing','conflict') for f in claim.fact_ids):
                raise invalid('research_fact_unresolved',422)
        reviews=[]
        known=set(selected)|{c.id for c in request.claims}|set(conflicts)
        for review in request.reviews:
            if review.target_id not in known:raise invalid('research_fact_unresolved',422)
            evidence=[self.reader.read_source(project,s,db=db) for s in review.evidence]
            sources.extend(evidence)
            reviews.append({**review.model_dump(mode='json'),'evidence':[s.model_dump(mode='json') for s in evidence],
                            'reviewed_by':self.store.user_id,'reviewed_at':now().isoformat()})
        for col,table in (('requirement_version_id','research_requirement_versions'),('design_version_id','research_design_versions')):
            identifier=getattr(request,col)
            if identifier and not db.execute('SELECT id FROM '+table+' WHERE id=%s AND project_id=%s',(identifier,project)).fetchone():
                raise invalid('research_source_not_found',404)
        def merged(field):return list(dict.fromkeys(v for c in catalogs for v in getattr(c,field)))
        unique={digest(s.model_dump(mode='json')):s for s in sources}
        sources=list(unique.values())
        from app.domain.storage_governance.guards import require_scope_open
        require_scope_open(db,project,file_ids={f for source in sources for f in source.source_file_ids})
        methods={m.id:m.model_dump(mode='json') for c in catalogs for m in c.methods}
        content=dict(schema_version=1,title=request.title,sources=[s.model_dump(mode='json') for s in sources],
            facts=facts,methods=list(methods.values()),claims=[c.model_dump(mode='json') for c in request.claims],
            conflicts=[c.model_dump(mode='json') for c in conflicts.values()],reviews=reviews,
            limitations=merged('limitations'),gaps=merged('gaps'),warnings=merged('warnings'),notes=request.notes,
            requirement_version_id=request.requirement_version_id,design_version_id=request.design_version_id,
            real_model_calls=0)
        if len(facts)>1000 or len(methods)>100 or len(canonical(content))>4*1024*1024:
            raise invalid('research_source_limit_exceeded',422)
        return content,sources

    def create(self,project,request,key,set_id=None):
        require_key(key);request=FindingVersionRequest.model_validate(request)
        if set_id is not None and set_id!=request.set_id:raise invalid('research_revision_conflict')
        body=request.model_dump(mode='json');request_hash=digest(body)
        with self.store.connection(write=True) as db:
            self.lock(db,project,'finding-key:'+key)
            replay=db.execute('SELECT * FROM research_finding_versions WHERE project_id=%s AND user_id=%s AND request_key=%s',
                (project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=request_hash:raise invalid('task_idempotency_conflict')
                return self.view(db,project,dict(replay)),200
            if request.set_id:
                self.lock(db,project,'finding-root:'+request.set_id)
                root=self.require(db,'research_finding_sets',project,request.set_id)
                if root['revision']!=request.expected_revision:raise invalid('research_revision_conflict')
                revision=root['revision']+1;parent=root['current_version_id'];root_id=root['id']
            else:
                root_id=identity(project,'finding-set',key);revision=1;parent=None
            content,sources=self._content(db,project,request)
            version_id=identity(project,'finding-version',key)
            if not request.set_id:
                insert(db,'research_finding_sets',{**base(root_id,project,self.store.user_id),'title':request.title,
                    'revision':1,'current_version_id':None,'updated_at':now()})
            insert(db,'research_finding_versions',{**base(version_id,project,self.store.user_id),'set_id':root_id,
                'revision':revision,'parent_id':parent,'content_json':content,'content_sha256':digest(content),
                'requirement_version_id':request.requirement_version_id,'design_version_id':request.design_version_id,
                'request_key':key,'request_digest':request_hash})
            for source in sources:self.bind(db,project,'finding',version_id,source)
            changed=db.execute('UPDATE research_finding_sets SET title=%s,revision=%s,current_version_id=%s,updated_at=%s WHERE id=%s AND revision=%s',
                (request.title,revision,version_id,now(),root_id,request.expected_revision or 1))
            if changed.rowcount!=1:raise invalid('research_revision_conflict')
            return self.view(db,project,self.require(db,'research_finding_versions',project,version_id)),201

    def view(self,db,project,row,*,progress=None):
        content=self.verify_content(row)
        for source in content['sources']:
            selected={k:source[k] for k in ('schema_version','source_kind','source_id','locator','sha256')}
            current=self.reader.read_source(project,selected,db=db,progress=progress)
            if current.model_dump(mode='json')!=source:raise invalid()
        return self.format_view(row,content)

    @staticmethod
    def format_view(row,content):
        # Presentation only: callers must first verify content and its sources.
        # Do not expose mutable aliases of the already-verified finding value.
        return dict(id=row['id'],set_id=row['set_id'],revision=row['revision'],parent_id=row['parent_id'],
            created_at=row['created_at'],content=deepcopy(content),sha256=row['content_sha256'])

    def get(self,project,set_id,version_id):
        with self.store.connection() as db:
            row=self.require(db,'research_finding_versions',project,version_id)
            if row['set_id']!=set_id:raise invalid('research_source_not_found',404)
            return self.view(db,project,row)

    def list(self,project):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            return {'items':[dict(r) for r in db.execute('SELECT id,title,revision,current_version_id,created_at,updated_at FROM research_finding_sets WHERE project_id=%s AND user_id=%s ORDER BY updated_at DESC,id LIMIT 100',(project,self.store.user_id))]}
