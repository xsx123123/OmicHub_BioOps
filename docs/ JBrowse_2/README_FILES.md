# ============================================================
# CygnusX JBrowse 2 集成 — 文件清单
# ============================================================

## 📁 生成的文件列表

| 文件名 | 说明 | 目标路径 |
|--------|------|----------|
| `implementation_guide.md` | 完整实现指南文档 | 项目根目录 |
| `jbrowse_config.yaml` | 外置 YAML 配置文件模板 | `/data/cygnusx/config/` |
| `download_jbrowse2.sh` | JBrowse 2 一键下载脚本 | `scripts/` |
| `jbrowse_config.py` | 配置加载器（Pydantic 模型 + 热重载） | `src/backend/core/` |
| `jbrowse_service.py` | 业务服务层（配置生成 + 文件扫描 + 索引检查） | `src/backend/services/` |
| `jbrowse_api.py` | FastAPI 路由（9 个 API 端点） | `src/backend/api/v1/` |
| `jbrowse_tasks.py` | Celery 异步任务（索引生成 + 目录扫描 + 清理） | `src/backend/tasks/` |
| `JBrowseViewer.vue` | Vue 3 前端页面（Arco Design） | `src/frontend/src/views/tools/` |
| `nginx_jbrowse.conf` | Nginx 配置片段 | 插入到现有 `nginx.conf` |
| `docker-compose-jbrowse.yml` | Docker Compose 调整片段 | 合并到现有 `docker-compose.yml` |

## 🚀 快速部署步骤（给 CC 的 checklist）

### 第一步：下载 JBrowse 2
```bash
chmod +x scripts/download_jbrowse2.sh
./scripts/download_jbrowse2.sh
```

### 第二步：配置文件
1. 将 `jbrowse_config.yaml` 复制到 `/data/cygnusx/config/jbrowse_config.yaml`
2. 根据实际数据修改参考基因组路径和预设轨道
3. 确保参考基因组 FASTA 已索引：`samtools faidx genome.fasta`

### 第三步：后端代码
1. 将 `jbrowse_config.py` 复制到 `src/backend/core/`
2. 将 `jbrowse_service.py` 复制到 `src/backend/services/`
3. 将 `jbrowse_api.py` 复制到 `src/backend/api/v1/`
4. 将 `jbrowse_tasks.py` 复制到 `src/backend/tasks/`
5. 在 `main.py` 中注册路由：`app.include_router(jbrowse.router, prefix="/api/v1")`
6. 在 Celery app 中导入 `jbrowse_tasks`

### 第四步：前端代码
1. 将 `JBrowseViewer.vue` 复制到 `src/frontend/src/views/tools/`
2. 在路由配置中增加 `/tools/jbrowse` 路径
3. 在「生信工具箱」页面中，「序列检索 BLAST」旁边增加「Web 基因组浏览器」卡片

### 第五步：基础设施
1. 将 `nginx_jbrowse.conf` 内容插入到现有 `nginx.conf`
2. 将 `docker-compose-jbrowse.yml` 内容合并到现有 `docker-compose.yml`
3. 重启 Nginx：`docker compose restart nginx`

### 第六步：验证
1. 访问 `https://your-domain/jbrowse2/` 确认 JBrowse 2 加载
2. 访问 `GET /api/jbrowse/assemblies` 确认 API 正常
3. 在页面中选择参考基因组，加载浏览器
4. 测试上传功能
5. 测试从「数据管理」模块跳转

## 🔧 关键 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jbrowse/assemblies` | 列出所有参考基因组 |
| GET | `/api/jbrowse/config` | 生成 JBrowse 2 配置 JSON |
| GET | `/api/jbrowse/scan` | 扫描用户目录 |
| POST | `/api/jbrowse/upload` | 上传文件 |
| POST | `/api/jbrowse/upload/batch` | 批量上传 |
| GET | `/api/jbrowse/index/check` | 检查索引状态 |
| POST | `/api/jbrowse/index/create` | 创建索引（异步） |
| GET | `/api/jbrowse/index/status/{task_id}` | 查询索引任务状态 |
| POST | `/api/jbrowse/config/reload` | 热重载 YAML 配置 |

## 📝 注意事项

1. **路径映射**：容器内路径和宿主机路径可能不同，确保 `/data/cygnusx` 在容器内可访问
2. **索引文件**：BAM 需要 `.bai`，VCF.gz 需要 `.tbi`，FASTA 需要 `.fai`，上传后会自动触发索引
3. **Nginx 配置**：`/tracks/` 路径暴露数据文件，建议加 IP 限制或认证
4. **Range Request**：`Accept-Ranges bytes` 对大文件浏览至关重要，Nginx 配置中必须保留
5. **Celery 任务**：索引生成可能耗时较长（大 BAM 文件），已配置 1 小时软超时

## 🎯 后续优化建议（供 CC 参考）

- [ ] 添加用户认证集成（替换 `getUserId()` 占位符）
- [ ] 添加管理员接口管理参考基因组（动态增删改 YAML）
- [ ] 添加轨道预设模板（不同物种常用轨道一键加载）
- [ ] 添加 JBrowse 2 与 iframe 的 postMessage 通信（实现区域同步）
- [ ] 添加文件预览缩略图（BAM 覆盖度概览）
- [ ] 添加多参考基因组比较视图（JBrowse 2 支持）

## 💡 设计亮点

- **外置 YAML**：新增参考基因组无需改代码，改配置文件即可
- **自动扫描**：用户目录下的文件自动发现，无需手动注册
- **自动索引**：上传后自动触发 Celery 索引任务，用户无感知
- **热重载**：配置变更后调用 `/api/jbrowse/config/reload` 立即生效
- **URL 状态同步**：浏览器状态保存在 URL 中，方便分享和刷新恢复
