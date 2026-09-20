# AgentTeams K8s 部署资产

本目录是 AgentTeams 的正式部署形态，与官方生产部署同构（Bridge + Worker + Matrix Gateway + Tuwunel homeserver）。开发验证仍用 `../matrix-dev/` 的 Synapse + Element Web compose，两者不要混用：

| 场景 | 资产 | Homeserver |
|---|---|---|
| 本机开发/联调 | `../matrix-dev/docker-compose.yml` | Synapse（一次性数据目录） |
| 正式部署 | 本目录清单 | Tuwunel（conduwuit 系，RocksDB 单文件存储） |

## 清单构成

- `bridge-cluster.yaml`：Bridge + 各 Worker Deployment/HPA（既有）。
- `gateway.yaml`：Matrix Gateway Deployment/Service/PDB + ConfigMap/Secret 模板。Gateway 是 CygnusX 侧唯一持有 Matrix 凭证（AppService token）的进程，镜像由 `integrations/agentteams/gateway/Dockerfile` 构建（当前默认 tag：`cygnusx-agent-gateway:v0.0.2dev`，可通过 `.env` 的 `CYGNUSX_IMAGE_TAG` 统一调整）。
- `tuwunel.yaml`：Tuwunel homeserver Deployment（单副本 + Recreate，RWO PVC）+ Service + ConfigMap + AppService 注册文件 Secret 模板。
- `network-policy.default-deny.yaml` / `network-policy.runtime.yaml`：默认拒绝 + Bridge/Worker/Gateway/Tuwunel 的精确放行。

## 部署顺序与配置联动

1. `kubectl apply -f network-policy.default-deny.yaml`（如未启用）。
2. 替换 `tuwunel.yaml` 中 `TUWUNEL_SERVER_NAME` 与 AppService 注册文件的 `as_token`/`hs_token`/users 正则域名；注册文件 users 正则必须覆盖静态身份（bioops-manager、agent-*、cygnusx-user）与动态平台用户账号 `cygnusx-user-*`。
3. `gateway.yaml` 的 `GATEWAY_MATRIX_SERVER_NAME`、`GATEWAY_MATRIX_IDENTITIES` 域名部分必须与 `TUWUNEL_SERVER_NAME` 一致；`GATEWAY_MATRIX_SERVICE_TOKEN` 必须等于注册文件的 `as_token`。
4. `GATEWAY_ELEMENT_BASE_URL` 指向对外可访问的 Element Web（建房后该地址以 `#/room/{room_id}` 深链随 `room.created` 事件下发给前端，用于房间页 iframe 嵌入）；Element Web 本身不在本目录资产内，可复用 matrix-dev 的 Element 或独立部署，生产需自行去掉 `X-Frame-Options` 或改为允许平台来源（matrix-dev 的 `nginx-no-xfo.conf` 是参考实现）。
5. `kubectl apply -f tuwunel.yaml -f gateway.yaml -f network-policy.runtime.yaml`。

## 镜像与国内加速

- `jevolk/tuwunel` 为第三方镜像，不适用本仓库 Dockerfile 换源规范（IMSA，`Protocol/镜像构建国内加速规范_v1.md`）；国内环境拉取缓慢时按 IMSA 总原则在集群级配置 registry mirror 或预先导入内网镜像仓库，并将清单中的 image 改为内网地址（建议钉版 tag，不要长期使用 `latest`）。
- Gateway 镜像为本仓库自构建，其 Dockerfile 遵循 IMSA 的 pip 换源约定。

## 安全姿态

全部容器遵循与 `bridge-cluster.yaml` 一致的基线：`runAsNonRoot` + 数字 uid、`readOnlyRootFilesystem`、`drop: ["ALL"]`、`seccompProfile: RuntimeDefault`、资源 requests/limits。Tuwunel 官方镜像未声明非 root 用户，清单以 uid 10001 + `fsGroup` 运行（数据库目录经 PVC 挂载可写）；若上游镜像未来强制 root，请优先构建内网镜像而非放开 `runAsNonRoot`。

## 已知限制

- Tuwunel 为有状态单副本（RocksDB 嵌入式存储，PVC 为 RWO），滚动升级即短暂中断；扩副本前必须迁移到外部数据库形态。
- Gateway 审计 JSONL 落在 emptyDir（随 Pod 生命周期），需要长期留存时改挂 PVC。
- Element iframe 内发言需用户持有可登录的 Matrix 账号；AppService 供给的 `cygnusx-user-*` 账号无密码，面向终端用户的 Element 登录（SSO/token 下发）是后续项。
