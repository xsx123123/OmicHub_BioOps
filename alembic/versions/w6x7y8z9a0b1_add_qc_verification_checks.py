"""add qc_verification_checks table (agent-qc 结构化判决落库, F2)

证据化验收：qc 会诊的 checks[] 逐行落库（case_id、claim_hash、verdict、
evidence_event_id、reviewer_agent、claim_snapshot、reason），判决可统计、
可复核，与后续返工率交叉验证。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w6x7y8z9a0b1"
down_revision: str | Sequence[str] | None = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qc_verification_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("claim_hash", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("evidence_event_id", sa.String(length=128), nullable=True),
        sa.Column("reviewer_agent", sa.String(length=80), nullable=False),
        sa.Column(
            "claim_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_qc_verification_checks_case_id", "qc_verification_checks", ["case_id"])
    op.create_index(
        "ix_qc_verification_checks_claim_hash", "qc_verification_checks", ["claim_hash"]
    )
    op.create_index(
        "ix_qc_verification_checks_case_verdict",
        "qc_verification_checks",
        ["case_id", "verdict"],
    )


def downgrade() -> None:
    op.drop_index("ix_qc_verification_checks_case_verdict", table_name="qc_verification_checks")
    op.drop_index("ix_qc_verification_checks_claim_hash", table_name="qc_verification_checks")
    op.drop_index("ix_qc_verification_checks_case_id", table_name="qc_verification_checks")
    op.drop_table("qc_verification_checks")
