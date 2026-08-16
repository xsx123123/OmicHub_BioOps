"""ORM contracts for project-scoped agent resources."""

from omichub.infrastructure.database.models.agent import AgentTemplateModel
from omichub.infrastructure.database.models.agent_memory import AgentMemoryModel
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from omichub.infrastructure.database.models.knowledge_document import KbDocumentModel
from omichub.infrastructure.database.models.mas import MASArtifactModel


def test_requested_models_expose_nullable_project_id() -> None:
    for model in (
        AgentTemplateModel,
        ChatSessionModel,
        AgentMemoryModel,
        KnowledgeBaseModel,
        KbDocumentModel,
        MASArtifactModel,
    ):
        column = model.__table__.c.project_id
        assert column.nullable is True
        assert column.type.length == 64
