"""Server-computed full-resolution regions and normalized immutable evidence."""
import json
import math
from app.adapters.bio_analysis_store import BioAnalysisStore,identity,base_row,insert,lock,now,error,scoped_object
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
        selected={r['label_id'] for r in matches}|{l['id'] for l in labels if point.get('cluster') in l.get('cluster_ids',[])}
        label=None;status='unknown'
        if len(selected)==1:label=next(iter(selected));status='assigned'
        elif selected:
            if policy=='priority' and matches:label=max(matches,key=lambda r:r['priority'])['label_id'];status='assigned'
            else:status='ambiguous'
        result.append(dict(barcode=point['barcode'],label_id=label,region_ids=[r['id'] for r in matches],status=status))
    return result


class BioAnnotationStore(BioAnalysisStore):
    def __init__(self,assets):
        super().__init__(assets);self.annotation_objects=BioAnnotationObjects(assets.directory)

    def validate(self,db,project,request):
        _,manifest,members,barcodes,_=self.axes(db,project,request.raw_source)
        positions=next((m for m in members if m['key']=='positions_index'),None)
        if not positions:raise error('bio_annotation_invalid',422)
        pmap={p['barcode']:p for p in json.loads(self.raw_store.objects.read(positions))}
        points=[dict(barcode=b,x=pmap.get(b,{}).get('pxl_col_in_fullres'),y=pmap.get(b,{}).get('pxl_row_in_fullres')) for b in barcodes]
        if request.processed_dataset_version_id:
            processed,_,_=self.processed_record(db,project,request.processed_dataset_version_id)
            if processed['raw_dataset_version_id']!=request.raw_source.dataset_version_id:raise conflict('bio_input_integrity_changed')
        # Section-specific annotations require actual frozen mapping; never infer a section.
        if any(r.section for r in request.regions) or any(l.cluster_ids for l in request.labels):
            if not request.processed_dataset_version_id:raise error('bio_annotation_invalid',422)
            import csv,io
            _,_,artifacts=self.processed_record(db,project,request.processed_dataset_version_id)
            obs=next((m for m in artifacts if m['key']=='observations'),None)
            if not obs:raise error('bio_input_integrity_changed')
            observations={r['barcode']:r for r in csv.DictReader(io.StringIO(self.objects.read(obs).decode()),delimiter='\t')}
            clusters={r.get('cluster') for r in observations.values() if r.get('kept','').lower()=='true' and r.get('cluster')}
            if any(not set(l.cluster_ids)<=clusters for l in request.labels):raise error('bio_annotation_invalid',422)
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
            else:
                artifact=self.require(db,'bio_analysis_artifacts',project,evidence.analysis_artifact_id)
                if artifact['processed_dataset_version_id']!=request.processed_dataset_version_id or artifact['role']!='marker_table':raise error('bio_annotation_invalid',422)
        assignments=assign_regions(points,[r.model_dump() for r in request.regions],request.overlap_policy,[l.model_dump() for l in request.labels])
        return assignments,dict(assigned=sum(r['status']=='assigned' for r in assignments),unknown=sum(r['status']=='unknown' for r in assignments),
            ambiguous=sum(r['status']=='ambiguous' for r in assignments),coordinate_space='fullres',boundary='inside',biological_validation=False)

    def get(self,project,set_id,version_id):
        with self.store.connection() as db:
            row=self.require(db,'bio_annotation_versions',project,version_id)
            if row['set_id']!=set_id:raise error('bio_annotation_not_found',404)
            geometry=scoped_object(db,project,self.store.user_id,row['geometry_object_id']);assignments=scoped_object(db,project,self.store.user_id,row['assignments_object_id'])
            if geometry['sha256']!=row['geometry_sha256'] or assignments['sha256']!=row['assignments_sha256']:raise conflict('bio_input_integrity_changed')
            value=json.loads(self.annotation_objects.read(geometry));rows=json.loads(self.annotation_objects.read(assignments))['rows']
            self.raw(db,project,value['raw_source'])
            evidence=[{k:r[k] for k in ('label_id','kind','analysis_artifact_id','file_id','note')} for r in db.execute('SELECT * FROM bio_annotation_evidence WHERE annotation_version_id=%s ORDER BY id',(version_id,))]
            return dict(id=version_id,set_id=set_id,name=value['name'],version=row['version'],revision=row['version'],raw_source=value['raw_source'],
                processed_dataset_version_id=row['processed_dataset_version_id'],labels=row['labels_json'],regions=value['regions'],overlap_policy=value['overlap_policy'],
                checks=row['checks_json'],assignments=rows,evidence=evidence)

    def save(self,project,request,key,set_id=None):
        require_key(key);sha=digest(request.model_dump(mode='json'));identifier=identity(project,'annotation',key);root_id=set_id or identifier
        with self.store.connection() as db:
            self.store.require_project(db,project)
            replay=db.execute('SELECT * FROM bio_annotation_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha or (set_id and replay['set_id']!=set_id):raise error('task_idempotency_conflict')
                return self.get(project,replay['set_id'],replay['id'])
            assignments,checks=self.validate(db,project,request)
        geometry=dict(schema_version=1,name=request.name,coordinate_space='fullres',raw_source=request.raw_source.model_dump(),overlap_policy=request.overlap_policy,
            regions=[r.model_dump() for r in request.regions])
        records,reservations=self.admit_documents(project,identifier,'bio_annotation',self.annotation_objects,
            {'geometry':canonical(geometry),'assignments':canonical(dict(schema_version=1,rows=assignments))})
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);lock(db,project,'annotation:'+key)
            replay=db.execute('SELECT * FROM bio_annotation_versions WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise error('task_idempotency_conflict')
            else:
                self.validate(db,project,request)
                if set_id:
                    db.execute('SELECT id FROM bio_annotation_sets WHERE id=%s AND project_id=%s FOR UPDATE',(set_id,project))
                    root=self.require(db,'bio_annotation_sets',project,set_id)
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
