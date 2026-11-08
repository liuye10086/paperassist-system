"""Append-only request aliases; scientific inputs and state stay on their targets."""
import sqlalchemy as sa


def define_analysis_request_receipts(metadata):
    table=sa.Table('analysis_request_receipts',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),
        sa.Column('kind',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),
        sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('target_id',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id']),
        sa.UniqueConstraint('user_id','project_id','kind','request_key',name='analysis_receipt_request_key'),
        sa.CheckConstraint("kind IN ('bio_analysis_run','bio_insight_run','research_report')",name='analysis_receipt_kind'),
        sa.CheckConstraint('length(request_key) BETWEEN 1 AND 128',name='analysis_receipt_key'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'",name='analysis_receipt_digest'),
        sa.CheckConstraint('length(target_id) BETWEEN 1 AND 64',name='analysis_receipt_target'))
    sa.Index('analysis_receipt_target_scope',table.c.project_id,table.c.kind,table.c.target_id)
    return table
