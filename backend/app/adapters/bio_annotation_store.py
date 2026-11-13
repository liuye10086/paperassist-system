"""Server-computed full-resolution regions and normalized immutable evidence."""
import json
import math
from app.adapters.bio_analysis_store import BioAnalysisStore,identity,base_row,insert,lock,now,error,scoped_object,object_by_key
from app.adapters.bio_objects import BioAnnotationObjects
from app.domain.bioinformatics.contracts import canonical,digest,conflict
from app.domain.bioinformatics.service import require_key


def inside(point,polygon):
    x,y=point;result=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        ax,ay=a;bx,by=b
        cross=(x-ax)*(by-ay)-(y-ay)*(bx-ax)
        if abs(cross)<=1e-8 and min(ax,bx)-1e-8<=x<=max(ax,bx)+1e-8 and min(ay,by)-1e-8<=y<=max(ay,by)+1e-8:return True
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:result=not result
    return result


def valid_polygon(polygon):
    vertices=polygon[:-1] if polygon[0]==polygon[-1] else polygon
    if len({tuple(p) for p in vertices})!=len(vertices):return False
    edges=list(zip(vertices,vertices[1:]+vertices[:1]))
    if abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in edges))<1e-8:return False
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    for i,(a,b) in enumerate(edges):
        for j,(c,d) in enumerate(edges[i+1:],i+1):
            if j==i+1 or (i==0 and j==len(edges)-1):continue
            if max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0]) or max(a[1],b[1])<min(c[1],d[1]) or max(c[1],d[1])<min(a[1],b[1]):continue
            if cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0:return False
    return True


def assign_regions(points,regions,policy,labels=()):
    result=[]
    for point in points:
        matches=[r for r in regions if point.get('x') is not None and point.get('y') is not None and inside((point['x'],point['y']),r['points'])
            and (not r.get('section') or r['section']==point.get('section'))]
        selected={r['label_id'] for r in matches}|{l['id'] for l in labels if point.get('cluster') in l.get('cluster_ids',[]) or point['barcode'] in l.get('cell_ids',[])}
        label=None;status='unknown'
        if len(selected)==1:label=next(iter(selected));status='assigned'
        elif selected:
            if policy=='priority' and matches:label=max(matches,key=lambda r:r['priority'])['label_id'];status='assigned'
            else:status='ambiguous'
        if label is not None:
            declared=next((l.get('status') for l in labels if l['id']==label),None)
            if declared in ('unknown','uncertain'):status=declared
        result.append(dict(barcode=point['barcode'],label_id=label,region_ids=[r['id'] for r in matches],status=status))
    return result


def annotation_request_digests(request):
    value=request.model_dump(mode='json');accepted={digest(value)}
    # Existing spatial receipts predate the optional cell selector. Its empty
    # default changes no selection and must not invalidate identical replays.
    if all(not label.get('cell_ids') for label in value['labels']):
        for label in value['labels']:label.pop('cell_ids',None)
        accepted.add(digest(value))
    return accepted


class BioAnnotationStore(BioAnalysisStore):
    def __init__(self,assets):
        super().__init__(assets);self.annotation_objects=BioAnnotationObjects(assets.directory)

    def validate(self,db,project,request):
        _,manifest,members,barcodes,_=self.axes(db,project,request.raw_source)
        single_cell=manifest.get('assay')=='single_cell'
        positions=next((m for m in members if m['key']=='positions_index'),None)
        if single_cell:
            if not request.processed_dataset_version_id or request.regions:raise error('bio_annotation_invalid',422)
            pmap={}
        else:
            if not positions:raise error('bio_annotation_invalid',422)
            pmap={p['barcode']:p for p in json.loads(self.raw_store.objects.read(positions))}
        points=[dict(barcode=b,x=pmap.get(b,{}).get('pxl_col_in_fullres'),y=pmap.get(b,{}).get('pxl_row_in_fullres')) for b in barcodes]
        if request.processed_dataset_version_id:
            processed,_,_=self.processed_record(db,project,request.processed_dataset_version_id)
            if processed['raw_dataset_version_id']!=request.raw_source.dataset_version_id:raise conflict('bio_input_integrity_changed')
        # Section-specific annotations require actual frozen mapping; never infer a section.
        if single_cell or any(r.section for r in request.regions) or any(l.cluster_ids or l.cell_ids for l in request.labels):
            if not request.processed_dataset_version_id:raise error('bio_annotation_invalid',422)
            import csv,io
            _,_,artifacts=self.processed_record(db,project,request.processed_dataset_version_id)
            obs=next((m for m in artifacts if m['key']=='observations'),None)
            if not obs:raise error('bio_input_integrity_changed')
            observations={r['barcode']:r for r in csv.DictReader(io.StringIO(self.objects.read(obs).decode()),delimiter='\t')}
            clusters={r.get('cluster') for r in observations.values() if r.get('kept','').lower()=='true' and r.get('cluster')}
            if any(not set(l.cluster_ids)<=clusters for l in request.labels):raise error('bio_annotation_invalid',422)
            retained={b for b,r in observations.items() if r.get('kept','').lower()=='true'}
            if not retained<=set(barcodes) or any(not set(l.cell_ids)<=retained for l in request.labels):raise error('bio_annotation_invalid',422)
            if single_cell:points=[p for p in points if p['barcode'] in retained]
            for point in points:
                row=observations.get(point['barcode'],{})
                point.update(section=row.get('section') or None,cluster=row.get('cluster') if row.get('kept','').lower()=='true' else None)
        for region in request.regions:
            if not valid_polygon(region.points):raise error('bio_annotation_invalid',422)
        for evidence in request.evidence:
            if evidence.kind=='file':
                file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(evidence.file_id,project)).fetchone()
                if not file:raise error('bio_annotation_invalid',422)
                self.assets.original(dict(file))
            elif evidence.kind=='marker':
                artifact=self.require(db,'bio_analysis_artifacts',project,evidence.analysis_artifact_id)
                if artifact['processed_dataset_version_id']!=request.processed_dataset_version_id or artifact['role']!='marker_table':raise error('bio_annotation_invalid',422)
        assignments=assign_regions(points,[r.model_dump() for r in request.regions],request.overlap_policy,[l.model_dump() for l in request.labels])
        return assignments,dict(assigned=sum(r['status']=='assigned' for r in assignments),unknown=sum(r['status']=='unknown' for r in assignments),
            uncertain=sum(r['status']=='uncertain' for r in assignments),ambiguous=sum(r['status']=='ambiguous' for r in assignments),coordinate_space='cell' if single_cell else 'fullres',boundary='inside',biological_validation=False)

    def get(self,project,set_id,version_id):
        with self.store.connection() as db:
            row=self.require(db,'bio_annotation_versions',project,version_id)
            if row['set_id']!=set_id:raise error('bio_annotation_not_found',404)
            geometry=scoped_object(db,project,self.store.user_id,row['geometry_object_id']);assignments=scoped_object(db,project,self.store.user_id,row['assignments_object_id'])
            if geometry['sha256']!=row['geometry_sha256'] or assignments['sha256']!=row['assignments_sha256']:raise conflict('bio_input_integrity_changed')
            value=json.loads(self.annotation_objects.read(geometry));rows=json.loads(self.annotation_objects.read(assignments))['rows']
            self.raw(db,project,value['raw_source'])
            evidence=[{k:r[k] for k in ('label_id','kind','analysis_artifact_id','file_id','note')} for r in db.execute('SELECT * FROM bio_annotation_evidence WHERE annotation_version_id=%s ORDER BY id',(version_id,))]
            members=[]
            for member in value.get('members',[]):
                stored=object_by_key(db,project,self.store.user_id,member)
                if stored['sha256']!=member['sha256']:raise conflict('bio_input_integrity_changed')
                members.append({**{k:member[k] for k in ('id','key','role','format','sha256','size_bytes')},
                    'download_url':f'/api/v1/projects/{project}/bio-annotation-sets/{set_id}/versions/{version_id}/members/{member["id"]}/download'})
            root=self.require(db,'bio_annotation_sets',project,set_id)
            return dict(id=version_id,set_id=set_id,name=value['name'],version=row['version'],revision=row['version'],raw_source=value['raw_source'],
                processed_dataset_version_id=row['processed_dataset_version_id'],labels=row['labels_json'],regions=value['regions'],overlap_policy=value['overlap_policy'],
                checks=row['checks_json'],assignments=rows,evidence=evidence,origin=value.get('origin','manual'),algorithm=value.get('algorithm'),members=members,
                created_at=row['created_at'].isoformat(),is_current=root['current_version_id']==version_id)

    def list_for_processed(self,project,identifier):
        with self.store.connection() as db:
            self.processed_record(db,project,identifier)
            rows=db.execute('SELECT id,current_version_id FROM bio_annotation_sets WHERE project_id=%s AND processed_dataset_version_id=%s AND created_by=%s ORDER BY updated_at DESC,id',
                (project,identifier,self.store.user_id)).fetchall()
        return dict(items=[self.get(project,r['id'],r['current_version_id']) for r in rows if r['current_version_id']])

    def member(self,project,set_id,version_id,member_id):
        value=self.get(project,set_id,version_id)
        if not any(m['id']==member_id for m in value['members']):raise error('bio_member_not_found',404)
        with self.store.connection() as db:
            row=self.require(db,'bio_annotation_versions',project,version_id)
            geometry=scoped_object(db,project,self.store.user_id,row['geometry_object_id'])
            body=json.loads(self.annotation_objects.read(geometry))
            member=next(m for m in body['members'] if m['id']==member_id)
            object_by_key(db,project,self.store.user_id,member)
            return {**member,'filename':member['key']+'.'+member['format']},self.annotation_objects.read(member)

    def save(self,project,request,key,set_id=None):
        require_key(key);sha=digest(request.model_dump(mode='json'));identifier=identity(project,'annotation',key);root_id=set_id or identifier
        accepted_digests=annotation_request_digests(request)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            replay=db.execute('SELECT * FROM bio_annotation_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest'] not in accepted_digests or (set_id and replay['set_id']!=set_id):raise error('task_idempotency_conflict')
                return self.get(project,replay['set_id'],replay['id'])
            assignments,checks=self.validate(db,project,request)
        geometry=dict(schema_version=1,name=request.name,coordinate_space=checks['coordinate_space'],raw_source=request.raw_source.model_dump(),overlap_policy=request.overlap_policy,
            regions=[r.model_dump() for r in request.regions])
        records,reservations=self.admit_documents(project,identifier,'bio_annotation',self.annotation_objects,
            {'geometry':canonical(geometry),'assignments':canonical(dict(schema_version=1,rows=assignments))})
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);lock(db,project,'annotation:'+key)
            replay=db.execute('SELECT * FROM bio_annotation_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest'] not in accepted_digests or (set_id and replay['set_id']!=set_id):raise error('task_idempotency_conflict')
            else:
                self.validate(db,project,request)
                if set_id:
                    db.execute('SELECT id FROM bio_annotation_sets WHERE id=%s AND project_id=%s FOR UPDATE',(set_id,project))
                    root=self.require(db,'bio_annotation_sets',project,set_id)
                    current=self.require(db,'bio_annotation_versions',project,root['current_version_id'])
                    if current['checks_json'].get('candidate_only'):raise error('bio_annotation_invalid',422)
                    if root['revision']!=request.expected_revision or root['raw_dataset_version_id']!=request.raw_source.dataset_version_id or root['processed_dataset_version_id']!=request.processed_dataset_version_id:raise conflict('bio_revision_conflict')
                    version=root['revision']+1;parent=root['current_version_id']
                else:
                    if request.expected_revision!=0:raise conflict('bio_revision_conflict')
                    version=1;parent=None
                    insert(db,'bio_annotation_sets',{**base_row(root_id,project,self.store.user_id),'name':request.name,'revision':1,'current_version_id':None,'updated_at':now(),
                        'raw_dataset_version_id':request.raw_source.dataset_version_id,'processed_dataset_version_id':request.processed_dataset_version_id})
                objects=self.settle_documents(db,project,records,reservations)
                insert(db,'bio_annotation_versions',{**base_row(identifier,project,self.store.user_id),'set_id':root_id,'version':version,'parent_id':parent,
                    'raw_dataset_version_id':request.raw_source.dataset_version_id,'processed_dataset_version_id':request.processed_dataset_version_id,
                    'geometry_object_id':objects['geometry']['id'],'geometry_sha256':records['geometry']['sha256'],
                    'assignments_object_id':objects['assignments']['id'],'assignments_sha256':records['assignments']['sha256'],
                    'labels_json':[l.model_dump() for l in request.labels],'checks_json':checks,'request_key':key,'request_digest':sha})
                for index,evidence in enumerate(request.evidence):
                    insert(db,'bio_annotation_evidence',{**base_row(identity(project,'annotation-evidence',identifier+':'+str(index)),project,self.store.user_id),
                        'annotation_version_id':identifier,**evidence.model_dump()})
                db.execute('UPDATE bio_annotation_sets SET revision=CASE WHEN current_version_id IS NULL THEN revision ELSE revision+1 END,current_version_id=%s,name=%s,updated_at=%s WHERE id=%s',
                    (identifier,request.name,now(),root_id))
        return self.get(project,root_id,identifier)
