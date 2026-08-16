"""API v1 路由汇总"""

from fastapi import APIRouter

from omichub.api.v1 import (
    agents,
    agentteams,
    ai,
    announcements,
    auth,
    chat,
    cookies,
    docs,
    downloads,
    festival,
    files,
    flows,
    goals,
    llm,
    mas,
    mcp,
    mcp_builder,
    modules,
    notification,
    pipelines,
    platform_config,
    plot_stats,
    projects,
    prompts,
    reports,
    sandbox,
    site_content,
    site_settings,
    stats,
    studio,
    tasks,
    teams,
    terminal,
    users,
    workflow_monitor,
)
from omichub.api.v1.admin import admin_cookies
from omichub.api.v1.admin import agents as admin_agents
from omichub.api.v1.admin import agentteams_bridge as admin_agentteams_bridge
from omichub.api.v1.admin import ai_metrics as admin_ai_metrics
from omichub.api.v1.admin import ai_providers as admin_ai_providers
from omichub.api.v1.admin import assistants as admin_assistants
from omichub.api.v1.admin import festival as admin_festival
from omichub.api.v1.admin import knowledge_bases as admin_knowledge_bases
from omichub.api.v1.admin import platform_config as admin_platform_config
from omichub.api.v1.admin import search_providers as admin_search_providers
from omichub.api.v1.admin import session_logs as admin_session_logs
from omichub.api.v1.admin import skills as admin_skills
from omichub.api.v1.admin import stats as admin_stats
from omichub.api.v1.admin import storage as admin_storage
from omichub.api.v1.admin import terminals as admin_terminals
from omichub.api.v1.admin import users as admin_users
from omichub.reference_genomes.api import router as reference_genomes_router
from omichub.tools import register_tool_routers

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(site_settings.router, prefix="/site-settings", tags=["SiteSettings"])
api_router.include_router(platform_config.router, prefix="/platform", tags=["PlatformConfig"])
api_router.include_router(site_content.router, prefix="/site-content", tags=["SiteContent"])
api_router.include_router(docs.router, prefix="/docs", tags=["Docs"])
api_router.include_router(flows.router, prefix="/flows", tags=["Flows"])
api_router.include_router(goals.router, prefix="/goals", tags=["Goals"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(pipelines.router, prefix="/pipelines", tags=["Pipelines"])
api_router.include_router(stats.router, prefix="/stats", tags=["Stats"])
api_router.include_router(plot_stats.router, prefix="/stats", tags=["PlotStats"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["Prompts"])
api_router.include_router(
    workflow_monitor.router, prefix="/workflow-monitor", tags=["Workflow-Monitor"]
)
api_router.include_router(downloads.router, prefix="/downloads", tags=["Downloads"])
api_router.include_router(files.router, prefix="/files", tags=["Files"])
api_router.include_router(teams.router, prefix="/teams", tags=["Teams"])
api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(cookies.router, prefix="/cookies", tags=["Cookies"])
api_router.include_router(admin_cookies.router, prefix="/admin/cookies", tags=["Admin-Cookies"])
api_router.include_router(admin_users.router, prefix="/admin/users", tags=["Admin-Users"])
api_router.include_router(admin_stats.router, prefix="/admin/stats", tags=["Admin-Stats"])
api_router.include_router(
    admin_session_logs.router, prefix="/admin/session-logs", tags=["Admin-Session-Logs"]
)
api_router.include_router(
    admin_ai_metrics.router, prefix="/admin/ai-metrics", tags=["Admin-AI-Metrics"]
)
api_router.include_router(
    admin_terminals.router, prefix="/admin/terminals", tags=["Admin-Terminals"]
)
api_router.include_router(admin_storage.router, prefix="/admin/storage", tags=["Admin-Storage"])
api_router.include_router(
    admin_ai_providers.router, prefix="/admin/ai-providers", tags=["Admin-AI-Providers"]
)
api_router.include_router(
    admin_search_providers.router, prefix="/admin/search-providers", tags=["Admin-Search-Providers"]
)
api_router.include_router(admin_skills.router, prefix="/admin/skills", tags=["Admin-Skills"])
api_router.include_router(
    admin_assistants.router, prefix="/admin/assistants", tags=["Admin-Assistants"]
)
api_router.include_router(
    admin_knowledge_bases.router, prefix="/admin/knowledge-bases", tags=["Admin-Knowledge-Bases"]
)
api_router.include_router(admin_agents.router, prefix="/admin/agents", tags=["Admin-Agents"])
api_router.include_router(admin_festival.router, prefix="/admin", tags=["Admin-Festival"])
api_router.include_router(
    admin_platform_config.router, prefix="/admin", tags=["Admin-PlatformConfig"]
)
api_router.include_router(
    admin_agentteams_bridge.router, prefix="/admin", tags=["Admin-AgentTeamsBridge"]
)
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])
api_router.include_router(agentteams.router, prefix="/agent-teams", tags=["AgentTeams"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI Copilot"])
api_router.include_router(chat.router, prefix="/chat", tags=["AI Chat"])
api_router.include_router(llm.router, prefix="/llm", tags=["LLM"])
api_router.include_router(mas.router, prefix="/mas", tags=["Multi-Agent System"])
api_router.include_router(notification.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(announcements.router, prefix="/announcements", tags=["Announcements"])
api_router.include_router(festival.router, prefix="/festival", tags=["Festival"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(mcp.router, prefix="/mcp", tags=["MCP"])
api_router.include_router(mcp_builder.router, prefix="/mcp-builder", tags=["MCP Builder"])
api_router.include_router(sandbox.router, prefix="/sandbox", tags=["Sandbox"])
api_router.include_router(studio.router, prefix="/studio", tags=["Studio"])
api_router.include_router(terminal.router, prefix="/terminal", tags=["Terminal"])
api_router.include_router(modules.router, prefix="/modules", tags=["Modules"])

# 常用物种基因数据库（参考基因组模块）：物种/版本/基因搜索/序列/GO/KEGG/统一搜索
api_router.include_router(
    reference_genomes_router, prefix="/reference-genomes", tags=["参考基因组"]
)

# 生信工具箱：自动发现 omichub.tools.<工具>.api 并挂载（每个工具自声明 prefix/tags）
# 新增工具无需改本文件 —— 在 src/omichub/tools/<工具名>/api.py 声明 router/prefix/tags 即可。
register_tool_routers(api_router)
