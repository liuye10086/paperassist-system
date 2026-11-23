"""Owner-scoped notes on original paper figures and tables."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY


def define_paper_material_notes(metadata, *, include_worksheet_names=True, allow_empty_result=True):
    return sa.Table(
        'paper_material_notes', metadata,
        sa.Column('project_id', sa.Text, primary_key=True),
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('owner_id', sa.Text, nullable=False),
        sa.Column('file_id', sa.Text, nullable=False),
        sa.Column('revision', sa.Integer, nullable=False),
        sa.Column('result_text', sa.Text, nullable=False),
        sa.Column('target_id', sa.Text),
        sa.Column('target_label', sa.Text),
        *([sa.Column('worksheet_names', ARRAY(sa.Text))] if include_worksheet_names else []),
        sa.UniqueConstraint('file_id', name='paper_material_notes_file_key'),
        sa.ForeignKeyConstraint(
            ['project_id', 'owner_id'], ['projects.id', 'projects.owner_id'],
            name='paper_material_notes_owner_fk',
        ),
        sa.ForeignKeyConstraint(
            ['file_id', 'project_id'], ['files.id', 'files.project_id'],
            name='paper_material_notes_file_fk',
        ),
        sa.CheckConstraint('revision >= 1', name='paper_material_notes_revision_check'),
        sa.CheckConstraint(
            "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name='paper_material_notes_id_check',
        ),
        sa.CheckConstraint(
            f'length(result_text) BETWEEN {0 if allow_empty_result else 1} AND 20000 AND result_text = btrim(result_text)',
            name='paper_material_notes_result_check',
        ),
        sa.CheckConstraint(
            '(target_id IS NULL AND target_label IS NULL) OR '
            '(target_id IS NOT NULL AND length(target_id) BETWEEN 1 AND 400 '
            'AND target_label IS NOT NULL AND length(target_label) BETWEEN 1 AND 500)',
            name='paper_material_notes_target_check',
        ),
    )
