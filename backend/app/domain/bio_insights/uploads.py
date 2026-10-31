"""Original-only resource uploads; CSV/TSV also gain a literal parse version."""
from pathlib import Path
import hashlib

from app.adapters.bio_insights_store import BioInsightsStore,identity,invalid,now
from app.domain.bioinformatics.service import require_key

EXTENSIONS=('.gaf','.obo','.gmt','.tsv','.csv','.gaf.gz','.obo.gz','.gmt.gz','.tsv.gz')


class BioResourceUploadService(BioInsightsStore):
    def recover(self,project,key):
        require_key(key);operation=identity(project,'resource-upload',key)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            reservation=db.execute('SELECT * FROM storage_reservations WHERE project_id=%s AND owner_id=%s AND operation_key=%s',
                (project,self.store.user_id,'bio-resource-original:'+operation)).fetchone()
            if not reservation:raise invalid('bio_insight_not_found',404)
            row=db.execute('SELECT * FROM files WHERE project_id=%s AND uploader_id=%s AND object_key=%s',
                (project,self.store.user_id,reservation['object_key'])).fetchone()
            if not row:raise invalid('bio_insight_not_found',404)
            self.assets.original(dict(row))
            return self.view(db,dict(row))

    def upload(self,project,filename,content,key):
        require_key(key)
        if not filename or filename!=Path(filename).name or any(c in filename for c in ('/','\\','\x00')) or len(filename)>255:
            raise invalid('bio_insight_file_invalid',422)
        if not filename.lower().endswith(EXTENSIONS):raise invalid('bio_insight_file_unsupported',422)
        if not 0<len(content)<=268435456:raise invalid('bio_insight_file_limit_exceeded',413)
        operation=identity(project,'resource-upload',key)
        with self.store.connection(write=True) as db:
            self.lock(db,project,'resource-upload:'+key)
            # Existing file metadata is authoritative; the descriptor identity
            # includes content, so replay compares it before any new write.
            # A durable operation key lives in the ledger reservation; it also
            # prevents one request key from accepting different bytes.
            reservation=db.execute('SELECT * FROM storage_reservations WHERE project_id=%s AND owner_id=%s AND operation_key=%s',
                (project,self.store.user_id,'bio-resource-original:'+operation)).fetchone()
            if reservation:
                if reservation['sha256']!=hashlib.sha256(content).hexdigest() or reservation['size_bytes']!=len(content):raise invalid('bio_insight_idempotency_conflict')
                prior=db.execute('SELECT * FROM files WHERE object_key=%s AND project_id=%s AND uploader_id=%s',
                    (reservation['object_key'],project,self.store.user_id)).fetchone()
                if not prior or prior['filename']!=filename:raise invalid('bio_insight_idempotency_conflict')
                self.assets.original(dict(prior))
                return self.view(db,dict(prior)),200
            from .table_parse import scan
            if filename.lower().endswith(('.csv','.tsv')):scan(content,filename)
            descriptor=self.assets.objects.put_original(project,operation,'bio_component',content,db=db,operation_key='bio-resource-original:'+operation)
            file=dict(id=descriptor.id,project_id=project,filename=filename,file_type='bio_component',size_bytes=descriptor.size_bytes,
                sha256=descriptor.sha256,uploaded_at=now(),parse_status='stored',uploader_id=self.store.user_id,storage_backend=descriptor.storage_backend,
                object_key=descriptor.object_key,metadata_revision=1,parse_revision=0)
            db.execute("INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,uploader_id,storage_backend,object_key,metadata_revision,parse_revision) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0)",
                tuple(file[k] for k in ('id','project_id','filename','file_type','size_bytes','sha256','uploaded_at','parse_status','uploader_id','storage_backend','object_key')))
            if filename.lower().endswith(('.csv','.tsv')):
                from .table_parse import persist
                persist(self.store,db,project,file,content);file['parse_status']='parsed'
            db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',(now().isoformat(),project))
            return self.view(db,file),201

    def view(self,db,file):
        parse=db.execute('SELECT id FROM file_parse_results WHERE file_id=%s AND completed_at IS NOT NULL ORDER BY version DESC LIMIT 1',(file['id'],)).fetchone()
        return dict(file_id=file['id'],filename=file['filename'],sha256=file['sha256'],size_bytes=file['size_bytes'],parse_status=file['parse_status'],
                    parse_version_id=parse['id'] if parse else None,table_reader_identity=parse['id'] if parse else None)
