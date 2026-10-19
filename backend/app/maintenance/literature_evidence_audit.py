"""Read-only validation of all historical claim versions and actual source objects."""
from types import SimpleNamespace
from app.core.config import get_data_dir
from app.db.database import get_database_config
from app.domain.literature_evidence.service import LiteratureEvidenceService, validate_request_row
from app.domain.literature_evidence.contracts import ClaimRequest, ClaimVersionRequest
from app.adapters.file_objects import LocalFileObjects
from app.domain.literature.contracts import SearchRequest


def audit_literature_evidence(db):
    checks = []
    services = {}

    def service(owner):
        if owner not in services:
            services[owner] = LiteratureEvidenceService(SimpleNamespace(owner_id=owner,
                db_config=get_database_config(), directory=get_data_dir(), original=LocalFileObjects(get_data_dir()).original))
        return services[owner]

    for table in ('literature_materials', 'literature_claims', 'literature_claim_versions',
                  'literature_claim_evidence', 'literature_claim_reviews', 'literature_claim_supplements'):
        rows = db.execute('SELECT * FROM '+table).fetchall()
        invalid = 0
        for row in rows:
            try:
                svc = service(row['user_id'])
                svc.store.require_project(db, row['project_id'])
                validate_request_row(row)
                if table == 'literature_materials':
                    svc.material_view(row['project_id'], svc.material_row(db, row['project_id'], row['id']))
                elif table == 'literature_claims':
                    model = ClaimRequest.model_validate(row['request_json'])
                    _, root = svc.claim_row(db, row['project_id'], row['id'], 1)
                    svc.claim_row(db, row['project_id'], row['id'])
                    count = db.execute('SELECT count(*) AS n FROM literature_claim_versions WHERE claim_id=%s', (row['id'],)).fetchone()['n']
                    if count != row['revision'] or any(root[k] != getattr(model, k) for k in ('content','context','output_language')):
                        raise ValueError('Claim version chain differs')
                elif table == 'literature_claim_versions':
                    model = ClaimRequest if row['revision']==1 else ClaimVersionRequest
                    request = model.model_validate(row['request_json'])
                    if row['revision']>1 and request.expected_revision+1 != row['revision']:
                        raise ValueError('Claim predecessor differs')
                    svc.claim_row(db, row['project_id'], row['claim_id'], row['revision'])
                elif table == 'literature_claim_evidence':
                    svc.evidence_view(db, row['project_id'], row)
                elif table == 'literature_claim_reviews':
                    svc.review_view(db, row['project_id'], row)
                else:
                    _, version = svc.claim_row(db, row['project_id'], row['claim_id'], row['claim_revision'])
                    task, search = svc.literature.require_search(db, row['project_id'], row['task_id'])
                    # Preserve the original supplement request/digest for historical replays;
                    # compare its query using the ordinary search contract's normalization.
                    expected_query = SearchRequest.model_validate(dict(search['input_json'],
                        query=row['request_json']['query'])).query
                    if (task['idempotency_key'] != 'claim-supplement:'+row['claim_id'] or row['round']!=1
                        or row['candidate_limit']!=20 or search['input_json']['limit']!=20
                        or search['input_json']['output_language'] != version['output_language']
                        or search['input_json']['source_context']['text'] != version['content']
                        or search['input_json']['query'] != expected_query
                        or row['claim_revision'] != row['request_json']['claim_revision']):
                        raise ValueError('Supplement scope differs')
            except Exception:
                invalid += 1
        checks.append(dict(table=table, column='owner_version_and_actual_source', rows=len(rows), invalid=invalid))
    return checks
