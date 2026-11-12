"""Persistence for registration submissions and their review audit."""

import sqlalchemy as sa


REVIEW_AUDIT_STATE = """(
    (before_review_status IS NULL AND after_review_status IS NULL AND after_role IS NOT NULL)
    OR (
        source='web' AND before_review_status='pending' AND before_role IS NULL AND before_active=false
        AND (
            (after_review_status='approved' AND after_role IS NOT NULL AND after_active)
            OR (after_review_status='rejected' AND after_role IS NULL AND NOT after_active)
        )
    )
) IS TRUE"""


def define_registration_tables(metadata):
    registrations = sa.Table(
        'account_registrations', metadata,
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('display_name', sa.Text, nullable=False),
        sa.Column('organization', sa.Text, nullable=False),
        sa.Column('note', sa.Text, nullable=False),
        sa.CheckConstraint(
            'length(btrim(display_name)) BETWEEN 1 AND 80 AND length(organization)<=160 AND length(note)<=1000',
            name='account_registration_fields',
        ),
    )
    attempts = sa.Table(
        'auth_registration_attempts', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('client_ip', sa.Text, nullable=False),
        sa.Column('attempted_at', sa.Double, nullable=False),
    )
    sa.Index('auth_registration_attempts_ip_time', attempts.c.client_ip, attempts.c.attempted_at)
    return registrations, attempts
