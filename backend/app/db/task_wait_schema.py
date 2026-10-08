"""Persisted waiting generations and accepted user recovery requests."""
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Integer, Table, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB


def define_task_wait_tables(metadata):
    waits = Table('task_waits', metadata,
        Column('id', Text, primary_key=True),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('project_id', Text, ForeignKey('projects.id'), nullable=False),
        Column('kind', Text, nullable=False), Column('status', Text, nullable=False),
        Column('task_revision', Integer, nullable=False), Column('input_version', JSONB, nullable=False),
        Column('reason_code', Text), Column('error_code', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('resolved_at', DateTime(timezone=True)), Column('resolved_task_revision', Integer),
        UniqueConstraint('task_id', 'task_revision', name='task_waits_generation_key'),
        UniqueConstraint('task_id', 'id', name='task_waits_task_id_key'),
        CheckConstraint("kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation')", name='task_waits_kind_check'),
        CheckConstraint("status IN ('open','resolved','superseded')", name='task_waits_status_check'),
        CheckConstraint('task_revision >= 1', name='task_waits_revision_check'),
        CheckConstraint("jsonb_typeof(input_version) = 'object'", name='task_waits_input_object_check'),
        CheckConstraint("(status='open' AND resolved_at IS NULL AND resolved_task_revision IS NULL) OR (status<>'open' AND resolved_at IS NOT NULL AND resolved_task_revision IS NOT NULL AND resolved_at>=created_at AND resolved_task_revision>task_revision)", name='task_waits_resolution_check'))
    Index('task_waits_one_open', waits.c.task_id, unique=True, postgresql_where=text("status='open'"))
    Index('task_waits_owner_status', waits.c.user_id, waits.c.status, waits.c.created_at)
    requests = Table('task_resume_requests', metadata,
        Column('id', Text, primary_key=True),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('idempotency_key', Text, nullable=False), Column('operation', Text, nullable=False),
        Column('wait_id', Text), Column('request_digest', Text, nullable=False),
        Column('expected_task_revision', Integer, nullable=False), Column('input_version', JSONB, nullable=False),
        Column('result_task_revision', Integer, nullable=False), Column('response_json', JSONB, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(['task_id', 'wait_id'], ['task_waits.task_id', 'task_waits.id'], name='task_resume_requests_wait_fkey'),
        UniqueConstraint('user_id', 'task_id', 'idempotency_key', name='task_resume_requests_idempotency_key'),
        CheckConstraint("operation IN ('resume','retry')", name='task_resume_requests_operation_check'),
        CheckConstraint("(operation='resume' AND wait_id IS NOT NULL) OR (operation='retry' AND wait_id IS NULL)", name='task_resume_requests_wait_check'),
        CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$'", name='task_resume_requests_key_check'),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name='task_resume_requests_digest_check'),
        CheckConstraint('expected_task_revision >= 1 AND result_task_revision=expected_task_revision+1', name='task_resume_requests_revision_check'),
        CheckConstraint("jsonb_typeof(input_version)='object' AND jsonb_typeof(response_json)='object'", name='task_resume_requests_json_check'))
    return waits, requests
