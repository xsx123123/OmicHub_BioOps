# 安全加固清单

本页是当前生产部署的操作清单，不把历史漏洞编号或已迁移的文件路径当作长期规范。详细变量说明见
[环境变量与密钥](env-variables)，当前安全实现以代码、`.env.example` 和生产部署配置为准。

## 部署前

- [ ] `APP_ENV=production`、`APP_DEBUG=false`，所有默认密钥均已替换。
- [ ] 已设置 `JWT_SECRET_KEY`、`APP_SECRET_KEY`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、
  `AI_PROVIDER_KEY_ENCRYPTION_KEY` 和强管理员密码。
- [ ] `.env` 不在 Git 中，权限仅授予部署账户；密钥不写入日志、工单和聊天记录。
- [ ] 数据库、Redis、Flower、AgentTeams Bridge、RocketMQ 和调试端口只对可信网络开放。
- [ ] HTTPS、证书续期、反向代理安全头和请求大小限制已配置。

## 身份、权限与数据

- [ ] 所有 API、文件、项目、任务和管理操作经过认证、授权与所属关系校验。
- [ ] 用户工作区、聊天上传、沙盒挂载和下载链接按用户/项目隔离。
- [ ] 管理员账号遵循最小人数、强密码和可审计原则；关闭不需要的自助注册入口。
- [ ] 已对对象存储、下载 URI、MCP 配置和外部网络访问设置允许列表与输入校验。
- [ ] 写操作、权限变更、任务执行和异常访问可通过审计与结构化日志追溯。

## 运行时与供应链

- [ ] 沙盒与 Worker 使用非 root 用户、资源限制、专用网络和最小挂载。
- [ ] 生产镜像固定版本或 digest，并完成漏洞扫描；不要只使用可变的 `latest` 标签。
- [ ] Python、Node、容器基础镜像和运行时工具定期更新，并在预发布环境运行迁移和业务冒烟测试。
- [ ] 已完成数据库、用户数据、知识库和配置的备份及恢复演练。
- [ ] 监控错误率、认证异常、资源耗尽和队列积压，并建立事故响应联系人和回滚路径。

## 发布后验证

```bash
make check-migrations
make check-alembic-heads
make wait-web
make sync-knowledge
```

这些命令不能替代渗透测试或组织安全审计；高风险变更应经过独立评审。
