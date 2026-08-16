# 首次部署与管理员注册

## `/setup` 初始化页面

首次部署且数据库中没有管理员时，浏览器访问：

```text
http://<服务器IP>:8888/setup
```

- 仅在系统无管理员账号时可用。
- 创建成功后 `/setup` 自动关闭，再次访问会重定向到登录页。
- 后端 `has_any_admin()` 会校验，无法绕过前端重复注册。

## 管理员创建后

- 其他账号由管理员在「系统管理 → 用户管理」创建。
- 或在开启自助注册后通过登录页注册。
- 首次登录会弹出迎新引导，并收到指向知识库的欢迎通知。

## 默认环境变量（生产必填）

| 变量 | 说明 |
|---|---|
| `JWT_SECRET_KEY` | JWT 签名密钥，≥32 字节随机字符串 |
| `APP_SECRET_KEY` | Cookie/Session 签名密钥 |
| `REDIS_PASSWORD` | Redis 认证密码 |
| `AI_PROVIDER_KEY_ENCRYPTION_KEY` | Fernet 32 字节 URL-safe base64 密钥 |
| `OMICHBUB_INIT_ADMIN_PASSWORD` | 生产环境初始管理员强密码 |

`AI_PROVIDER_KEY_ENCRYPTION_KEY` 一旦设置不可更改，否则已加密字段无法解密。
