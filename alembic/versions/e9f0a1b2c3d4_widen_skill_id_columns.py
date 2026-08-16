"""widen skill_id columns for aliyun official skills

阿里云官方 Skills 的 ID 可达 60+ 字符（如
alibabacloud-tech-solution-animation-creation-auto-deploy），
skills.skill_id / skill_versions.skill_id 由 varchar(50) 放宽到 varchar(100)。

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa

revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("skills", "skill_id", type_=sa.String(100), existing_type=sa.String(50))
    op.alter_column(
        "skill_versions", "skill_id", type_=sa.String(100), existing_type=sa.String(50)
    )


def downgrade() -> None:
    op.alter_column(
        "skill_versions", "skill_id", type_=sa.String(50), existing_type=sa.String(100)
    )
    op.alter_column("skills", "skill_id", type_=sa.String(50), existing_type=sa.String(100))
