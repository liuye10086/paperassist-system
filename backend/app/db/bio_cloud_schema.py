"""Project-scoped cloud receipts; scheduling remains in tasks/outbox."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.db.research_intake_schema import scoped_fk

TABLE_NAMES = ('bio_cloud_uploads', 'bio_cloud_parts', 'bio_cloud_runs', 'bio_cloud_run_inputs', 'bio_cloud_outputs')


def define_bio_cloud_tables(metadata):
    uploads = sa.Table('bio_cloud_uploads', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('owner_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        *(sa.Column(k, sa.Text, nullable=False) for k in ('request_key', 'request_digest', 'filename', 'region', 'bucket', 'object_key', 'status')),
        sa.Column('size_bytes', sa.BigInteger, nullable=False),
        sa.Column('provider_upload_id', sa.Text), sa.Column('error_code', sa.Text),
        sa.Column('receipt_json', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id', 'project_id', name='bio_cloud_upload_scope'),
        sa.UniqueConstraint('project_id', 'request_key', name='bio_cloud_upload_request'),
        sa.UniqueConstraint('region', 'bucket', 'object_key', name='bio_cloud_upload_object'),
        sa.CheckConstraint("size_bytes>0 AND size_bytes<=127775277056 AND request_digest ~ '^[0-9a-f]{64}$'", name='bio_cloud_upload_size'),
        sa.CheckConstraint("status IN ('initializing','uploading','completing','completed','cancelling','cancelled','failed','initialization_unknown')", name='bio_cloud_upload_state'))
    parts = sa.Table('bio_cloud_parts', metadata,
        sa.Column('upload_id', sa.Text, sa.ForeignKey('bio_cloud_uploads.id'), primary_key=True),
        sa.Column('part_number', sa.Integer, primary_key=True),
        sa.Column('checksum_sha256', sa.Text, nullable=False),
        sa.CheckConstraint("part_number BETWEEN 1 AND 10000 AND length(checksum_sha256)=44", name='bio_cloud_part_check'))
    runs = sa.Table('bio_cloud_runs', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('task_id', sa.Text, nullable=False),
        *(sa.Column(k, sa.Text, nullable=False) for k in ('request_key', 'request_digest', 'request_token', 'status')),
        sa.Column('snapshot_json', JSONB, nullable=False),
        sa.Column('output_manifest_json', JSONB),
        sa.Column('provider_run_id', sa.Text), sa.Column('provider_state', sa.Text),
        sa.Column('run_output_uri', sa.Text), sa.Column('error_code', sa.Text),
        sa.Column('cancel_requested', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('submitted_at', sa.DateTime(timezone=True)),
        sa.Column('poll_failures', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id', 'project_id', name='bio_cloud_run_scope'),
        sa.UniqueConstraint('project_id', 'request_key', name='bio_cloud_run_request'),
        sa.UniqueConstraint('task_id', name='bio_cloud_run_task'),
        sa.UniqueConstraint('request_token', name='bio_cloud_run_token'),
        scoped_fk(['task_id', 'project_id'], ['tasks.id', 'tasks.project_id'], 'bio_cloud_task_scope'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=1048576", name='bio_cloud_run_snapshot'),
        sa.CheckConstraint("status IN ('queued','submitting','submission_unknown','pending','running','cancelling','cancelled','collecting','completed','failed','blocked')", name='bio_cloud_run_state'))
    sa.Index('bio_cloud_runs_project', runs.c.project_id, runs.c.created_at.desc())
    inputs = sa.Table('bio_cloud_run_inputs', metadata,
        sa.Column('run_id', sa.Text, primary_key=True), sa.Column('upload_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        scoped_fk(['run_id','project_id'], ['bio_cloud_runs.id','bio_cloud_runs.project_id'], 'bio_cloud_input_run'),
        scoped_fk(['upload_id','project_id'], ['bio_cloud_uploads.id','bio_cloud_uploads.project_id'], 'bio_cloud_input_upload'))
    outputs = sa.Table('bio_cloud_outputs', metadata,
        sa.Column('run_id', sa.Text, primary_key=True), sa.Column('role', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False), sa.Column('file_id', sa.Text, nullable=False),
        sa.Column('source_key', sa.Text, nullable=False),
        sa.Column('sha256', sa.Text, nullable=False), sa.Column('size_bytes', sa.BigInteger, nullable=False),
        scoped_fk(['run_id','project_id'], ['bio_cloud_runs.id','bio_cloud_runs.project_id'], 'bio_cloud_output_run'),
        scoped_fk(['file_id','project_id'], ['files.id','files.project_id'], 'bio_cloud_output_file'))
    return uploads, parts, runs, inputs, outputs
