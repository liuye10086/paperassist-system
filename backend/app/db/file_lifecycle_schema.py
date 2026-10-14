"""Append-only lifecycle receipts; existing lineage remains the source of truth."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

SCOPE_FUNCTION_BODY = """DECLARE actor text; BEGIN
  IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'lifecycle history is immutable'; END IF;
  IF TG_TABLE_NAME='file_deletion_requests' THEN actor:=NEW.requested_by; ELSE actor:=NEW.actor_id; END IF;
  IF NOT EXISTS (SELECT 1 FROM files f JOIN projects p ON p.id=f.project_id
    WHERE f.id=NEW.file_id AND p.id=NEW.project_id AND p.owner_id=actor)
  THEN RAISE EXCEPTION 'lifecycle scope mismatch'; END IF;
  IF TG_TABLE_NAME='file_reparse_assessments' THEN
    IF NOT EXISTS (SELECT 1 FROM tasks t WHERE t.id=NEW.task_id AND t.project_id=NEW.project_id
      AND t.user_id=actor AND t.task_type IN ('parse_file','extract_dataset')
      AND t.input_snapshot->'file'->>'id'=NEW.file_id)
    THEN RAISE EXCEPTION 'lifecycle task scope mismatch'; END IF;
  END IF;
  RETURN NEW;
END"""


def define_file_lifecycle_tables(metadata):
    deletion = sa.Table('file_deletion_requests', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('requested_by', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.Text, nullable=False),
        sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('policy_version', sa.Text, nullable=False),
        sa.Column('assessment_revision', sa.Text, nullable=False),
        sa.Column('assessment_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('requested_by', 'project_id', 'file_id', 'idempotency_key', name='file_deletion_request_key'),
        sa.CheckConstraint("status IN ('retained','blocked')", name='file_deletion_status_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'", name='file_deletion_request_check'),
        sa.CheckConstraint("length(reason)>=1 AND length(reason)<=500 AND reason=btrim(reason)", name='file_deletion_reason_check'),
        sa.CheckConstraint("assessment_revision ~ '^[0-9a-f]{64}$' AND policy_version='internal_testing_keep_v1' AND jsonb_typeof(assessment_json)='object'", name='file_deletion_assessment_check'),
        sa.CheckConstraint('resolved_at=created_at', name='file_deletion_terminal_check'))
    sa.Index('file_deletion_file_created', deletion.c.file_id, deletion.c.created_at.desc(), deletion.c.id)
    reparse = sa.Table('file_reparse_assessments', metadata,
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), primary_key=True),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('actor_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('policy_version', sa.Text, nullable=False),
        sa.Column('assessment_revision', sa.Text, nullable=False),
        sa.Column('client_assessment_supplied', sa.Boolean, nullable=False),
        sa.Column('snapshot_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("assessment_revision ~ '^[0-9a-f]{64}$' AND policy_version='internal_testing_keep_v1' AND jsonb_typeof(snapshot_json)='object'", name='file_reparse_assessment_check'))
    return deletion, reparse
