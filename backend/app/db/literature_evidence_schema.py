"""Project-private, append-only claim versions and frozen evidence provenance."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_literature_evidence_tables(metadata):
    def scope():
        return [sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
                sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
                sa.ForeignKeyConstraint(['project_id', 'user_id'], ['projects.id', 'projects.owner_id'])]

    def request():
        return [sa.Column('idempotency_key', sa.Text, nullable=False),
                sa.Column('request_digest', sa.Text, nullable=False), sa.Column('request_json', JSONB, nullable=False),
                sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]

    def constraints(prefix, *, keyed=True):
        result = [sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object'", name=prefix+'_request_check')]
        if keyed:
            result.append(sa.UniqueConstraint('user_id', 'project_id', 'idempotency_key', name=prefix+'_request_key'))
        return result

    def reference(prefix):
        return [sa.Column('project_reference_id', sa.Text, nullable=False), sa.Column('reference_id', sa.Text, nullable=False),
                sa.ForeignKeyConstraint(['project_reference_id', 'project_id', 'user_id', 'reference_id'],
                    ['project_references.id', 'project_references.project_id', 'project_references.user_id', 'project_references.reference_id'], name=prefix+'_reference_fkey')]

    def claim_version(prefix):
        return [sa.Column('claim_id', sa.Text, nullable=False), sa.Column('claim_revision', sa.Integer, nullable=False),
                sa.ForeignKeyConstraint(['claim_id', 'claim_revision', 'project_id', 'user_id'],
                    ['literature_claim_versions.claim_id', 'literature_claim_versions.revision', 'literature_claim_versions.project_id', 'literature_claim_versions.user_id'], name=prefix+'_version_fkey')]

    materials = sa.Table('literature_materials', metadata,
        sa.Column('id', sa.Text, primary_key=True), *scope(), *request(), *reference('literature_materials'),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('source_kind', sa.Text, nullable=False), sa.Column('version_id', sa.Text, nullable=False),
        sa.Column('source_json', JSONB, nullable=False), sa.Column('source_description', sa.Text, nullable=False),
        sa.Column('match_note', sa.Text, nullable=False), *constraints('literature_materials'),
        sa.UniqueConstraint('id', 'project_id', 'user_id', 'project_reference_id', name='literature_materials_scope_key'),
        sa.CheckConstraint("source_kind IN ('document_version','ocr_review_version') AND jsonb_typeof(source_json)='object'", name='literature_materials_source_check'))
    claims = sa.Table('literature_claims', metadata,
        sa.Column('id', sa.Text, primary_key=True), *scope(), *request(),
        sa.Column('revision', sa.Integer, nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        *constraints('literature_claims'), sa.UniqueConstraint('id', 'project_id', 'user_id', name='literature_claims_scope_key'),
        sa.CheckConstraint('revision>=1 AND updated_at>=created_at', name='literature_claims_revision_check'))
    versions = sa.Table('literature_claim_versions', metadata,
        sa.Column('claim_id', sa.Text, primary_key=True), sa.Column('revision', sa.Integer, primary_key=True),
        *scope(), *request(), sa.Column('content', sa.Text, nullable=False), sa.Column('context', sa.Text, nullable=False),
        sa.Column('output_language', sa.Text, nullable=False), *constraints('literature_claim_versions', keyed=False),
        sa.UniqueConstraint('user_id', 'project_id', 'claim_id', 'idempotency_key', name='literature_claim_versions_request_key'),
        sa.UniqueConstraint('claim_id', 'revision', 'project_id', 'user_id', name='literature_claim_versions_scope_key'),
        sa.ForeignKeyConstraint(['claim_id', 'project_id', 'user_id'], ['literature_claims.id', 'literature_claims.project_id', 'literature_claims.user_id'], name='literature_claim_versions_claim_fkey'),
        sa.CheckConstraint("revision>=1 AND length(btrim(content))>0 AND output_language IN ('zh-CN','en')", name='literature_claim_versions_content_check'))
    evidence = sa.Table('literature_claim_evidence', metadata,
        sa.Column('id', sa.Text, primary_key=True), *scope(), *request(), *claim_version('literature_claim_evidence'),
        *reference('literature_claim_evidence'), sa.Column('quote', sa.Text, nullable=False),
        sa.Column('reading_scope', sa.Text, nullable=False), sa.Column('source_json', JSONB, nullable=False),
        sa.Column('location_json', JSONB, nullable=False), sa.Column('snapshot_sha256', sa.Text, nullable=False),
        *constraints('literature_claim_evidence', keyed=False),
        sa.UniqueConstraint('user_id', 'project_id', 'claim_id', 'idempotency_key', name='literature_claim_evidence_request_key'),
        sa.CheckConstraint("length(btrim(quote))>0 AND reading_scope IN ('abstract','user_material','pmc_fulltext') AND jsonb_typeof(source_json)='object' AND jsonb_typeof(location_json)='object' AND snapshot_sha256 ~ '^[0-9a-f]{64}$'", name='literature_claim_evidence_source_check'))
    reviews = sa.Table('literature_claim_reviews', metadata,
        sa.Column('id', sa.Text, primary_key=True), *scope(), *request(), *claim_version('literature_claim_reviews'),
        *reference('literature_claim_reviews'), sa.Column('evidence_ids_json', JSONB, nullable=False),
        sa.Column('status', sa.Text, nullable=False), sa.Column('relevance', sa.Text, nullable=False),
        sa.Column('reason', sa.Text, nullable=False), sa.Column('narrowed_statement', sa.Text, nullable=False),
        sa.Column('limitations', sa.Text, nullable=False), sa.Column('decided_by', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        *constraints('literature_claim_reviews', keyed=False),
        sa.UniqueConstraint('user_id', 'project_id', 'claim_id', 'idempotency_key', name='literature_claim_reviews_request_key'),
        sa.CheckConstraint("status IN ('supported','partial','unsupported','needs_review') AND relevance IN ('related','unrelated','uncertain') AND jsonb_typeof(evidence_ids_json)='array'", name='literature_claim_reviews_status_check'),
        sa.CheckConstraint("(status='needs_review' OR jsonb_array_length(evidence_ids_json)>0) AND ((status <> 'supported' AND status <> 'partial') OR relevance='related') AND (status <> 'partial' OR length(btrim(narrowed_statement))>0) AND decided_by=user_id", name='literature_claim_reviews_decision_check'))
    supplements = sa.Table('literature_claim_supplements', metadata,
        *scope(), *request(), *claim_version('literature_claim_supplements'),
        sa.Column('task_id', sa.Text, sa.ForeignKey('literature_searches.task_id'), nullable=False, unique=True),
        sa.ForeignKeyConstraint(['task_id', 'project_id', 'user_id'], ['literature_searches.task_id', 'literature_searches.project_id', 'literature_searches.user_id'], name='literature_claim_supplements_search_fkey'),
        sa.Column('round', sa.Integer, nullable=False), sa.Column('candidate_limit', sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint('claim_id', name='literature_claim_supplements_pkey'),
        *constraints('literature_claim_supplements', keyed=False),
        sa.CheckConstraint('round=1 AND candidate_limit=20', name='literature_claim_supplements_limit_check'))
    for table in (materials, claims, evidence, reviews):
        sa.Index(table.name+'_project_created', table.c.project_id, table.c.created_at.desc(), table.c.id)
    return materials, claims, versions, evidence, reviews, supplements
