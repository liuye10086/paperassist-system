"""Atomic session revocation audit, one-use recovery and password throttling."""
from alembic import op
import sqlalchemy as sa

revision = "0003_password_security"
down_revision = "0002_auth_ownership"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_revocations",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("revoked_at", sa.Double, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
    )
    op.create_index("session_revocations_user_time", "session_revocations", ["user_id", "revoked_at"])
    op.create_table(
        "password_recovery_codes",
        sa.Column("code_hash", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Double, nullable=False),
        sa.Column("expires_at", sa.Double, nullable=False),
        sa.Column("used_at", sa.Double),
        sa.Column("revoked_at", sa.Double),
        sa.CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="recovery_single_terminal_state"),
    )
    op.create_index("password_recovery_user", "password_recovery_codes", ["user_id"])
    op.create_table(
        "auth_password_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id")),
        sa.Column("code_hash", sa.Text),
        sa.Column("client_ip", sa.Text, nullable=False),
        sa.Column("attempted_at", sa.Double, nullable=False),
    )
    op.create_index("password_attempts_user_time", "auth_password_attempts", ["user_id", "attempted_at"])
    op.create_index("password_attempts_code_time", "auth_password_attempts", ["code_hash", "attempted_at"])
    op.create_index("password_attempts_ip_time", "auth_password_attempts", ["client_ip", "attempted_at"])


def downgrade():
    op.drop_table("auth_password_attempts")
    op.drop_table("password_recovery_codes")
    op.drop_table("session_revocations")
