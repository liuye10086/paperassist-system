"""Accounts, revocable sessions, login throttling and project ownership."""

from alembic import op
import sqlalchemy as sa

revision = "0002_auth_ownership"
down_revision = "0001_postgresql"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.Double, nullable=False),
        sa.Column("updated_at", sa.Double, nullable=False),
        sa.CheckConstraint("role IN ('user','admin')", name="users_role_check"),
    )
    op.add_column("projects", sa.Column("owner_id", sa.Text, nullable=True))
    op.create_foreign_key(
        "projects_owner_id_fkey", "projects", "users", ["owner_id"], ["id"]
    )
    op.create_index("projects_owner", "projects", ["owner_id"])
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("csrf_token", sa.Text, nullable=False),
        sa.Column("created_at", sa.Double, nullable=False),
        sa.Column("last_seen_at", sa.Double, nullable=False),
        sa.Column("expires_at", sa.Double, nullable=False),
    )
    op.create_index("sessions_user", "sessions", ["user_id"])
    op.create_table(
        "auth_login_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("client_ip", sa.Text, nullable=False),
        sa.Column("attempted_at", sa.Double, nullable=False),
    )
    op.create_index(
        "auth_attempts_email_time", "auth_login_attempts", ["email", "attempted_at"]
    )
    op.create_index(
        "auth_attempts_ip_time", "auth_login_attempts", ["client_ip", "attempted_at"]
    )


def downgrade():
    op.drop_table("auth_login_attempts")
    op.drop_table("sessions")
    op.drop_index("projects_owner", table_name="projects")
    op.drop_constraint("projects_owner_id_fkey", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
    op.drop_table("users")
