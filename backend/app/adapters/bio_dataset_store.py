"""Bounded immutable-version reads; full matrices are never densified."""
from app.adapters.bio_objects import BioObjects
from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import canonical, conflict, member_filename
from app.domain.bioinformatics.service import BioDatasetService, public_checks


class BioDatasetStore:
    def __init__(self,assets):
        self.assets=assets
        self.store=TaskStore(assets.owner_id,assets.db_config)
        self.objects=BioObjects(assets.directory)

    def list(self,project_id,page):
        with self.store.connection() as db:
            self.store.require_project(db,project_id)
            total=db.execute('SELECT count(*) AS n FROM bio_datasets WHERE project_id=%s',(project_id,)).fetchone()['n']
            rows=db.execute('''SELECT d.id,d.name,d.assay,d.revision,d.current_version_id,v.version,v.shape_json
                FROM bio_datasets d LEFT JOIN bio_dataset_versions v ON v.id=d.current_version_id
                WHERE d.project_id=%s ORDER BY d.created_at DESC,d.id LIMIT 5 OFFSET %s''',(project_id,(page-1)*5)).fetchall()
            items=[]
            for row in rows:
                item={k:row[k] for k in ('id','name','assay','revision','current_version_id')}
                item['current_version']=dict(id=row['current_version_id'],version=row['version'],shape=row['shape_json']) if row['current_version_id'] else None
                items.append(item)
            return dict(items=items,total=total,page=page,page_size=5)

    def require_version(self,db,project_id,dataset_id,version_id):
        self.store.require_project(db,project_id)
        row=db.execute('''SELECT v.*,o.object_key,o.size_bytes,o.sha256 FROM bio_dataset_versions v
            JOIN storage_objects o ON o.id=v.manifest_object_id
            JOIN storage_references r ON r.object_id=o.id AND r.project_id=v.project_id
            WHERE v.project_id=%s AND v.dataset_id=%s AND v.id=%s AND r.owner_id=%s
              AND r.kind='bio_dataset' AND o.state='present' ''',(project_id,dataset_id,version_id,self.store.user_id)).fetchone()
        if not row:
            raise StorageError('bio_version_not_found','数据集固定版本不存在。',404)
        row=dict(row)
        if row['sha256']!=row['manifest_sha256']:
            raise conflict()
        manifest=self.objects.read_json(row)
        if manifest.get('parser_version')!=row['parser_version']:
            raise conflict()
        return row,manifest

    def members(self,db,version):
        return [dict(r) for r in db.execute('''SELECT m.*,o.object_key FROM bio_dataset_members m
            JOIN storage_objects o ON o.id=m.object_id JOIN storage_references r ON r.object_id=o.id
            AND r.project_id=m.project_id WHERE m.dataset_version_id=%s AND r.owner_id=%s
            AND r.kind='bio_dataset' AND o.state='present' ORDER BY m.role,m.id''',(version['id'],self.store.user_id))]

    @staticmethod
    def verify_member(member,expected):
        if not member or not expected or any(member[k]!=expected[k] for k in (
                'id','role','format','compression','verification_state','sha256','size_bytes','source_file_id','source_member_name')):
            raise conflict()

    def version(self,project_id,dataset_id,version_id):
        with self.store.connection() as db:
            version,manifest=self.require_version(db,project_id,dataset_id,version_id)
            members=self.members(db,version)
            public=[]
            frozen={m['id']:m for m in manifest.get('members',[])}
            for m in members:
                self.verify_member(m,frozen.get(m['id']))
                self.objects.read(m)
                public.append({k:m[k] for k in ('id','role','verification_state','sha256','size_bytes')})
                public[-1].update(filename=member_filename(frozen[m['id']]),download_url=self.base(project_id,dataset_id,version_id)+f"/members/{m['id']}")
            expected={m['id'] for m in manifest.get('members',[])}
            if expected != {m['id'] for m in members}:
                raise conflict()
            return dict(id=version['id'],dataset_id=dataset_id,version=version['version'],manifest_sha256=version['manifest_sha256'],
                shape=version['shape_json'],checks=public_checks(version['checks_json']),source=BioDatasetService.source(version,[f['id'] for f in manifest['source_files']]),
                members=public,summary=dict(manifest.get('verification',{})),spatial=manifest.get('spatial'))

    @staticmethod
    def base(project_id,dataset_id,version_id):
        return f'/api/v1/projects/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}'

    def manifest(self,project_id,dataset_id,version_id):
        with self.store.connection() as db:
            row,_=self.require_version(db,project_id,dataset_id,version_id)
            return self.objects.read(row)

    def member(self,project_id,dataset_id,version_id,member_id):
        with self.store.connection() as db:
            row,manifest=self.require_version(db,project_id,dataset_id,version_id)
            members=self.members(db,row)
            member=next((m for m in members if m['id']==member_id),None)
            expected=next((m for m in manifest.get('members',[]) if m['id']==member_id),None)
            if not member or not expected:
                raise StorageError('bio_member_not_found','数据集成员不存在。',404)
            self.verify_member(member,expected)
            return {**member,'filename':member_filename(expected)},self.objects.read(member)

    def preview(self,project_id,dataset_id,version_id,features_page,observations_page):
        import numpy as np
        import json
        with self.store.connection() as db:
            row,manifest=self.require_version(db,project_id,dataset_id,version_id)
            members=self.members(db,row)
            by_id={m['id']:m for m in members}
            by_key={m['key']:m for m in manifest['members']}
            def record(key):
                frozen=by_key.get(key)
                member=by_id.get(frozen['id']) if frozen else None
                self.verify_member(member,frozen)
                self.objects.read(member)
                return member
            def index(key):
                return json.loads(self.objects.read(record(key)))
            axis=index('features_index')
            features=axis['feature_ids']
            if len(features)!=len(axis['feature_symbols']) or len(features)!=len(axis['feature_types']):
                raise conflict()
            observations=index('barcodes_index')['barcodes']
            nf,no=len(features),len(observations)
            f0,o0=(features_page-1)*40,(observations_page-1)*20
            f1,o1=min(f0+40,nf),min(o0+20,no)
            if f0>=nf or o0>=no:
                return dict(features=[],observations=[],values=[],features_total=nf,observations_total=no)
            arrays={}
            for key in ('matrix_data','matrix_indices','matrix_indptr'):
                m=record(key)
                arrays[key]=np.load(self.objects.path(m['object_key']),mmap_mode='r',allow_pickle=False)
            data,indices,indptr=(arrays[k] for k in ('matrix_data','matrix_indices','matrix_indptr'))
            dtypes=manifest.get('matrix_dtypes',{})
            if (str(data.dtype)!=dtypes.get('data') or str(indices.dtype)!=dtypes.get('indices') or str(indptr.dtype)!=dtypes.get('indptr')
                    or data.dtype.kind not in 'iu' or indices.dtype.kind not in 'iu' or indptr.dtype.kind not in 'iu'
                    or indptr.shape!=(no+1,) or data.shape!=indices.shape or int(indptr[-1])!=len(data)):
                raise conflict()
            values=[]
            for obs in range(o0,o1):
                start,end=int(indptr[obs]),int(indptr[obs+1])
                if not 0<=start<=end<=len(data):
                    raise conflict()
                small=[0]*(f1-f0)
                for feature,value in zip(indices[start:end],data[start:end]):
                    if f0<=feature<f1:
                        small[int(feature)-f0]=int(value)
                values.append(small)
            selected_features=[dict(id=features[i],symbol=axis['feature_symbols'][i],feature_type=axis['feature_types'][i]) for i in range(f0,f1)]
            return dict(features=selected_features,observations=observations[o0:o1],values=values,
                features_total=nf,observations_total=no,features_page=features_page,observations_page=observations_page)

    def coordinates(self,project_id,dataset_id,version_id,image_member_id=None):
        import json
        with self.store.connection() as db:
            version,manifest=self.require_version(db,project_id,dataset_id,version_id)
            members=self.members(db,version)
            frozen={m['id']:m for m in manifest['members']}
            def read(member):
                expected=frozen.get(member['id'])
                self.verify_member(member,expected)
                return self.objects.read(member)
            images=[m for m in members if m['role']=='tissue_image']
            image=next((m for m in images if m['id']==image_member_id),None) if image_member_id else next(
                (m for m in images if 'hires' in m['source_member_name']),images[0] if images else None)
            if not image:
                raise StorageError('bio_member_not_found','配套组织图不存在。',404)
            read(image)
            info=next((i for i in manifest.get('spatial',{}).get('images',[]) if i['source_member_name']==image['source_member_name']),None)
            position=next((m for m in members if m['role']=='positions_index'),None)
            if not info or not info['scale_field'] or not position:
                raise conflict()
            scale=manifest['spatial']['scalefactors'][info['scale_field']]
            points=json.loads(read(position))
            public=[dict(barcode=p['barcode'],in_tissue=p['in_tissue'],x=p['pxl_col_in_fullres']*scale,
                y=p['pxl_row_in_fullres']*scale) for p in points[:10000]]
            return dict(image=dict(id=image['id'],filename=member_filename(frozen[image['id']]),width=info['width'],height=info['height'],
                download_url=self.base(project_id,dataset_id,version_id)+f"/members/{image['id']}"),
                width=info['width'],height=info['height'],scale=scale,points=public,total=len(points),truncated=len(points)>10000)
