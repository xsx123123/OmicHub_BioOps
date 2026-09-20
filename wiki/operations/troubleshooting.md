# 问题排查

## 登录后页面空白

- 浏览器强制刷新 `Ctrl+Shift+R`
- 检查 `docker logs cygnusx-web`
- 确认 nginx 挂载最新 `frontend/dist`，执行 `make docker-reload`

## 上传文件失败

- 检查 Nginx/后端上传大小限制
- 大文件建议通过服务器本地拷贝
- 检查 `/data/cygnusx/uploads` 权限

## 任务一直等待中

- Worker 栈是否已启动：`make docker-up-worker`
- Redis 是否可连接：`docker logs cygnusx-cache`
- Worker 日志是否有报错：`make docker-logs-worker`

## 任务运行失败

查看任务详情「实时日志」，重点检查：

- 输入文件路径是否正确
- 样本信息是否完整（分组、配对）
- 参考基因组是否已配置
- 工作目录磁盘空间
- Conda 环境/容器镜像是否包含所需软件

## Worker 镜像或 Snakemake 启动失败

修改了 `deploy/docker/Dockerfile.worker` 或 `deploy/docker/worker-entrypoint.sh` 后，必须重新构建 Worker 镜像：

```bash
make docker-build-worker
```

确认镜像中的工具和 Snakemake logger 可以加载：

```bash
docker run --rm cygnusx-worker:dev snakemake --version
docker run --rm --entrypoint /bin/sh cygnusx-worker:dev -c 'id; getent passwd 1000'
```

预期运行身份为 `uid=1000(cygnusx)`。若出现 `KeyError: getpwuid(): uid not found: 1000`，说明正在使用旧镜像；重新执行 `make docker-build-worker` 后再启动 Worker：

```bash
make docker-up-worker
```

若构建在读取 `docker/dockerfile:1` 时出现 BuildKit 的 `failed size validation`，请确认 Worker Dockerfile 没有恢复 `# syntax=docker/dockerfile:1`，并清理可回收的构建缓存后重试：

```bash
docker builder prune
make docker-build-worker
```

> `docker builder prune` 会删除未使用的构建缓存，不会删除正在运行的容器。

## Worker 交互终端

```bash
docker exec -it cygnusx-worker zsh
docker run --rm -it cygnusx-worker:dev bash
```

后一个命令中的交互式裸 `bash` 会自动进入 Zsh，并可使用 `btop`。若仅需执行 Bash 脚本，使用 `bash -c '...'`，入口脚本不会切换 shell。

## 数据库相关 500 错误

```bash
make check-alembic-heads
```

若存在 Multiple Heads：

```bash
make migrate-merge
```

## 权限事故

如果登录页提示系统内部错误，且日志报 `/app/logs/cygnusx.log` 权限错误：

```bash
make docker-fix-permissions
docker restart cygnusx-web cygnusx-worker cygnusx-beat
```

## AI 助手无法回复

- 确认已配置 AI Provider（`data/ai/providers.yaml` 或 `.env`）
- 检查网络能否访问模型 API
- 查看后端日志中的 API 调用失败记录
- 若问题是“知识库没有答案”，确认目标文档已登记或位于 `wiki/`，然后执行 `make sync-knowledge`；
  需要时再执行 `make knowledge-reindex`
- 检查当前 Agent、Skill、MCP 和协作能力是否已被部署配置及用户权限启用；不要把未启用功能当成
  Provider 故障
