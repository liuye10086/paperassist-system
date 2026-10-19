"""Project-private material, quote and manual decision routes."""
from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store, Key, Page
from app.domain.literature_evidence.contracts import (ClaimRequest, ClaimVersionRequest,
    MaterialRequest, QuoteRequest, ReviewRequest, SupplementRequest)
from app.domain.literature_evidence.service import LiteratureEvidenceService

router = APIRouter(prefix='/api/v1/projects/{project_id}/literature/evidence', tags=['文献论述与证据'])


@router.get('/config')
def config(project_id: str, store: Store):
    return LiteratureEvidenceService(store).config(project_id)


@router.get('/material-options')
def material_options(project_id: str, store: Store, page: Page = 1):
    return LiteratureEvidenceService(store).material_options(project_id, page)


@router.post('/materials', status_code=201)
def create_material(project_id: str, request: MaterialRequest, response: Response, store: Store, idempotency_key: Key):
    view, response.status_code = LiteratureEvidenceService(store).create_material(project_id, request, idempotency_key)
    return view


@router.get('/materials')
def materials(project_id: str, store: Store, page: Page = 1, project_reference_id: str | None = None):
    return LiteratureEvidenceService(store).materials(project_id, page, project_reference_id)


@router.get('/materials/{material_id}/source')
def material_source(project_id: str, material_id: str, store: Store, page: Page = 1):
    return LiteratureEvidenceService(store).material_source(project_id, material_id, page)


@router.post('/claims', status_code=201)
def create_claim(project_id: str, request: ClaimRequest, response: Response, store: Store, idempotency_key: Key):
    view, response.status_code = LiteratureEvidenceService(store).create_claim(project_id, request, idempotency_key)
    return view


@router.get('/claims')
def claims(project_id: str, store: Store, page: Page = 1):
    return LiteratureEvidenceService(store).claims(project_id, page)


@router.get('/claims/{claim_id}')
def claim(project_id: str, claim_id: str, store: Store, revision: Page | None = None):
    return LiteratureEvidenceService(store).claim(project_id, claim_id, revision)


@router.post('/claims/{claim_id}/versions', status_code=201)
def version_claim(project_id: str, claim_id: str, request: ClaimVersionRequest, response: Response, store: Store, idempotency_key: Key):
    view, response.status_code = LiteratureEvidenceService(store).version_claim(project_id, claim_id, request, idempotency_key)
    return view


@router.post('/claims/{claim_id}/evidence', status_code=201)
def create_evidence(project_id: str, claim_id: str, request: QuoteRequest, response: Response, store: Store, idempotency_key: Key):
    view, response.status_code = LiteratureEvidenceService(store).create_evidence(project_id, claim_id, request, idempotency_key)
    return view


@router.get('/claims/{claim_id}/evidence')
def evidence(project_id: str, claim_id: str, store: Store, page: Page = 1, revision: Page | None = None):
    return LiteratureEvidenceService(store).history(project_id, claim_id, revision, page)


@router.post('/claims/{claim_id}/reviews', status_code=201)
def create_review(project_id: str, claim_id: str, request: ReviewRequest, response: Response, store: Store, idempotency_key: Key):
    view, response.status_code = LiteratureEvidenceService(store).create_review(project_id, claim_id, request, idempotency_key)
    return view


@router.get('/claims/{claim_id}/reviews')
def reviews(project_id: str, claim_id: str, store: Store, page: Page = 1, revision: Page | None = None):
    return LiteratureEvidenceService(store).history(project_id, claim_id, revision, page, reviews=True)


@router.post('/claims/{claim_id}/supplement', status_code=202)
def supplement(project_id: str, claim_id: str, request: SupplementRequest, response: Response, store: Store, idempotency_key: Key):
    view, response.status_code = LiteratureEvidenceService(store).supplement(project_id, claim_id, request, idempotency_key)
    return view
