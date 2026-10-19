"""openFuyao Environment 表。

revision      = "20261019_01"
down_revision = "20260915_01"

只新增表，不改既有列；`downgrade` 仅删除本表。
`persistence/db.py::_handle_legacy_db_if_needed` 的必需对象清单需同步登记本表，
否则存量库会在迁移前被误判为结构完整并 stamp head。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261019_01"
down_revision = "20260915_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openfuyao_environments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column(
            "progress", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("console_url", sa.String(length=512), nullable=True),
        sa.Column("proxy_url", sa.String(length=512), nullable=True),
        sa.Column("bke_version", sa.String(length=64), nullable=True),
        sa.Column("os_version", sa.String(length=64), nullable=True),
        sa.Column("preflight_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host", name="uq_openfuyao_environments_host"),
    )
    op.create_index(
        "ix_openfuyao_environments_agent_id",
        "openfuyao_environments",
        ["agent_id"],
    )
    op.create_index(
        "ix_openfuyao_environments_status",
        "openfuyao_environments",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_openfuyao_environments_status", table_name="openfuyao_environments"
    )
    op.drop_index(
        "ix_openfuyao_environments_agent_id", table_name="openfuyao_environments"
    )
    op.drop_table("openfuyao_environments")
