"""add audit_logs table; change execution_steps.output to TEXT for encrypted storage

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── audit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("detail", sa.JSON(), nullable=True),
    )
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # ── execution_steps.output: JSON → TEXT ────────────────────────────────────
    # EncryptedField stores Fernet tokens as TEXT; JSON column can't hold those.
    # Existing JSON values become their text representation, which the
    # EncryptedField legacy-fallback path handles transparently on read.
    op.alter_column(
        "execution_steps",
        "output",
        type_=sa.Text(),
        postgresql_using="output::text",
        existing_nullable=True,
    )

    # ── agents.system_prompt is already TEXT — no DDL change needed ────────────
    # EncryptedField uses impl=Text; the column type stays the same.
    # New writes will be Fernet tokens; legacy rows are handled by fallback.


def downgrade() -> None:
    # Revert execution_steps.output back to JSON
    # Note: rows written as Fernet tokens will become invalid JSON after downgrade.
    op.alter_column(
        "execution_steps",
        "output",
        type_=sa.JSON(),
        postgresql_using="output::json",
        existing_nullable=True,
    )

    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_table("audit_logs")
