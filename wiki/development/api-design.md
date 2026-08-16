# API 设计约定

## 统一响应包装

```python
class ResponseModel(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    timestamp: str
```

## 统一分页模型

```python
class PageModel(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
```

分页请求参数：`page`（默认 1）、`page_size`（默认 20，最大 200）、`sort_by`、`sort_order`。

## 异常处理

| 异常 | HTTP body code | 说明 |
|---|---|---|
| 业务异常 | 4xx/5xx | `OmicsHubException` |
| 参数校验失败 | 422 | `RequestValidationError` |
| 未处理异常 | 500 | 兜底，不暴露堆栈 |

## JWT 认证

- Access Token 默认 30 分钟
- Refresh Token 默认 7 天
- 生产环境必须替换默认 `JWT_SECRET_KEY`
- 引入 `token_version` 实现 JWT 吊销

## 路由注册

所有模块路由在 `src/omichub/api/v1/router.py` 统一挂载，不要在应用入口散落注册。
