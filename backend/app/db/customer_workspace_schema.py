"""Published snapshots, confirmed-version progress and customer feedback."""

import sqlalchemy as sa


PROGRESS_STATUSES = ('pending_assignment', 'analyzing', 'needs_materials')
SUBMITTED_STATUSES = PROGRESS_STATUSES + ('materials_submitted',)


def status_check(statuses):
    return 'status IN (' + ','.join(f"'{value}'" for value in statuses) + ')'


def define_customer_workspace_tables(metadata, *, include_assignment_revision=False, include_materials_submitted=False):
    publications = sa.Table(
        'customer_delivery_publications', metadata,
        sa.Column('snapshot_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.Column('delivery_id', sa.Text, nullable=False),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.ForeignKeyConstraint(
            ['snapshot_id', 'delivery_id', 'project_id'],
            ['delivery_snapshots.id', 'delivery_snapshots.delivery_id', 'delivery_snapshots.project_id'],
            name='customer_publication_snapshot_fk',
        ),
        sa.UniqueConstraint('snapshot_id', 'project_id', name='customer_publication_scope'),
        sa.CheckConstraint('length(btrim(title)) BETWEEN 1 AND 200', name='customer_publication_title'),
    )
    sa.Index('customer_publication_project', publications.c.project_id, publications.c.published_at.desc())

    progress = sa.Table(
        'customer_requirement_progress', metadata,
        sa.Column('requirement_version_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('note', sa.Text),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.ForeignKeyConstraint(
            ['requirement_version_id', 'project_id'],
            ['research_requirement_versions.id', 'research_requirement_versions.project_id'],
            name='customer_progress_requirement_fk',
        ),
        sa.CheckConstraint(status_check(SUBMITTED_STATUSES if include_materials_submitted else PROGRESS_STATUSES),
                           name='customer_progress_status'),
        sa.CheckConstraint('note IS NULL OR length(note)<=4000', name='customer_progress_note'),
    )
    if include_assignment_revision:
        progress.append_column(sa.Column('assignment_revision', sa.BigInteger))
        progress.append_constraint(sa.CheckConstraint('assignment_revision > 0', name='customer_progress_assignment_revision'))

    feedback = sa.Table(
        'customer_feedback', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('snapshot_id', sa.Text),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('request_key', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.ForeignKeyConstraint(
            ['snapshot_id', 'project_id'],
            ['customer_delivery_publications.snapshot_id', 'customer_delivery_publications.project_id'],
            name='customer_feedback_publication_fk',
        ),
        sa.UniqueConstraint('project_id', 'user_id', 'request_key', name='customer_feedback_request'),
        sa.CheckConstraint('length(btrim(message)) BETWEEN 1 AND 4000', name='customer_feedback_message'),
        sa.CheckConstraint('length(request_key) BETWEEN 1 AND 128', name='customer_feedback_request_key'),
    )
    sa.Index('customer_feedback_scope', feedback.c.project_id, feedback.c.user_id, feedback.c.snapshot_id,
             feedback.c.created_at, feedback.c.id)
    return publications, progress, feedback


def define_material_submission_tables(metadata):
    submissions = sa.Table(
        'customer_material_submissions', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.Column('requirement_version_id', sa.Text, nullable=False),
        sa.Column('assignment_revision', sa.BigInteger),
        sa.Column('user_id', sa.Text, nullable=False),
        sa.Column('request_key', sa.Text, nullable=False),
        sa.Column('note', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.ForeignKeyConstraint(['project_id', 'user_id'], ['projects.id', 'projects.owner_id'],
                                name='customer_submission_owner_fk'),
        sa.ForeignKeyConstraint(
            ['requirement_version_id', 'project_id'],
            ['research_requirement_versions.id', 'research_requirement_versions.project_id'],
            name='customer_submission_requirement_fk',
        ),
        sa.UniqueConstraint('id', 'project_id', name='customer_submission_scope'),
        sa.UniqueConstraint('project_id', 'user_id', 'request_key', name='customer_submission_request'),
        sa.CheckConstraint('note IS NULL OR length(note)<=4000', name='customer_submission_note'),
        sa.CheckConstraint('length(request_key) BETWEEN 1 AND 128', name='customer_submission_request_key'),
        sa.CheckConstraint('assignment_revision > 0', name='customer_submission_assignment_revision'),
    )
    sa.Index('customer_submission_requirement', submissions.c.requirement_version_id, submissions.c.created_at.desc())
    files = sa.Table(
        'customer_material_submission_files', metadata,
        sa.Column('submission_id', sa.Text, primary_key=True),
        sa.Column('file_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.ForeignKeyConstraint(['submission_id', 'project_id'],
                                ['customer_material_submissions.id', 'customer_material_submissions.project_id'],
                                name='customer_submission_file_parent_fk'),
        sa.ForeignKeyConstraint(['file_id', 'project_id'], ['files.id', 'files.project_id'],
                                name='customer_submission_file_fk'),
    )
    sa.Index('customer_submission_file', files.c.file_id)
    return submissions, files
