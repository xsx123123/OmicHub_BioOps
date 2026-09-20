"""自定义异常类"""


class CygnusXError(Exception):
    """CygnusX 基础异常"""

    status_code: int = 500
    detail: str = "Internal Server Error"

    def __init__(self, detail: str | None = None, *, code: str | None = None):
        self.detail = detail or self.detail
        self.code = code
        super().__init__(self.detail)


class NotFoundError(CygnusXError):
    status_code = 404
    detail = "Resource not found"


class ConflictError(CygnusXError):
    status_code = 409
    detail = "Resource already exists"


class AuthenticationError(CygnusXError):
    status_code = 401
    detail = "Authentication failed"


class RateLimitError(CygnusXError):
    """请求已超过安全限流阈值。"""

    status_code = 429
    detail = "请求过于频繁，请稍后再试"


class AuthorizationError(CygnusXError):
    status_code = 403
    detail = "Permission denied"


class ValidationError(CygnusXError):
    status_code = 422
    detail = "Validation error"


class TaskExecutionError(CygnusXError):
    status_code = 500
    detail = "Task execution failed"


class YAMLConfigError(CygnusXError):
    status_code = 422
    detail = "YAML configuration error"


class MCPConnectionError(CygnusXError):
    status_code = 503
    detail = "MCP server connection failed"


class BusinessError(CygnusXError):
    status_code = 400
    detail = "Business rule violation"


class InsufficientBalanceError(BusinessError):
    status_code = 402
    detail = "Insufficient cookie balance"


class QuotaExceededError(CygnusXError):
    """存储配额超限 — 上传前置校验拦截"""

    status_code = 403
    detail = "存储空间不足"
