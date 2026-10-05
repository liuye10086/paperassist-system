"""Independent UI and project output language preferences."""
from alembic import op
import sqlalchemy as sa

revision = "0004_language_preferences"
down_revision = "0003_password_security"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("ui_language", sa.Text, nullable=False, server_default="zh-CN"))
    op.create_check_constraint("users_ui_language_check", "users", "ui_language IN ('zh-CN', 'en')")
    op.add_column("projects", sa.Column("default_output_language", sa.Text, nullable=False, server_default="zh-CN"))
    op.create_check_constraint("projects_output_language_check", "projects", "default_output_language IN ('zh-CN', 'en')")


def downgrade():
    op.drop_constraint("projects_output_language_check", "projects", type_="check")
    op.drop_column("projects", "default_output_language")
    op.drop_constraint("users_ui_language_check", "users", type_="check")
    op.drop_column("users", "ui_language")
