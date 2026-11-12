"""Current delegation and append-only administrator history."""

import sqlalchemy as sa


def define_project_assignment_tables(metadata):
    assignments = sa.Table(
        'project_assignments', metadata,
        sa.Column('project_id', sa.Text, primary_key=True),
        sa.Column('owner_id', sa.Text, nullable=False),
        sa.Column('analyst_id', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('revision', sa.BigInteger, nullable=False),
        sa.Column('updated_by', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.ForeignKeyConstraint(['project_id', 'owner_id'], ['projects.id', 'projects.owner_id'],
                                name='project_assignment_owner_fk'),
        sa.CheckConstraint('revision > 0', name='project_assignment_revision'),
        sa.CheckConstraint('analyst_id IS DISTINCT FROM owner_id', name='project_assignment_distinct_analyst'),
    )
    sa.Index('project_assignment_analyst', assignments.c.analyst_id, assignments.c.project_id,
             postgresql_where=assignments.c.analyst_id.is_not(None))

    sa.Table(
        'project_assignment_events', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.Column('owner_id', sa.Text, nullable=False),
        sa.Column('revision', sa.BigInteger, nullable=False),
        sa.Column('actor_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('actor_email', sa.Text, nullable=False),
        sa.Column('previous_analyst_id', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('previous_analyst_email', sa.Text),
        sa.Column('analyst_id', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('analyst_email', sa.Text),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id', 'owner_id'], ['projects.id', 'projects.owner_id'],
                                name='project_assignment_event_owner_fk'),
        sa.UniqueConstraint('project_id', 'revision', name='project_assignment_event_revision_key'),
        sa.CheckConstraint('revision > 0', name='project_assignment_event_revision'),
        sa.CheckConstraint('length(btrim(reason)) BETWEEN 5 AND 500', name='project_assignment_event_reason'),
        sa.CheckConstraint('previous_analyst_id IS DISTINCT FROM analyst_id', name='project_assignment_event_change'),
        sa.CheckConstraint('(previous_analyst_id IS NULL) = (previous_analyst_email IS NULL) '
                           'AND (analyst_id IS NULL) = (analyst_email IS NULL)', name='project_assignment_event_emails'),
    )
