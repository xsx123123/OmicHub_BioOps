# API 参考

CygnusX 提供 RESTful API，所有接口均以 `/api/v1` 为前缀。

## 认证

大部分 API 需要在请求头中携带 JWT Token：

```http
Authorization: Bearer <access_token>
```

Token 可通过登录接口获取。

## 核心接口

### 分析流程

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/flows` | 列出所有分析流程 |
| GET | `/api/v1/flows/{flow_id}` | 获取流程详情 |

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/tasks` | 列出任务 |
| POST | `/api/v1/tasks` | 提交新任务 |
| GET | `/api/v1/tasks/{task_id}` | 获取任务详情 |
| GET | `/api/v1/tasks/{task_id}/dag` | 生成任务 DAG |

### 用户与认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/login` | 用户登录 |
| POST | `/api/v1/auth/register` | 用户注册 |
| GET | `/api/v1/users/me` | 获取当前用户信息 |

## WebSocket

任务实时日志通过 WebSocket 推送：

```
ws://<host>/api/v1/tasks/{task_id}/ws?token=<access_token>
```

## 错误码

| 状态码 | 说明 |
|--------|------|
| 401 | 未授权 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 422 | 请求参数错误 |
