"""add_home_quick_entries_to_site_settings

Revision ID: r6s7t8u9v0w1
Revises: 3e76881cadbc
Create Date: 2026-07-08 10:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r6s7t8u9v0w1"
down_revision: str | None = "3e76881cadbc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_HOME_QUICK_ENTRIES = [
    {
        "key": "rna-seq",
        "title": "RNA-seq 分析",
        "desc": "转录组差异表达分析",
        "to": "/flows?type=rna-seq",
        "icon": "FlaskOutline",
        "icon_bg": "blue",
    },
    {
        "key": "atac-seq",
        "title": "ATAC-seq 分析",
        "desc": "染色质开放性分析",
        "to": "/flows?type=atac-seq",
        "icon": "FitnessOutline",
        "icon_bg": "purple",
    },
    {
        "key": "files",
        "title": "数据管理",
        "desc": "上传与管理样本数据",
        "to": "/files",
        "icon": "CloudUploadOutline",
        "icon_bg": "cyan",
    },
    {
        "key": "ai",
        "title": "AI 助手",
        "desc": "智能分析与问答",
        "to": "/ai",
        "icon": "ChatbubblesOutline",
        "icon_bg": "green",
    },
    {
        "key": "tasks",
        "title": "任务中心",
        "desc": "查看分析任务进度",
        "to": "/tasks",
        "icon": "DocumentTextOutline",
        "icon_bg": "orange",
    },
]


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column(
            "home_quick_entries",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    settings = sa.table("site_settings", sa.column("home_quick_entries", sa.JSON()))
    op.execute(settings.update().values(home_quick_entries=DEFAULT_HOME_QUICK_ENTRIES))


def downgrade() -> None:
    op.drop_column("site_settings", "home_quick_entries")
