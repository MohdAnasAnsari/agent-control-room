"""add agent_states and agent_contexts tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── agent_states ────────────────────────────────────────────────────────
    op.create_table(
        "agent_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tools",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "memory",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "runtime_status",
            sa.String(50),
            nullable=False,
            server_default="idle",
        ),
        sa.Column("current_task", sa.Text(), nullable=True),
        sa.Column(
            "execution_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_execution", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_states_agent_id", "agent_states", ["agent_id"])
    op.create_unique_constraint(
        "uq_agent_states_agent_id", "agent_states", ["agent_id"]
    )

    # ── agent_contexts ───────────────────────────────────────────────────────
    op.create_table(
        "agent_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "parent_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dependencies",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "execution_path",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "step_data",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_contexts_execution_id", "agent_contexts", ["execution_id"]
    )
    op.create_unique_constraint(
        "uq_agent_contexts_execution_id", "agent_contexts", ["execution_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_contexts_execution_id", "agent_contexts", type_="unique"
    )
    op.drop_index("ix_agent_contexts_execution_id", table_name="agent_contexts")
    op.drop_table("agent_contexts")

    op.drop_constraint(
        "uq_agent_states_agent_id", "agent_states", type_="unique"
    )
    op.drop_index("ix_agent_states_agent_id", table_name="agent_states")
    op.drop_table("agent_states")
