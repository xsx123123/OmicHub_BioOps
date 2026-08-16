"""backfill omichub-platform preset into builtin agents' mcp_ids

存量内置 Agent 在 omichub-platform preset 引入之前落库，mcp_ids 里只有
omichub-tools；ensure_builtin_agents 对已存在 Agent 只同步 features、不动绑定，
因此需要一个一次性数据迁移把平台操作工具（任务/流程/沙箱/文件读取）补齐。

只处理「仍保持默认绑定」的内置 Agent（mcp_ids 含 omichub-tools 但不含
omichub-platform）；管理员自定义过绑定的行不受影响，迁移后管理员的调整也不会
被 ensure_builtin_agents 回写。

Revision ID: a5b6c7d8e9f0
Revises: z4a5b6c7d8e9
Create Date: 2026-07-22
"""

import uuid

from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None

# 与 infrastructure/mcp/presets.py 中的确定性 UUID 保持一致
_OMICHUB_TOOLS_SERVER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "omichub-tools.builtin"))
_OMICHUB_PLATFORM_SERVER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "omichub-platform.builtin"))


def upgrade() -> None:
    # 注意：存量库的 mcp_ids 实际是 json 类型（模型声明 JSONB，存在漂移），
    # @> / || / - 都是 jsonb 运算符，必须显式 ::jsonb 转型，赋值再转回 ::json。
    # 1) 默认绑定行（含 omichub-tools 不含 platform）→ 追加 platform
    op.execute(
        f"""
        UPDATE agent_templates
        SET mcp_ids = (mcp_ids::jsonb || '["{_OMICHUB_PLATFORM_SERVER_ID}"]'::jsonb)::json
        WHERE is_builtin
          AND mcp_ids::jsonb @> '["{_OMICHUB_TOOLS_SERVER_ID}"]'::jsonb
          AND NOT (mcp_ids::jsonb @> '["{_OMICHUB_PLATFORM_SERVER_ID}"]'::jsonb)
        """
    )
    # 2) 空绑定行（[]，运行时语义等同"默认注入 omichub-tools"）→ 补全两个 preset。
    #    必须连 tools 一起写入：只写 platform 会让 assemble_context 的"空则默认注入"
    #    分支失效，反而丢掉生信工具箱。
    op.execute(
        f"""
        UPDATE agent_templates
        SET mcp_ids = '["{_OMICHUB_TOOLS_SERVER_ID}", "{_OMICHUB_PLATFORM_SERVER_ID}"]'::json
        WHERE is_builtin
          AND mcp_ids::jsonb = '[]'::jsonb
        """
    )


def downgrade() -> None:
    # 对原空绑定行，回退后 mcp_ids 变为 [tools]，与 [] 运行时语义相同（均注入 omichub-tools）。
    op.execute(
        f"""
        UPDATE agent_templates
        SET mcp_ids = (mcp_ids::jsonb - '{_OMICHUB_PLATFORM_SERVER_ID}')::json
        WHERE is_builtin
          AND mcp_ids::jsonb @> '["{_OMICHUB_TOOLS_SERVER_ID}"]'::jsonb
          AND mcp_ids::jsonb @> '["{_OMICHUB_PLATFORM_SERVER_ID}"]'::jsonb
        """
    )
