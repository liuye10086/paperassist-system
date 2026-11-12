"""Store account applications and preserve registration decisions in the audit."""

from alembic import op
import sqlalchemy as sa

from app.db.account_registration_schema import REVIEW_AUDIT_STATE, define_registration_tables


revision = '0076_account_registration'
down_revision = '0075_account_roles'
branch_labels = depends_on = None


def _replace_audit_roles(*, allow_unassigned):
    after = "after_role IN ('user','admin','customer','analyst')"
    if allow_unassigned:
        after = f'(after_role IS NULL OR {after})'
    op.drop_constraint('admin_audit_values', 'admin_audit_events', type_='check')
    op.create_check_constraint(
        'admin_audit_values', 'admin_audit_events',
        f"source IN ('web','cli') AND {after} AND (before_role IS NULL OR before_role IN ('user','admin','customer','analyst'))",
    )


def upgrade():
    metadata = sa.MetaData()
    sa.Table('users', metadata, sa.Column('id', sa.Text, primary_key=True))
    for table in define_registration_tables(metadata):
        table.create(op.get_bind())
    op.add_column('admin_audit_events', sa.Column('before_review_status', sa.Text))
    op.add_column('admin_audit_events', sa.Column('after_review_status', sa.Text))
    op.alter_column('admin_audit_events', 'after_role', existing_type=sa.Text(), nullable=True)
    _replace_audit_roles(allow_unassigned=True)
    op.create_check_constraint('admin_audit_review_state', 'admin_audit_events', REVIEW_AUDIT_STATE)


def downgrade():
    has_registration_history = op.get_bind().exec_driver_sql("""
        SELECT EXISTS (SELECT 1 FROM account_registrations)
            OR EXISTS (SELECT 1 FROM admin_audit_events WHERE after_review_status IS NOT NULL)
    """).scalar_one()
    if has_registration_history:
        raise RuntimeError('Registration applications or review history exist; downgrade would lose information.')
    op.drop_constraint('admin_audit_review_state', 'admin_audit_events', type_='check')
    _replace_audit_roles(allow_unassigned=False)
    op.alter_column('admin_audit_events', 'after_role', existing_type=sa.Text(), nullable=False)
    op.drop_column('admin_audit_events', 'after_review_status')
    op.drop_column('admin_audit_events', 'before_review_status')
    op.drop_table('auth_registration_attempts')
    op.drop_table('account_registrations')
