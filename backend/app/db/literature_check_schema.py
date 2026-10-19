"""Only independent frozen check receipts; no mutations of retrieval history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_literature_check_tables(metadata):
    table=sa.Table('literature_check_receipts',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('project_reference_id',sa.Text,nullable=False),sa.Column('reference_id',sa.Text,nullable=False),
        sa.Column('search_id',sa.Text,nullable=False),sa.Column('receipt_id',sa.Text,nullable=False),
        sa.Column('kind',sa.Text,nullable=False),sa.Column('source_kind',sa.Text,nullable=False),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('request_json',JSONB,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),
        sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='lcheck_owner_fkey'),
        sa.ForeignKeyConstraint(['project_reference_id','project_id','user_id','reference_id'],
            ['project_references.id','project_references.project_id','project_references.user_id','project_references.reference_id'],name='lcheck_reference_fkey'),
        sa.ForeignKeyConstraint(['receipt_id','search_id','project_id','user_id'],
            ['literature_fetch_receipts.id','literature_fetch_receipts.task_id','literature_fetch_receipts.project_id','literature_fetch_receipts.user_id'],name='lcheck_source_fkey'),
        sa.UniqueConstraint('user_id','project_id','idempotency_key',name='lcheck_request_key'),
        sa.CheckConstraint("kind IN ('saved_record','doi_resolution') AND source_kind IN ('ncbi_eutilities','synthetic_fixture')",name='lcheck_kind_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='lcheck_snapshot_check'))
    sa.Index('literature_check_receipts_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return (table,)
