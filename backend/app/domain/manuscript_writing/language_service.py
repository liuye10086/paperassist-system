"""Per-item explicit language review bound to immutable science and export bytes."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.literature_evidence.service import request_data
from app.domain.manuscripts.service import now
from .live_review import LiveReviewService
from .language_contracts import LanguagePreparation,LanguageReviewRequest
from .language import prepare_candidate,editable_fields,figure_materials,inventory,validate_decisions,RENDERER_VERSION
from .numeric_review import NUMERIC_VERSION,validation_version


def invalid(exc):
    return StorageError('manuscript_writing_language_invalid','全文语言审核不完整、图内文字未知、内容SHA不符或修改越过科学审核边界。',422)


def artifact_sha(row):
    return digest({k:row[k] for k in ('id','request_id','manuscript_id','base_version_id','project_id','user_id','review_id','review_sha256','request_json','candidate_json','inventory_json')})


class LanguageReviewService(LiveReviewService):
    def prepare(self,db,project,review,body,*,numeric_version=NUMERIC_VERSION):
        if body['review_id']!=review['id'] or body['review_sha256']!=review['review_sha256']: raise source_conflict()
        try:
            candidate=prepare_candidate(review['reviewed_candidate_json'],body,numeric_version=numeric_version);seen=set()
            for replacement in body['figure_versions']:
                identity=replacement['figure_id']
                if identity in seen: raise ValueError('Duplicate figure')
                seen.add(identity)
                figure=next((f for g in candidate['results_groups'] for f in g['figures'] if f['id']==identity),None)
                if not figure or figure['sha256']!=replacement['original_sha256']: raise ValueError('Original image drift')
                from app.domain.manuscripts.figure_language import FigureLanguageService
                service=FigureLanguageService(self.assets);version=service.row(db,project,replacement['version_id']);snap=version['snapshot_json']
                source=next(s for s in candidate['sources'] if s['id']==figure['source_ids'][0]);original=snap['original']
                if (original['sha256']!=figure['sha256'] or original['file_id']!=source['file_id'] or original['id']!=source['id'] or original['kind']!=source['kind'] or original.get('image_id')!=figure.get('image_id') or snap['output_language']!=candidate['output_language']): raise ValueError('Replacement is not bound to this original')
                figure.update(language_version_id=version['id'],sha256=snap['sha256'],preview_url=f'/api/v1/projects/{project}/manuscript-figure-language-versions/{version["id"]}/download')
            images,image_items=figure_materials(self.assets,db,project,candidate)
            items=inventory(candidate,images,image_items)
        except (ValueError,KeyError,TypeError,StopIteration) as exc: raise invalid(exc) from exc
        return candidate,items

    def context(self,project,identity,request_id,review_id,request=None):
        with self.store.connection() as db:
            review=super().row(db,project,identity,request_id,review_id)
            self.validate_frozen(db,project,identity,request_id,review)
            body=request_data(LanguagePreparation,request or dict(schema_version=2,review_id=review_id,review_sha256=review['review_sha256']))
            candidate,items=self.prepare(db,project,review,body)
            return dict(schema_version=2,review_id=review_id,review_sha256=review['review_sha256'],output_language=candidate['output_language'],candidate=candidate,inventory=items,inventory_sha256=digest(items),editable_fields=editable_fields(review['reviewed_candidate_json']),renderer_version=RENDERER_VERSION)

    def language_row(self,db,project,identity,request_id,language_id,*,for_admission=False,seen=None):
        self.manuscripts.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_writing_language_reviews WHERE id=%s AND request_id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(language_id,request_id,identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('task_not_found','语言审核版本不存在。',404)
        body=request_data(LanguageReviewRequest,row['request_json'])
        if body!=row['request_json'] or digest(body)!=row['request_digest'] or digest(row['candidate_json'])!=row['candidate_sha256'] or digest(row['inventory_json'])!=row['inventory_sha256'] or artifact_sha(row)!=row['artifact_sha256']: raise source_conflict()
        review=super().row(db,project,identity,request_id,row['review_id'])
        if review['review_sha256']!=row['review_sha256'] or review['base_version_id']!=row['base_version_id']: raise source_conflict()
        try:version=validation_version(row['candidate_json']['writing_provenance'].get('language_numeric_validation_version',1))
        except ValueError as exc:raise source_conflict() from exc
        candidate,items=self.prepare(db,project,review,body,numeric_version=version)
        self.finish(candidate,row['id'],row['review_sha256'],numeric_version=version)
        if candidate!=row['candidate_json'] or items!=row['inventory_json']: raise source_conflict()
        try: validate_decisions(items,body,candidate['output_language'])
        except ValueError as exc: raise source_conflict() from exc
        if for_admission:
            self.validate_frozen(db,project,identity,request_id,review,strict_numeric=True,seen=seen)
            try:prepare_candidate(review['reviewed_candidate_json'],body)
            except ValueError as exc:raise invalid(exc) from exc
        return row

    @staticmethod
    def finish(candidate,identity,science_sha,*,numeric_version=NUMERIC_VERSION):
        candidate['writing_provenance'].update(language_review_id=identity,scientific_review_sha256=science_sha,verification_status='scientific_and_language_reviewed')
        if validation_version(numeric_version)==NUMERIC_VERSION:candidate['writing_provenance']['language_numeric_validation_version']=NUMERIC_VERSION

    def view_language(self,row):
        return dict(id=row['id'],request_id=row['request_id'],review_id=row['review_id'],review_sha256=row['review_sha256'],candidate=row['candidate_json'],candidate_sha256=row['candidate_sha256'],inventory=row['inventory_json'],inventory_sha256=row['inventory_sha256'],artifact_sha256=row['artifact_sha256'],request=row['request_json'],decided_by=row['user_id'],created_at=row['created_at'].isoformat())

    def get_language(self,project,identity,request_id,language_id):
        with self.store.connection() as db: return self.view_language(self.language_row(db,project,identity,request_id,language_id))

    def create_language(self,project,identity,request_id,request,key):
        require_key(key);body=request_data(LanguageReviewRequest,request)
        with self.store.connection(write=True) as db:
            self.citations.evidence.lock(db,project)
            review=super().row(db,project,identity,request_id,body['review_id'])
            old=db.execute('SELECT id,request_digest FROM manuscript_writing_language_reviews WHERE request_id=%s AND request_key=%s',(request_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body): raise StorageError('task_idempotency_conflict','语言审核标识已用于其他输入。',409)
                return self.view_language(self.language_row(db,project,identity,request_id,old['id'])),200
            self.assert_current(db,project,identity,request_id,review)
            candidate,items=self.prepare(db,project,review,body)
            try: validate_decisions(items,body,candidate['output_language'])
            except ValueError as exc: raise invalid(exc) from exc
            language_id=str(uuid4());self.finish(candidate,language_id,review['review_sha256'])
            row=dict(id=language_id,request_id=request_id,manuscript_id=identity,base_version_id=review['base_version_id'],project_id=project,user_id=self.store.user_id,review_id=review['id'],review_sha256=review['review_sha256'],request_key=key,request_json=body,request_digest=digest(body),candidate_json=candidate,candidate_sha256=digest(candidate),inventory_json=items,inventory_sha256=digest(items),created_at=now())
            row['artifact_sha256']=artifact_sha(row)
            db.execute('INSERT INTO manuscript_writing_language_reviews('+','.join(row)+') VALUES ('+','.join(['%s']*len(row))+')',tuple(Jsonb(v) if isinstance(v,(dict,list)) else v for v in row.values()))
            return self.view_language(self.language_row(db,project,identity,request_id,language_id)),201
