"""Add account roles and an independent registration review status."""

from alembic import op
import sqlalchemy as sa


revision = '0075_account_roles'
down_revision = '0074_tabular_import_file_limit'
branch_labels = depends_on = None


def _replace_audit_roles(roles):
    op.drop_constraint('admin_audit_values', 'admin_audit_events', type_='check')
    op.create_check_constraint(
        'admin_audit_values', 'admin_audit_events',
        f"source IN ('web','cli') AND after_role IN ({roles}) AND (before_role IS NULL OR before_role IN ({roles}))",
    )


def upgrade():
    op.add_column('users', sa.Column('review_status', sa.Text, nullable=False, server_default='approved'))
    op.alter_column('users', 'role', existing_type=sa.Text(), nullable=True)
    op.drop_constraint('users_role_check', 'users', type_='check')
    op.execute("UPDATE users SET role='analyst' WHERE role='user'")
    op.create_check_constraint('users_role_check', 'users', "role IN ('customer','admin','analyst')")
    op.create_check_constraint(
        'users_review_status_check', 'users',
        "(review_status='approved' AND role IS NOT NULL) OR "
        "(review_status IN ('pending','rejected') AND role IS NULL AND NOT active)",
    )
    _replace_audit_roles("'user','admin','customer','analyst'")


def downgrade():
    incompatible = op.get_bind().exec_driver_sql("""
        SELECT EXISTS (SELECT 1 FROM users WHERE review_status <> 'approved' OR role='customer')
            OR EXISTS (SELECT 1 FROM admin_audit_events
                WHERE before_role IN ('customer','analyst') OR after_role IN ('customer','analyst'))
    """).scalar_one()
    if incompatible:
        raise RuntimeError('Account roles or review records require schema 0075; downgrade would lose information.')
    _replace_audit_roles("'user','admin'")
    op.drop_constraint('users_review_status_check', 'users', type_='check')
    op.drop_constraint('users_role_check', 'users', type_='check')
    op.execute("UPDATE users SET role='user' WHERE role='analyst'")
    op.alter_column('users', 'role', existing_type=sa.Text(), nullable=False)
    op.create_check_constraint('users_role_check', 'users', "role IN ('user','admin')")
    op.drop_column('users', 'review_status')
