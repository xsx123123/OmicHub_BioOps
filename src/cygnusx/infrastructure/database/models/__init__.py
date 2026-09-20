"""ORM 模型

各域 ORM 表模型，对应 domain/entities.py 中的实体。
导入即注册到 Base.metadata，供 create_all / alembic 使用。
"""

from cygnusx.infrastructure.database.models.agent import (
    AgentTemplateModel,
    UserAgentCapabilityModel,
)
from cygnusx.infrastructure.database.models.agent_memory import (
    AgentMemoryModel,
    MemoryBlockModel,
    MemoryFactModel,
    MemorySettlementModel,
)
from cygnusx.infrastructure.database.models.agentteams_bridge import AgentTeamsBridgeSettingsModel
from cygnusx.infrastructure.database.models.ai import ConversationModel, MessageModel
from cygnusx.infrastructure.database.models.ai_metric import (
    AiCallMetricModel,
    AiMetricAlertModel,
)
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel
from cygnusx.infrastructure.database.models.announcement import AnnouncementModel
from cygnusx.infrastructure.database.models.api_key import APIKeyModel
from cygnusx.infrastructure.database.models.audit_log import AuditLogModel
from cygnusx.infrastructure.database.models.blast import (
    BlastDatabaseModel,
    BlastTaskModel,
)
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsCaseCursorModel,
    AgentTeamsRoomMemberModel,
    AgentTeamsRoomModel,
    AgentTeamsTurnRecordModel,
    CaseArtifactDependencyModel,
    CaseArtifactVersionModel,
    ChatAssistantModel,
    ChatHandoffEventModel,
    ChatMessageEventModel,
    ChatMessageFeedbackModel,
    ChatMessageModel,
    ChatSessionModel,
    CollaborationDegradationEventModel,
    QcVerificationCheckModel,
)
from cygnusx.infrastructure.database.models.cookie import (
    ConsumptionLogModel,
    CookieAccountModel,
    CookiePricingModel,
    CookieTransactionModel,
    LedgerEntryModel,
)
from cygnusx.infrastructure.database.models.festival import FestivalClaimModel
from cygnusx.infrastructure.database.models.file import (
    DirectoryModel,
    FileRecordModel,
    SampleModel,
    UploadSessionModel,
)
from cygnusx.infrastructure.database.models.goal import (
    AgentGoalEventModel,
    AgentGoalModel,
    AgentGoalWorkUnitModel,
)
from cygnusx.infrastructure.database.models.knowledge_audit_log import DocAuditLogModel
from cygnusx.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from cygnusx.infrastructure.database.models.knowledge_chunk import KbChunkModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_issue import KbIssueModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.mas import (
    MASA2AEventModel,
    MASApprovalModel,
    MASArtifactModel,
    MASNodeModel,
    MASPlanModel,
    MASReworkGuardModel,
    MASRunModel,
)
from cygnusx.infrastructure.database.models.mcp import MCPServerModel
from cygnusx.infrastructure.database.models.mcp_builder import (
    MCPBuildModel,
    MCPReviewModel,
    MCPVersionModel,
    MCPVisibilityModel,
)
from cygnusx.infrastructure.database.models.mcp_log import MCPLogModel
from cygnusx.infrastructure.database.models.notification import NotificationModel
from cygnusx.infrastructure.database.models.overdrive import (
    OverdriveCommandModel,
    OverdriveEventModel,
    OverdriveRunModel,
    OverdriveTaskResultModel,
)
from cygnusx.infrastructure.database.models.project import ProjectModel
from cygnusx.infrastructure.database.models.report import ReportFileModel, ReportModel
from cygnusx.infrastructure.database.models.sandbox import SandboxSessionModel
from cygnusx.infrastructure.database.models.schedule import (
    ReminderDeliveryModel,
    ScheduleModel,
    ScheduleOccurrenceModel,
)
from cygnusx.infrastructure.database.models.search_provider import SearchProviderConfigModel
from cygnusx.infrastructure.database.models.site_settings import SiteSettingModel
from cygnusx.infrastructure.database.models.skill import (
    SkillInvocationModel,
    SkillModel,
    SkillVersionModel,
)
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.database.models.team import TeamMemberModel, TeamModel
from cygnusx.infrastructure.database.models.terminal import TerminalSessionModel
from cygnusx.infrastructure.database.models.user import UserModel, WorkspaceModel
from cygnusx.infrastructure.database.models.workspace_archive import WorkspaceArchiveModel

__all__ = [
    "AgentTemplateModel",
    "UserAgentCapabilityModel",
    "AgentTeamsBridgeSettingsModel",
    "AgentMemoryModel",
    "MemoryBlockModel",
    "MemoryFactModel",
    "MemorySettlementModel",
    "APIKeyModel",
    "UserModel",
    "WorkspaceModel",
    "WorkspaceArchiveModel",
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
    "AgentTeamsRoomModel",
    "AgentTeamsRoomMemberModel",
    "AgentTeamsTurnRecordModel",
    "CaseArtifactDependencyModel",
    "CaseArtifactVersionModel",
    "QcVerificationCheckModel",
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
    "MCPLogModel",
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
    "ScheduleModel",
    "ScheduleOccurrenceModel",
    "ReminderDeliveryModel",
]
