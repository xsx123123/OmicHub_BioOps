# 安全

本章节汇总 OmicHub 的安全加固措施、生产环境检查项与密钥管理要求。

## 内容导航

- [安全加固清单](hardening-checklist) — 24 项已知风险修复与生产检查项
- [环境变量与密钥](env-variables) — 生产密钥、配置组与操作原则

## 核心安全原则

- **默认安全**：任何用户数据、文件、任务、管理接口都必须经过认证、授权与所属关系校验。
- **密钥外置**：JWT、Redis、AI Provider、TOTP 等密钥只通过环境变量注入，不入仓库。
- **最小权限**：沙盒容器只读根文件系统、drop capabilities、网络隔离、资源硬限制。
- **审计可追溯**：关键写操作、权限变化、任务和异常访问应保留可检索的审计与结构化日志。

## 首次部署必填环境变量

```bash
JWT_SECRET_KEY=your-random-secret-here
APP_SECRET_KEY=your-random-secret-here
REDIS_PASSWORD=your-redis-password-here
AI_PROVIDER_KEY_ENCRYPTION_KEY=your-fernet-key-here
OMICHBUB_INIT_ADMIN_PASSWORD=your-strong-password
```

> `AI_PROVIDER_KEY_ENCRYPTION_KEY` 一旦设置并写入数据后不可更改，否则已加密字段将无法解密。
