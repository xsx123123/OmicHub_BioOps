# matrix-dev:本机开发用 Matrix + Element(非正式部署)

仅用于本地打通 AgentTeams 协作聊天室链路,**不是正式部署形态**。正式控制面
(Tuwunel Matrix / Element Web / MinIO / Higress)走 K8s 官方 Helm chart,
见 `docs/26.8.1/agent_Case.md` 第 6 节。

## 启动步骤

```bash
# 1. 生成 Synapse 配置(server_name=localhost)
docker run --rm \
  -v "$PWD/deploy/agentteams/matrix-dev/synapse-data:/data" \
  -e SYNAPSE_SERVER_NAME=localhost -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest generate

# 2. 从 element-web 镜像提取 nginx 配置并去掉 X-Frame-Options(允许 CygnusX iframe 嵌入)
docker run --rm vectorim/element-web:latest cat /etc/nginx/nginx.conf \
  | sed '/X-Frame-Options/d' > deploy/agentteams/matrix-dev/nginx-no-xfo.conf

# 3. 启动
docker compose -f deploy/agentteams/matrix-dev/docker-compose.yml up -d

# 4. 创建用户并建房间(见 setup 一节)
```

## 账号与房间

已在 2026-08-01 初始化:

- 用户:`bioops`,密码存于本目录 `.bioops-password`(chmod 600,仅开发用)
- 房间:BioOps 团队公共房间,room_id 存于本目录 `.room-id`
- Element 地址已写入根目录 `.env` 的 `AGENTTEAMS_ELEMENT_URL`(`http://localhost:8081/#/room/...`)
- `.bioops-password`、`.room-id`、`synapse-data/`、`nginx-no-xfo.conf` 均为本地生成物,不要提交

## 边界

- 只绑定 127.0.0.1(Synapse 8008 / Element 8081)
- 与 CygnusX 主栈、Bridge 无网络互通需求:浏览器直接访问 localhost 上的 Element
- 拆除:`docker compose -f deploy/agentteams/matrix-dev/docker-compose.yml down -v && rm -rf deploy/agentteams/matrix-dev/synapse-data`
