"""AI 域值对象"""

from enum import Enum


class RoleType(str, Enum):
    """消息角色"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCallStatus(str, Enum):
    """工具调用状态"""

    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"


class ToolName(str, Enum):
    """AI Copilot 内置工具（Tool Use 协议）"""

    SUBMIT_TASK = "submit_task"
    QUERY_STATUS = "query_status"
    LIST_SAMPLES = "list_samples"
