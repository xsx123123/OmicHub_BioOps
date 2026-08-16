"""ORM 模型

各域 ORM 表模型，对应 domain/entities.py 中的实体。
导入即注册到 Base.metadata，供 create_all / alembic 使用。
"""

from omichub.infrastructure.database.models.agent import AgentTemplateModel, UserAgentCapabilityModel
from omichub.infrastructure.database.models.agent_memory import AgentMemoryModel
from omichub.infrastructure.database.models.agentteams_bridge import AgentTeamsBridgeSettingsModel
from omichub.infrastructure.database.models.ai import ConversationModel, MessageModel
from omichub.infrastructure.database.models.ai_metric import (
    AiCallMetricModel,
    AiMetricAlertModel,
)
from omichub.infrastructure.database.models.ai_provider import AIProviderConfigModel
from omichub.infrastructure.database.models.announcement import AnnouncementModel
from omichub.infrastructure.database.models.api_key import APIKeyModel
from omichub.infrastructure.database.models.audit_log import AuditLogModel
from omichub.infrastructure.database.models.blast import (
    BlastDatabaseModel,
    BlastTaskModel,
)
from omichub.infrastructure.database.models.chat import (
    AgentTeamsCaseCursorModel,
    ChatAssistantModel,
    ChatMessageFeedbackModel,
    CollaborationDegradationEventModel,
    ChatHandoffEventModel,
    ChatMessageModel,
    ChatSessionModel,
)
from omichub.infrastructure.database.models.cookie import (
    ConsumptionLogModel,
    CookieAccountModel,
    CookiePricingModel,
    CookieTransactionModel,
    LedgerEntryModel,
)
from omichub.infrastructure.database.models.festival import FestivalClaimModel
from omichub.infrastructure.database.models.goal import (
    AgentGoalEventModel,
    AgentGoalModel,
    AgentGoalWorkUnitModel,
)
from omichub.infrastructure.database.models.file import (
    DirectoryModel,
    FileRecordModel,
    SampleModel,
    UploadSessionModel,
)
from omichub.infrastructure.database.models.knowledge_audit_log import DocAuditLogModel
from omichub.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from omichub.infrastructure.database.models.knowledge_chunk import KbChunkModel
from omichub.infrastructure.database.models.knowledge_document import KbDocumentModel
from omichub.infrastructure.database.models.knowledge_editor import DocEditorModel
from omichub.infrastructure.database.models.knowledge_issue import KbIssueModel
from omichub.infrastructure.database.models.knowledge_revision import DocRevisionModel
from omichub.infrastructure.database.models.mas import (
    MASA2AEventModel,
    MASApprovalModel,
    MASArtifactModel,
    MASNodeModel,
    MASPlanModel,
    MASReworkGuardModel,
    MASRunModel,
)
from omichub.infrastructure.database.models.mcp import MCPServerModel
from omichub.infrastructure.database.models.mcp_builder import (
    MCPBuildModel,
    MCPReviewModel,
    MCPVersionModel,
    MCPVisibilityModel,
)
from omichub.infrastructure.database.models.notification import NotificationModel
from omichub.infrastructure.database.models.overdrive import (
    OverdriveCommandModel,
    OverdriveEventModel,
    OverdriveRunModel,
    OverdriveTaskResultModel,
)
from omichub.infrastructure.database.models.project import ProjectModel
from omichub.infrastructure.database.models.report import ReportFileModel, ReportModel
from omichub.infrastructure.database.models.sandbox import SandboxSessionModel
from omichub.infrastructure.database.models.search_provider import SearchProviderConfigModel
from omichub.infrastructure.database.models.site_settings import SiteSettingModel
from omichub.infrastructure.database.models.skill import (
    SkillInvocationModel,
    SkillModel,
    SkillVersionModel,
)
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.database.models.team import TeamMemberModel, TeamModel
from omichub.infrastructure.database.models.terminal import TerminalSessionModel
from omichub.infrastructure.database.models.user import UserModel, WorkspaceModel

__all__ = [
    "AgentTemplateModel",
    "UserAgentCapabilityModel",
    "AgentTeamsBridgeSettingsModel",
    "AgentMemoryModel",
    "APIKeyModel",
    "UserModel",
    "WorkspaceModel",
    "TaskModel",
    "TeamModel",
    "TeamMemberModel",
    "CookieAccountModel",
    "CookieTransactionModel",
    "CookiePricingModel",
    "ConsumptionLogModel",
    "LedgerEntryModel",
    "FestivalClaimModel",
    "AgentGoalModel",
    "AgentGoalEventModel",
    "AgentGoalWorkUnitModel",
    "ConversationModel",
    "MessageModel",
    "ChatSessionModel",
    "AgentTeamsCaseCursorModel",
    "ChatMessageModel",
    "ChatMessageFeedbackModel",
    "ChatAssistantModel",
    "ChatHandoffEventModel",
    "CollaborationDegradationEventModel",
    "AIProviderConfigModel",
    "AiCallMetricModel",
    "AiMetricAlertModel",
    "AnnouncementModel",
    "AuditLogModel",
    "BlastDatabaseModel",
    "BlastTaskModel",
    "KbDocumentModel",
    "KbChunkModel",
    "KnowledgeBaseModel",
    "DocRevisionModel",
    "DocEditorModel",
    "KbIssueModel",
    "DocAuditLogModel",
    "MCPServerModel",
    "MCPBuildModel",
    "MCPVersionModel",
    "MCPVisibilityModel",
    "MCPReviewModel",
    "MASPlanModel",
    "MASRunModel",
    "MASNodeModel",
    "MASArtifactModel",
    "MASA2AEventModel",
    "MASApprovalModel",
    "MASReworkGuardModel",
    "ReportModel",
    "ReportFileModel",
    "SandboxSessionModel",
    "SearchProviderConfigModel",
    "TerminalSessionModel",
    "NotificationModel",
    "OverdriveRunModel",
    "OverdriveEventModel",
    "OverdriveCommandModel",
    "OverdriveTaskResultModel",
    "SiteSettingModel",
    "SkillInvocationModel",
    "SkillModel",
    "SkillVersionModel",
    "FileRecordModel",
    "UploadSessionModel",
    "SampleModel",
    "DirectoryModel",
    "ProjectModel",
]
