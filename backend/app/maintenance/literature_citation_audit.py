"""Read-only historical provenance audit, independent of current support decisions."""
from types import SimpleNamespace
from app.core.config import get_data_dir
from app.db.database import get_database_config
from app.adapters.file_objects import LocalFileObjects
from app.domain.literature.service import digest
from app.domain.literature_citations.service import LiteratureCitationService
from app.domain.literature_citations.contracts import DraftRequest, DraftVersionRequest, MaterialConfirmationRequest
from app.domain.literature_citations.formatter import render_paragraphs


def validate_version(svc,db,row):
    project=row['project_id'];snapshot=row['snapshot_json'];svc.validate(row)
    model=DraftRequest if row['revision']==1 else DraftVersionRequest
    body=model.model_validate(row['request_json']).model_dump(mode='json')
    if row['revision']>1 and body['expected_revision']+1!=row['revision']:
        raise ValueError('Wrong predecessor')
    svc.draft_row(db,project,row['draft_id'],row['revision'])
    if any(snapshot[k]!=body[k] for k in ('title','output_language','format')) or snapshot['schema_version']!=1:
        raise ValueError('Snapshot does not match input')
    if len(snapshot['paragraphs'])!=len(body['paragraphs']):
        raise ValueError('Paragraph count changed')
    for frozen,requested in zip(snapshot['paragraphs'],body['paragraphs'],strict=True):
        if frozen['id']!=requested['id'] or len(frozen['fragments'])!=len(requested['fragments']):
            raise ValueError('Paragraph identity changed')
        for fragment,request in zip(frozen['fragments'],requested['fragments'],strict=True):
            if request['kind']=='text':
                if fragment!=request:
                    raise ValueError('Text changed')
                continue
            _,claim=svc.evidence.claim_row(db,project,request['claim_id'],request['claim_revision'])
            if any(fragment[k]!=request[k] for k in ('kind','claim_id','claim_revision')) or fragment['text']!=claim['content']:
                raise ValueError('Claim text changed')
            if len(fragment['bindings'])!=len(request['bindings']):
                raise ValueError('Binding count changed')
            refs=set()
            for bound,binding in zip(fragment['bindings'],request['bindings'],strict=True):
                if any(bound[k]!=binding[k] for k in ('review_id','metadata_version_id')):
                    raise ValueError('Binding changed')
                review=svc.row(db,'literature_claim_reviews',project,bound['review_id'])
                if (review['claim_id']!=claim['claim_id'] or review['claim_revision']!=claim['revision']
                        or review['project_reference_id']!=bound['project_reference_id'] or review['reference_id']!=bound['reference_id']
                        or review['status']!='supported' or review['relevance']!='related' or not review['evidence_ids_json']):
                    raise ValueError('Historical manual support missing')
                if bound['project_reference_id'] in refs:
                    raise ValueError('Duplicate reference')
                refs.add(bound['project_reference_id'])
                if svc.evidence.review_view(db,project,review)!=bound['review']:
                    raise ValueError('Historical review changed')
                evidence=svc.evidence.evidence_by_ids(db,project,claim['claim_id'],claim['revision'],review['project_reference_id'],review['evidence_ids_json'])
                svc.validate_evidence_receipts(db,project,review['project_reference_id'],evidence)
                if evidence!=bound['evidence']:
                    raise ValueError('Historical evidence changed')
                meta=svc.row(db,'literature_citation_metadata_versions',project,bound['metadata_version_id'])
                actual=svc.metadata_view(db,project,meta,verify=True)
                if (not actual['usable'] or actual!=bound['metadata_source'] or actual['metadata']!=bound['metadata']
                        or actual['project_reference_id']!=bound['project_reference_id'] or actual['revision']!=bound['metadata_revision']):
                    raise ValueError('Historical metadata changed')
    if render_paragraphs(snapshot['paragraphs'])!=snapshot['output']:
        raise ValueError('Frozen output differs from frozen sources')


def audit_literature_citations(db):
    services={};checks=[]
    def service(owner):
        if owner not in services:
            services[owner]=LiteratureCitationService(SimpleNamespace(owner_id=owner,db_config=get_database_config(),
                directory=get_data_dir(),original=LocalFileObjects(get_data_dir()).original))
        return services[owner]
    for table in ('literature_citation_metadata_versions','literature_material_confirmations',
                  'literature_citation_drafts','literature_citation_versions'):
        rows=db.execute('SELECT * FROM '+table).fetchall();invalid=0
        for row in rows:
            try:
                svc=service(row['user_id']);project=row['project_id']
                svc.store.require_project(db,project);svc.validate(row)
                if table=='literature_citation_metadata_versions':
                    svc.metadata_actual(db,project,row)
                    versions=svc.rows(db,table,project,' AND project_reference_id=%s',(row['project_reference_id'],))
                    if sorted(r['revision'] for r in versions)!=list(range(1,len(versions)+1)):
                        raise ValueError('Metadata history gap')
                elif table=='literature_material_confirmations':
                    body=MaterialConfirmationRequest.model_validate({k:v for k,v in row['request_json'].items() if k!='material_id'})
                    material=svc.evidence.material_row(db,project,row['material_id'])
                    source,items=svc.evidence.material_actual(project,material)
                    expected=dict(completeness=body.completeness,basis=body.basis,source=source,actual_item_count=len(items),confirmed_by=row['user_id'])
                    if (row['snapshot_json']!=expected or row['revision']!=body.expected_revision+1
                            or row['project_reference_id']!=material['project_reference_id']
                            or row['request_json']['material_id']!=material['id']):
                        raise ValueError('Material confirmation changed')
                    versions=svc.rows(db,table,project,' AND material_id=%s',(material['id'],))
                    if sorted(r['revision'] for r in versions)!=list(range(1,len(versions)+1)):
                        raise ValueError('Confirmation history gap')
                elif table=='literature_citation_drafts':
                    versions=svc.rows(db,'literature_citation_versions',project,' AND draft_id=%s',(row['id'],))
                    if sorted(r['revision'] for r in versions)!=list(range(1,row['revision']+1)):
                        raise ValueError('Draft history gap')
                    first=next(v for v in versions if v['revision']==1)
                    if digest(first['request_json'])!=row['request_digest']:
                        raise ValueError('Draft root request changed')
                else:
                    validate_version(svc,db,row)
            except Exception:
                invalid+=1
        checks.append(dict(table=table,column='owner_history_and_frozen_sources',rows=len(rows),invalid=invalid))
    return checks
