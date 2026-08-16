# 生产环境检查清单

部署到生产前逐项确认：

- [ ] `APP_ENV=production`、`APP_DEBUG=false`
- [ ] `JWT_SECRET_KEY`、`APP_SECRET_KEY`、`REDIS_PASSWORD`、`AI_PROVIDER_KEY_ENCRYPTION_KEY` 已设置且非默认值
- [ ] `OMICHBUB_INIT_ADMIN_PASSWORD` 为强密码
- [ ] 数据库端口在 `docker-compose.prod.yml` 中关闭
- [ ] Redis 端口在 `docker-compose.prod.yml` 中关闭
- [ ] Flower 服务 `replicas: 0`
- [ ] SSL 证书已挂载到 nginx
- [ ] `/tracks/` 仅允许受信内网访问
- [ ] 沙盒容器网络隔离：`SANDBOX_NETWORK_ISOLATED=true`
- [ ] 聊天附件按用户隔离
- [ ] `pip-audit` 无高危以上漏洞

## 关键环境变量

| 变量 | 要求 |
|---|---|
| `JWT_SECRET_KEY` | ≥32 字节随机字符串 |
| `APP_SECRET_KEY` | 随机字符串 |
| `REDIS_PASSWORD` | 强密码 |
| `AI_PROVIDER_KEY_ENCRYPTION_KEY` | Fernet 32 字节 base64，设置后不可更改 |
| `OMICHBUB_INIT_ADMIN_PASSWORD` | 强密码 |

## 保存时 401 排障

如果你在「AI 模型配置」或其他管理页点击保存时看到：

```text
生成失败: 请求失败 (401): {"detail":"令牌无效或已过期"}
```

这通常不是模型秘钥问题，而是当前登录态失效：

- 浏览器里的 `access_token` / `refresh_token` 已过期
- 账号的 `token_version` 被管理员操作提升，旧 token 自动失效
- 多实例部署时 `JWT_SECRET_KEY` 不一致，导致某些请求解不出同一批 token

建议按下面顺序排查：

1. 先退出登录并重新登录，再重试保存
2. 检查生产环境所有 `web` 实例是否共用同一份 `JWT_SECRET_KEY`
3. 检查最近是否有重置密码、禁用/启用账号、修改角色等会提升 `token_version` 的操作
4. 如果刚重启或扩容过，确认新实例拿到的 `.env` / Secret 与旧实例一致

如果是 AI Provider 保存页，前端现在会把这类 401 明确提示为“请重新登录后再保存”，避免误报成秘钥失效。
