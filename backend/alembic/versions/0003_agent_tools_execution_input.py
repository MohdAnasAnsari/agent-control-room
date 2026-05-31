"""add tools to agents, input_data to executions, updated_at to agents

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agents.tools — JSON list of tool names
    op.add_column(
        "agents",
        sa.Column("tools", sa.JSON(), nullable=False, server_default="[]"),
    )
    # agents.updated_at — auto-update timestamp
    op.add_column(
        "agents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # executions.input_data — workflow trigger payload
    op.add_column(
        "executions",
        sa.Column("input_data", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("executions", "input_data")
    op.drop_column("agents", "updated_at")
    op.drop_column("agents", "tools")
