# OmicHub JBrowse 2 基因组浏览器集成实现指南

> 目标：将 JBrowse 2 嵌入 OmicHub 平台，支持外置 YAML 配置、自动扫描用户目录、网页上传文件。
> 作者：Kimi
> 说明：本指南提供完整代码框架，供 CC 优化和适配现有架构。

---

## 目录

1. [项目结构规划](#1-项目结构规划)
2. [JBrowse 2 下载与部署](#2-jbrowse-2-下载与部署)
3. [外置 YAML 配置系统](#3-外置-yaml-配置系统)
4. [FastAPI 后端实现](#4-fastapi-后端实现)
5. [Celery 异步任务](#5-celery-异步任务)
6. [Vue 3 前端组件](#6-vue-3-前端组件)
7. [Nginx 配置](#7-nginx-配置)
8. [Docker Compose 调整](#8-docker-compose-调整)
9. [数据管理模块打通](#9-数据管理模块打通)
10. [部署检查清单](#10-部署检查清单)

---

## 1. 项目结构规划

```
omichub/
├── pipelines/
│   └── jbrowse2/                    # JBrowse 2 静态产物 (下载至此)
│       ├── index.html
│       ├── static/
│       └── ...
│
├── src/
│   ├── backend/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── jbrowse.py       # FastAPI 路由
│   │   ├── core/
│   │   │   └── jbrowse_config.py  # YAML 配置加载器
│   │   ├── services/
│   │   │   └── jbrowse_service.py  # 业务逻辑
│   │   └── tasks/
│   │       └── jbrowse_tasks.py   # Celery 异步任务
│   │
│   └── frontend/
│       └── src/
│           └── views/
│               └── tools/
│                   └── JBrowseViewer.vue  # 前端页面
│
├── config/
│   └── jbrowse_config.yaml          # 外置配置文件
│
└── scripts/
    └── download_jbrowse2.sh         # 一键下载脚本
```

---

## 2. JBrowse 2 下载与部署

### 2.1 下载脚本

执行 `scripts/download_jbrowse2.sh`：

```bash
#!/bin/bash
# scripts/download_jbrowse2.sh
# 一键下载 JBrowse 2 Web 产物到 pipelines/jbrowse2/

set -e

VERSION="2.15.1"
TARGET_DIR="pipelines/jbrowse2"
URL="https://github.com/GMOD/jbrowse-components/releases/download/v${VERSION}/jbrowse-web-v${VERSION}.zip"

echo "📦 下载 JBrowse 2 v${VERSION}..."

mkdir -p ${TARGET_DIR}
cd ${TARGET_DIR}

# 下载并解压
wget -q --show-progress ${URL} -O jbrowse.zip
unzip -q -o jbrowse.zip
rm jbrowse.zip

echo "✅ JBrowse 2 已部署到 ${TARGET_DIR}/"
echo "📁 文件列表:"
ls -la
```

### 2.2 手动执行

```bash
chmod +x scripts/download_jbrowse2.sh
./scripts/download_jbrowse2.sh
```

---

## 3. 外置 YAML 配置系统

配置文件路径：`config/jbrowse_config.yaml`

（见下方代码文件 `jbrowse_config.yaml`）

### 配置加载器

见 `src/backend/core/jbrowse_config.py`

---

## 4. FastAPI 后端实现

### 4.1 配置加载器

`src/backend/core/jbrowse_config.py`

### 4.2 API 路由

`src/backend/api/v1/jbrowse.py`

### 4.3 业务服务

`src/backend/services/jbrowse_service.py`

---

## 5. Celery 异步任务

`src/backend/tasks/jbrowse_tasks.py`

---

## 6. Vue 3 前端组件

`src/frontend/src/views/tools/JBrowseViewer.vue`

---

## 7. Nginx 配置

在现有 `nginx.conf` 中增加：

```nginx
# JBrowse 2 静态产物
location /jbrowse2/ {
    alias /usr/share/nginx/html/jbrowse2/;
    try_files $uri $uri/ /jbrowse2/index.html;
    expires 30d;
    add_header Cache-Control "public, immutable";
}

# 数据文件访问 (支持 Range Request)
location /tracks/ {
    alias /data/omichub/;
    add_header Access-Control-Allow-Origin *;
    add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS";
    add_header Accept-Ranges bytes;
}

# JBrowse API 反代
location /api/jbrowse/ {
    proxy_pass http://web:8000/api/jbrowse/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

## 8. Docker Compose 调整

### 8.1 nginx 服务增加挂载

```yaml
services:
  nginx:
    volumes:
      # 新增：JBrowse 2 产物
      - ./pipelines/jbrowse2:/usr/share/nginx/html/jbrowse2:ro
      # 新增：数据文件访问
      - /data/omichub:/data/omichub:ro
      # 现有挂载保持不变...
```

### 8.2 新增 volumes (可选)

如需持久化上传的临时文件：

```yaml
volumes:
  jbrowse_uploads:
    driver: local
```

---

## 9. 数据管理模块打通

在「数据管理」模块的文件列表中，增加操作按钮：

- **"在浏览器查看"**：跳转到 JBrowse 页面，自动加载该文件作为轨道
- **"生成索引"**：如果索引文件缺失，触发 Celery 任务生成

前端调用示例：

```javascript
// 从数据管理模块跳转到 JBrowse
const viewInBrowser = (filePath) => {
  const url = `/tools/jbrowse?autoLoad=${encodeURIComponent(filePath)}`;
  window.open(url, '_blank');
};
```

---

## 10. 部署检查清单

- [ ] 执行 `scripts/download_jbrowse2.sh` 下载产物
- [ ] 创建 `config/jbrowse_config.yaml` 并配置参考基因组
- [ ] 确保参考基因组 FASTA 文件已格式化索引 (`.fai`)
- [ ] 将后端代码文件复制到对应目录
- [ ] 在 `main.py` 中注册 `jbrowse` 路由
- [ ] 在 `celery_app.py` 中注册 `jbrowse_tasks`
- [ ] 更新 `nginx.conf` 增加 JBrowse 2 和 `/tracks/` 配置
- [ ] 更新 `docker-compose.yml` 增加挂载
- [ ] 重启 nginx 容器 (`docker compose restart nginx`)
- [ ] 测试访问 `https://your-domain/jbrowse2/`
- [ ] 测试 API `GET /api/jbrowse/assemblies`
- [ ] 测试上传功能
- [ ] 测试自动扫描功能

---

## 附录：索引文件生成命令

```bash
# FASTA 索引
samtools faidx genome.fasta

# BAM 索引
samtools index sample.bam

# VCF 索引
bcftools index -t sample.vcf.gz

# BigWig 无需额外索引
```

---

> 💡 提示：本指南中的代码为完整可运行框架，CC 可根据实际项目结构进行路径调整和细节优化。
