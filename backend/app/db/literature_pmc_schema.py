"""Project-private immutable OAI acquisition history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_literature_pmc_tables(metadata):
    table=sa.Table('literature_pmc_receipts',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),
        sa.Column('user_id',sa.Text,nullable=False),sa.Column('project_reference_id',sa.Text,nullable=False),
        sa.Column('reference_id',sa.Text,nullable=False),sa.Column('pmcid',sa.Text,nullable=False),
        sa.Column('pmid',sa.Text,nullable=False),sa.Column('source_kind',sa.Text,nullable=False),
        sa.Column('status',sa.Text,nullable=False),sa.Column('idempotency_key',sa.Text,nullable=False),
        sa.Column('request_digest',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),
        sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='lpmc_owner_fkey'),
        sa.ForeignKeyConstraint(['project_reference_id','project_id','user_id','reference_id'],
            ['project_references.id','project_references.project_id','project_references.user_id','project_references.reference_id'],name='lpmc_reference_fkey'),
        sa.UniqueConstraint('user_id','project_id','idempotency_key',name='lpmc_request_key'),
        sa.CheckConstraint("pmcid ~ '^PMC[1-9][0-9]{0,11}$' AND pmid ~ '^[1-9][0-9]{0,11}$' AND source_kind IN ('pmc_oai','synthetic_fixture')",name='lpmc_identity_check'),
        sa.CheckConstraint("status IN ('succeeded','pmc_xml_invalid','pmc_record_unavailable','pmc_identity_mismatch','pmc_license_denied','pmc_body_missing','pmc_http_failed','pmc_request_failed','pmc_response_too_large')",name='lpmc_status_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='lpmc_snapshot_check'))
    sa.Index('literature_pmc_receipts_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return (table,)
