"""Immutable provenance and request receipts for saved analysis artifacts."""

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Table, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB


def define_delivery_artifact_sources(metadata):
    return Table(
        'delivery_artifact_sources', metadata,
        Column('file_id', Text, primary_key=True),
        Column('project_id', Text, nullable=False),
        Column('actor_id', Text, ForeignKey('users.id'), nullable=False),
        Column('assignment_revision', BigInteger, nullable=False),
        Column('request_key', Text, nullable=False),
        Column('request_digest', Text, nullable=False),
        Column('provenance_json', JSONB, nullable=False),
        Column('provenance_sha256', Text, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
        ForeignKeyConstraint(['file_id', 'project_id'], ['files.id', 'files.project_id'],
                             name='delivery_artifact_file_scope_fk'),
        UniqueConstraint('project_id', 'actor_id', 'request_key', name='delivery_artifact_request_key'),
        CheckConstraint('assignment_revision > 0', name='delivery_artifact_assignment_revision'),
        CheckConstraint('length(request_key) BETWEEN 1 AND 128', name='delivery_artifact_request_key_length'),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND provenance_sha256 ~ '^[0-9a-f]{64}$'",
                        name='delivery_artifact_digests'),
        CheckConstraint("jsonb_typeof(provenance_json) = 'object'", name='delivery_artifact_provenance'),
    )
