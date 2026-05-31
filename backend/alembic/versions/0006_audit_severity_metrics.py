"""Add severity column to audit_logs; create request_metrics table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── audit_logs: add severity column ───────────────────────────────────────
    op.add_column(
        "audit_logs",
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            server_default="low",
        ),
    )
    op.create_index("ix_audit_logs_severity", "audit_logs", ["severity"])

    # ── request_metrics table ─────────────────────────────────────────────────
    op.create_table(
        "request_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("method",   sa.String(10),  nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Float,   nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_request_metrics_timestamp", "request_metrics", ["timestamp"])
    op.create_index("ix_request_metrics_endpoint",  "request_metrics", ["endpoint"])


def downgrade() -> None:
    op.drop_index("ix_request_metrics_endpoint",  table_name="request_metrics")
    op.drop_index("ix_request_metrics_timestamp", table_name="request_metrics")
    op.drop_table("request_metrics")

    op.drop_index("ix_audit_logs_severity", table_name="audit_logs")
    op.drop_column("audit_logs", "severity")
