"""openFuyao 阶段 2/3：集群、集群节点、应用三张表。

revision      = "20261021_01"
down_revision = "20261019_01"

只新增表；``downgrade`` 仅删除本迁移创建的表。
``persistence/db.py::_handle_legacy_db_if_needed`` 的必需对象清单已同步登记。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_01"
down_revision = "20261019_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openfuyao_clusters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("namespace", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column(
            "progress", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "expected_node_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("kubeconfig_path", sa.String(length=512), nullable=True),
        sa.Column("endpoint", sa.String(length=255), nullable=True),
        sa.Column("preflight_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_openfuyao_clusters_name"),
    )
    op.create_index(
        "ix_openfuyao_clusters_agent_id", "openfuyao_clusters", ["agent_id"]
    )
    op.create_index(
        "ix_openfuyao_clusters_status", "openfuyao_clusters", ["status"]
    )

    op.create_table(
        "openfuyao_cluster_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column(
            "port", sa.Integer(), nullable=False, server_default=sa.text("22")
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
            server_default="root",
        ),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="worker",
        ),
        sa.Column(
            "is_local",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "phase",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["openfuyao_clusters.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cluster_id", "ip", name="uq_openfuyao_cluster_nodes_ip"
        ),
        sa.UniqueConstraint(
            "cluster_id", "hostname", name="uq_openfuyao_cluster_nodes_hostname"
        ),
    )
    op.create_index(
        "ix_openfuyao_cluster_nodes_cluster_id",
        "openfuyao_cluster_nodes",
        ["cluster_id"],
    )

    op.create_table(
        "openfuyao_apps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("namespace", sa.String(length=63), nullable=False),
        sa.Column("release_name", sa.String(length=63), nullable=False),
        sa.Column("repo_name", sa.String(length=128), nullable=True),
        sa.Column("chart_name", sa.String(length=128), nullable=True),
        sa.Column("chart_version", sa.String(length=64), nullable=True),
        sa.Column("values_json", sa.JSON(), nullable=True),
        sa.Column("image_override", sa.String(length=512), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "phase",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "progress", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("node_port", sa.Integer(), nullable=True),
        sa.Column("verify_url", sa.String(length=512), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["openfuyao_clusters.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cluster_id",
            "namespace",
            "release_name",
            name="uq_openfuyao_apps_release",
        ),
    )
    op.create_index(
        "ix_openfuyao_apps_cluster_id", "openfuyao_apps", ["cluster_id"]
    )
    op.create_index("ix_openfuyao_apps_agent_id", "openfuyao_apps", ["agent_id"])
    op.create_index("ix_openfuyao_apps_status", "openfuyao_apps", ["status"])


def downgrade() -> None:
    op.drop_index("ix_openfuyao_apps_status", table_name="openfuyao_apps")
    op.drop_index("ix_openfuyao_apps_agent_id", table_name="openfuyao_apps")
    op.drop_index("ix_openfuyao_apps_cluster_id", table_name="openfuyao_apps")
    op.drop_table("openfuyao_apps")

    op.drop_index(
        "ix_openfuyao_cluster_nodes_cluster_id",
        table_name="openfuyao_cluster_nodes",
    )
    op.drop_table("openfuyao_cluster_nodes")

    op.drop_index("ix_openfuyao_clusters_status", table_name="openfuyao_clusters")
    op.drop_index("ix_openfuyao_clusters_agent_id", table_name="openfuyao_clusters")
    op.drop_table("openfuyao_clusters")
