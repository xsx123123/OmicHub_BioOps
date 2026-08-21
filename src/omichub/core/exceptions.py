"""自定义异常类"""


class OmicHubError(Exception):
    """OmicHub 基础异常"""

    status_code: int = 500
    detail: str = "Internal Server Error"

    def __init__(self, detail: str | None = None, *, code: str | None = None):
        self.detail = detail or self.detail
        self.code = code
        super().__init__(self.detail)


class NotFoundError(OmicHubError):
    status_code = 404
    detail = "Resource not found"


class ConflictError(OmicHubError):
    status_code = 409
    detail = "Resource already exists"


class AuthenticationError(OmicHubError):
    status_code = 401
    detail = "Authentication failed"


class RateLimitError(OmicHubError):
    """请求已超过安全限流阈值。"""

    status_code = 429
    detail = "请求过于频繁，请稍后再试"


class AuthorizationError(OmicHubError):
    status_code = 403
    detail = "Permission denied"


class ValidationError(OmicHubError):
    status_code = 422
    detail = "Validation error"


class TaskExecutionError(OmicHubError):
    status_code = 500
    detail = "Task execution failed"


class YAMLConfigError(OmicHubError):
    status_code = 422
    detail = "YAML configuration error"


class MCPConnectionError(OmicHubError):
    status_code = 503
    detail = "MCP server connection failed"


class BusinessError(OmicHubError):
    status_code = 400
    detail = "Business rule violation"


class InsufficientBalanceError(BusinessError):
    status_code = 402
    detail = "Insufficient cookie balance"


class QuotaExceededError(OmicHubError):
    """存储配额超限 — 上传前置校验拦截"""

    status_code = 403
    detail = "存储空间不足"
