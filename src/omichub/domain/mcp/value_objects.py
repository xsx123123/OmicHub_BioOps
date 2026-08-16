"""MCP 域值对象"""

from enum import Enum


class Transport(str, Enum):
    """MCP 传输模式"""

    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
    BUILTIN = "builtin"  # 内置预设（进程内执行，无需外部进程）


class ServerStatus(str, Enum):
    """MCP Server 状态"""

    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    STARTING = "starting"


class ServerPool(str, Enum):
    """MCP Server 所属池（MCP Builder 引入）"""

    PRODUCTION = "production"  # 正式：Admin 手动注册 / 审核发布，永久有效
    EXPERIMENTAL = "experimental"  # 实验：AI 生成，带 TTL，仅创建者 + Admin 可见
    DEPRECATED = "deprecated"  # 已废弃


class BuildStatus(str, Enum):
    """MCP 构建记录状态机"""

    PLANNING = "planning"
    CODING = "coding"
    TESTING = "testing"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class ReviewStatus(str, Enum):
    """MCP Server 审核状态"""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(str, Enum):
    """审核决定"""

    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_CHANGES = "request_changes"


class AccessLevel(str, Enum):
    """用户级 MCP 可见性"""

    NONE = "none"
    READ = "read"
    EXECUTE = "execute"
    ADMIN = "admin"
