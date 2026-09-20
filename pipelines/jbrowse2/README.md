# JBrowse 2 × CygnusX 集成说明

> 本目录是 **JBrowse 2 Web 构建产物**（v2.15.1，由 `scripts/download_jbrowse2.sh` 从 [GMOD/jbrowse-components](https://github.com/GMOD/jbrowse-components/releases) 下载解压）。本身是一个独立的 SPA（`index.html` + `static/`），CygnusX 并未修改其源码，而是通过 **iframe + 动态配置注入 + nginx 静态托管** 的方式把它「嫁接」进平台。
>
> 本文档说明这套嫁接的完整架构与数据流，便于后续维护、排障与升级 JBrowse 版本。

---

## 1. 一图总览

```
┌─────────────────────────── 浏览器（用户）─────────────────────────────┐
│  CygnusX 前端  Vue 3 + naive-ui                                         │
│  frontend/src/views/BioTools/JBrowseViewer.vue   （路由 /tools/jbrowse）│
│                                                                         │
│   ① apiClient（带 JWT）──► GET /api/v1/jbrowse/config                   │
│                              │  返回 JBrowse 2 配置 JSON                │
│   ② URL.createObjectURL(blob) ── 生成 blob:https://... （绕过 JWT）     │
│   ③ <iframe src="/jbrowse2/?config=<blobUrl>&loc=Chr1:1-2000000">      │
│         │                                              │                │
└─────────┼──────────────────────────────────────────────┼────────────────┘
          │ ① JWT 鉴权                                   │ ④ fetch blob（无 JWT）
          ▼                                              ▼
   ┌───────────────────────┐                ┌────────────────────────────┐
   │  FastAPI web 容器      │                │  nginx 容器                 │
   │  /api/v1/jbrowse/*     │                │                            │
   │  · 列参考基因组/扫描    │                │  /jbrowse2/  ─► /var/www/  │
   │  · 生成 config JSON    │                │                 jbrowse2   │
   │    （defaultSession +  │                │  /tracks/    ─► /data/     │
   │     theme #165DFF）    │                │                 cygnusx    │
   │  · 上传 / 索引管理     │                │    （HTTP Range Request）  │
   └──────────┬─────────────┘                └─────────────┬──────────────┘
              │ ⑤ 投递 Celery 索引任务                      │ ⑥ 流式读取
              ▼                                             ▼
   ┌───────────────────────┐                ┌────────────────────────────┐
   │  Celery worker 容器    │                │  /data/cygnusx/            │
   │  samtools/bcftools/    │ ──写索引──►    │  ref/  tracks/  users/     │
   │  tabix                 │                │  （nginx :ro  web/worker 可写）│
   └───────────────────────┘                └────────────────────────────┘
```

**核心数据流（用户打开浏览器到看到轨道）**：

| 步骤 | 主体 | 动作 |
|----|----|----|
| ① | 前端 → 后端 | `apiClient`（自动附加 JWT）调用 `GET /api/v1/jbrowse/config?assembly=...&tracks=...&region=...` |
| ② | 前端 | 后端返回配置 JSON → **`absolutizeUris(config)` 把所有 `/tracks/...` 补成绝对 URL**（见第 2 节警告）→ `new Blob([JSON.stringify(config)])` → `URL.createObjectURL(blob)` |
| ③ | 前端 | `<iframe src="/jbrowse2/?config=<blobUrl>&loc=<region>">` 挂载 JBrowse 2 SPA |
| ④ | iframe（JBrowse 2） | 同源 fetch 读取 blob 配置（**无需 JWT**，因 blob 属当前 origin） |
| ⑤ | iframe（JBrowse 2） | 按 config 中的 `uri: /tracks/...` 向 nginx 发 **HTTP Range Request** 流式拉取 FASTA/BAM/BigWig/VCF |
| ⑥ | nginx | `/tracks/` alias 到 `/data/cygnusx/`，原生支持 Range，按需返回字节段 |

---

## 2. 为什么是 iframe + blob，而不是 React 组件？

CygnusX 前端是 **Vue 3 + naive-ui**，而 JBrowse 2 官方提供的是 React 组件（`@jbrowse/react-linear-genome-view`）。引入 React 会带来双框架运行时与构建复杂度，且无法解决核心矛盾——**轨道数据的鉴权**：

- JBrowse 2 的所有数据请求（FASTA/BAM/...）由其内部 `fetch` 发起，**无法携带 CygnusX 的 JWT**。
- 若数据走带鉴权的 API 路径，iframe 内的 JBrowse 会全部 401。
- 因此数据必须走一条 **nginx 直出的无鉴权静态路径**（`/tracks/`），而鉴权/归属校验上移到「**配置生成**」这一步：后端只把用户**有权访问**的文件路径写进 config，JBrowse 拿到的 config 已是「白名单」。
- 而配置 JSON 本身需要鉴权（`/jbrowse/config` 要 JWT），所以前端先用带 JWT 的 `apiClient` 取回 JSON，再 `createObjectURL` 交给 iframe——**blob 属当前 origin，iframe 同源可读，从而绕过 JWT**。

这是整套集成最关键的设计决策，所有其它部分都围绕它展开。

> ### ⚠️ blob URL 是 opaque base —— 必须把 uri 绝对化
>
> blob URL 是【opaque / 不能作为 base】的 URL。JBrowse 2 加载 config 时会用 `new URL(uri, configBaseUrl)` 解析每个 `uri` 字段。后端/YAML 里写的是相对路径（`/tracks/ref/human/hg38.fa`），而 configBaseUrl 是 `blob:...` —— 此时 `new URL("/tracks/...", "blob:...")` 会抛 **`TypeError: Failed to construct 'URL': Invalid URL`**，参考序列与轨道全部加载失败，**浏览器只显示 Logo**。
>
> 这是「只显示 Logo」问题的**真正根因**（不是高度塌陷）。修复：在 `URL.createObjectURL` 之前，用 `frontend/src/utils/jbrowse.ts` 的 `absolutizeUris(config)` 递归把所有 `uri` 补成绝对 URL（`window.location.origin + uri`）。绝对 URL 解析时忽略 base，绕开 opaque 限制。两个页面（`JBrowseViewer.vue` 后端配置、`YamlGenomeBrowser.vue` 前端 YAML）都已应用此修复。

---

## 3. 前端集成

| 文件 | 作用 |
|----|----|
| `frontend/src/views/BioTools/JBrowseViewer.vue` | 主页面：工具栏 / 参考基因组选择 / 坐标跳转 / 上传 / 我的文件 / iframe 渲染 |
| `frontend/src/api/jbrowse.ts` | API 封装（`apiClient` 自动附 JWT） |
| `frontend/src/types/jbrowse.ts` | 与后端 schema 对齐的 TS 类型 |
| `frontend/src/router/index.ts` | 路由 `/tools/jbrowse`，**必须带 `meta.fullscreen: true`** |

### 关键实现点

- **自动初始化**：`onMounted` 拉取 assemblies → 选默认基因组 → 自动 `loadBrowser()`，无需用户点按钮。
- **配置注入**：`loadBrowser()` 调 `jbrowseApi.generateConfig()` → `Blob` → `createObjectURL` → 拼接 `&loc=` 写入 iframe `src`。
- **iframe 强制刷新**：每次生成新配置时 `:key="iframeKey"` 自增，强制 Vue 重建 iframe 元素，避免 JBrowse 2 复用 `localStorage` 旧 session 导致只显示 Logo。
- **全高布局**：路由 `meta.fullscreen: true` 让 `DefaultLayout` 给内容区一条有界高度的 flex 链（`flex:1; min-height:0` + native scrollbar），否则 `.browser-view{flex:1}` 不展开 → iframe `height:100%` 塌陷 → **只渲染得出 Logo**（这是最常见的「只显示 Logo」根因，详见第 8 节）。
- **Loading 兜底**：初始化期间 `NSpin` 覆盖层；iframe `@load` 后隐藏；10s 超时则 `Message.error('初始化失败：参考基因组文件可能缺失或格式错误')`。
- **坐标校验**：输入框 `chr1:1000000-2000000`，正则 `/^[A-Za-z0-9_.]+:\d+-\d+$/`，非法则 `Message.error('坐标格式错误...')`。

---

## 4. 后端 API

路由前缀 `/api/v1/jbrowse`（`api/v1/router.py` 注册），全部要求登录（`CurrentUserId`，身份取自 JWT，拒绝 `user_id` 查询参数伪造）；`config/reload` 需管理员。

| 方法 | 路径 | 说明 |
|----|----|----|
| GET | `/assemblies` | 列出所有参考基因组（含 fasta/fai 存在性） |
| GET | `/assemblies/{assembly_id}` | 参考基因组详情 |
| GET | `/config` | **生成 JBrowse 2 配置 JSON**（核心：assembly + tracks + defaultSession + theme） |
| GET | `/scan` | 扫描当前用户目录，发现可加载文件 |
| POST | `/upload` | 上传单个轨道文件（可触发自动索引） |
| POST | `/upload/batch` | 批量上传 |
| GET | `/index/check` | 检查文件索引状态 |
| POST | `/index/create` | 提交 Celery 索引任务 |
| GET | `/index/status/{task_id}` | 查询索引任务状态 |
| GET | `/preset-tracks/{assembly_id}` | 获取某参考基因组的预设轨道 |
| POST | `/config/reload` | **管理员**：强制热重载 YAML 配置 |

### 配置生成（`jbrowse_service.generate_browser_config`）

输出 JSON 形如：

```jsonc
{
  "assemblies": [{
    "name": "rice_nipponbare",
    "aliases": ["IRGSP-1.0"],
    "sequence": {
      "type": "ReferenceSequenceTrack",
      "trackId": "rice_nipponbare-reference",
      "adapter": {
        "type": "IndexedFastaAdapter",
        "fastaLocation": { "uri": "/tracks/ref/rice/IRGSP-1.0_genome.fasta", "locationType": "UriLocation" },
        "faiLocation":   { "uri": "/tracks/ref/rice/IRGSP-1.0_genome.fasta.fai", "locationType": "UriLocation" }
      }
    }
  }],
  "tracks": [ /* 预设轨道 + 用户轨道，uri 均为 /tracks/... */ ],
  "defaultSession": {
    "name": "CygnusX-rice_nipponbare",
    "view": { "id": "linearGenomeView", "type": "LinearGenomeView",
              "tracks": [ /* trackId 列表 */ ],
              "location": { "refName": "Chr1", "start": 1000000, "end": 2000000 } }
  },
  "configuration": {
    "theme": { "palette": { "primary": { "main": "#165DFF" },     // 平台主色
                            "secondary": { "main": "#14C9C9" },
                            "tertiary":  { "main": "#FFB800" } } }
  }
}
```

- **`defaultSession`** 让 JBrowse 2 打开即进入 `LinearGenomeView` 并定位到目标区域，避免停在 Logo 起始页。
- **`configuration.theme`** 把 JBrowse 内部主题色对齐到 CygnusX 主色 `#165DFF`。
- **adapter 映射**（`ADAPTER_MAP`）：`.bam→BamAdapter`、`.cram→CramAdapter`（需 `sequenceAdapter`）、`.bw/.bigwig→BigWigAdapter`、`.vcf.gz→VcfTabixAdapter`、`.bed.gz→BedTabixAdapter`、`.gff3.gz→Gff3TabixAdapter`。

### URI 换算（`to_tracks_uri`）

后端配置里写的是容器**绝对路径**（`/data/cygnusx/ref/rice/x.fasta`），生成给 JBrowse 的 `uri` 时由 `to_tracks_uri()` 换算成 `/tracks/ref/rice/x.fasta`。`data_root` 取自 `storage_config`（与 `CygnusX.yaml` 单一数据源），路径不在 `data_root` 下时退化为只保留文件名，避免泄漏目录结构。

---

## 5. 配置系统（`tools/jbrowse/jbrowse_config.yaml`）

外置 YAML，路径由 `settings.jbrowse_config_yaml` 决定（默认 `tools/jbrowse/jbrowse_config.yaml`，集中配置于 tools/，容器内经 tools/ 挂载 `:ro` 可读）。结构（pydantic v2 校验，`infrastructure/config/jbrowse_config.py`）：

| 段 | 作用 |
|----|----|
| `assemblies` | 参考基因组列表：`id / name / species / fasta / fai / aliases` |
| `preset_tracks` | 按 `assembly_id` 分组的预设（公共）轨道：`name / file / index / type / color` |
| `auto_scan` | 用户目录自动扫描：`scan_paths`（支持 `{user_id}` 模板）/ `extensions` / `auto_index` |
| `upload` | 上传策略：`upload_dir` / `max_file_size`（GB）/ `allowed_types` / `auto_index_after_upload` |
| `defaults` | `default_assembly` / `default_region` / `track_height` / `show_labels` |

**热重载**：`ConfigManager` 单例按文件 `mtime` 判定是否重新解析；文件缺失/字段非法时回退内置默认空配置（**绝不抛异常**，浏览器降级为「无可用基因组」空状态，不影响平台其它功能）。改完 YAML 后调 `POST /api/v1/jbrowse/config/reload` 立即生效，或等 mtime 自动触发，**无需重启后端**。

> 新增参考基因组：在 `assemblies` 下追加一项即可，无需改代码。

---

## 6. nginx 路由（`deploy/docker/nginx/nginx.conf`）

```nginx
# JBrowse 2 静态产物（webpack 打包的 hash 化 JS/CSS）。
# 必须用 ^~ 前缀，否则下方正则 \.(js|css|...)$ 会抢占 /jbrowse2/static/*.js 导致 404。
location ^~ /jbrowse2/ {
    alias /var/www/jbrowse2/;
    try_files $uri $uri/ =404;
    expires 30d;
    add_header Cache-Control "public, immutable";
}

# 数据文件（FASTA/BAM/BigWig/VCF 等）。JBrowse 2 通过 HTTP Range Request 流式读取，
# nginx 原生支持 Range。
location ^~ /tracks/ {
    alias /data/cygnusx/;
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Range, Content-Type" always;
    add_header Accept-Ranges bytes always;
    # 公网部署时取消注释做 IP 白名单：
    # allow 10.0.0.0/8; allow 172.16.0.0/12; allow 192.168.0.0/16; deny all;
}
```

**为什么挂到 `/var/www/jbrowse2` 而不是 `/usr/share/nginx/html/jbrowse2`？**
`/usr/share/nginx/html` 是前端 dist 的**只读 bind mount**，Docker 无法在其下创建新的子挂载点（OCI read-only filesystem 错误）。所以挂到独立路径 `/var/www/jbrowse2`，nginx alias 跟着改。

---

## 7. 索引（Celery）

- 任务：`infrastructure/celery_app/tasks/jbrowse.py` 的 `index_file`。
- 工具：`samtools`（BAM/CRAM → `.bai`/`.crai`）、`bcftools`（VCF.gz → `.tbi`）、`tabix`（bed.gz/gff3.gz → `.tbi`）。
- 二进制缺失时 `shutil.which` 拦截并返回失败，**不重试**。
- 触发方式：上传时 `auto_index`、`POST /index/create`、前端「我的文件」面板的「创建索引」按钮。
- ⚠️ 改 task 代码后必须 `docker restart cygnusx-worker`（Celery worker 不热重载，`docker exec` 看的是磁盘不是进程内存）。

---

## 8. 安全模型

| 层 | 机制 |
|----|----|
| 配置生成 | 后端对用户提交的轨道路径做**归属校验**（`ensure_user_owned`）：只允许 `/data/cygnusx/users/{user_id}/` 下的文件，拒绝越权读取他人数据。`/tracks/` 虽静态暴露，但配置层不协助越权。 |
| 数据读取 | `/tracks/` 对**所有能访问 nginx 的客户端开放** `/data/cygnusx/` 下文件（无鉴权）。私有内网部署可接受；**公网部署必须启用 IP 白名单**或改用带鉴权的代理路径。 |
| API | 全部 JWT 鉴权，`user_id` 取自 JWT subject，不接受查询参数伪造。 |
| 只读校验 | `check_index_status` 等只读操作走 `ensure_under_data_root`（下限校验，禁止任意路径探测）。 |

---

## 9. 部署与升级

### 首次部署 / 升级 JBrowse 版本

```bash
# 1. 下载/更新本目录的 JBrowse 2 构建产物（改 scripts/download_jbrowse2.sh 里的 VERSION）
./scripts/download_jbrowse2.sh

# 2. 重建 nginx 容器以加载 volume（必须 up -d 重建，restart 不够）
docker compose -f deploy/docker/docker-compose.yml up -d nginx
# 生产环境用 docker-compose.prod.yml
```

### docker volume 挂载（`docker-compose.yml`）

```yaml
nginx:
  volumes:
    - ../../pipelines/jbrowse2:/var/www/jbrowse2:ro   # 本目录 → /jbrowse2/
    - /data/cygnusx:/data/cygnusx:ro                   # 数据 → /tracks/
    - ../../frontend/dist:/usr/share/nginx/html:ro     # 前端 SPA
```

### 前端改动后

改了 `JBrowseViewer.vue` 等前端代码，需**重新构建前端**（nginx 服务的是构建产物 `dist`），且若 `rm -rf dist` 重建后需 `restart nginx`（bind mount 指向旧空 inode 问题，参见项目记忆 `nginx-bind-mount-rmrf-dist`）。

---

## 10. 常见问题（Troubleshooting）

| 症状 | 排查 |
|----|----|
| **页面只显示 JBrowse Logo，无基因组视图** | ① **首选查**：config 是否在 blob 前调了 `absolutizeUris`（blob 是 opaque base，相对 `/tracks/` uri 会抛 `Invalid URL`，这才是「只显示 Logo」的真正根因，控制台可见 TypeError）；② 路由 `meta.fullscreen: true` 是否丢失（导致 iframe 高度塌陷，是次因）；③ iframe `:key` 是否生效（避免旧 session）；④ 清浏览器 localStorage 后重试。 |
| **轨道数据 404** | 打开 DevTools Network，看 JBrowse 对 `/tracks/...` 的请求是否 200。404 → 文件不在 `/data/cygnusx/` 下或 nginx alias 错；403 → 检查 IP 白名单。 |
| **`/jbrowse2/static/*.js` 404** | nginx `location ^~ /jbrowse2/` 必须用 `^~` 前缀，否则被 `\.(js|css)$` 正则抢占。 |
| **FASTA 加载失败 / 无序列** | 检查 `.fai` 是否存在且与 FASTA 匹配；缺索引用「创建索引」或 `POST /index/create`。 |
| **改了 YAML 不生效** | 调 `POST /api/v1/jbrowse/config/reload`；或确认 mtime 变了（编辑器 `:w` 会更新 mtime）。 |
| **改了 Celery task 不生效** | `docker restart cygnusx-worker`（worker 不热重载）。 |
| **初始化一直转圈** | 看 Console 是否有 `[JBrowse]` 日志；10s 超时会提示「参考基因组文件可能缺失或格式错误」。 |

---

## 11. 关键文件索引

| 层 | 文件 |
|----|----|
| 前端页面 | `frontend/src/views/BioTools/JBrowseViewer.vue` |
| 前端 API | `frontend/src/api/jbrowse.ts` |
| 前端类型 | `frontend/src/types/jbrowse.ts` |
| 前端路由 | `frontend/src/router/index.ts`（`tools/jbrowse`，`fullscreen: true`） |
| 后端 API | `src/cygnusx/api/v1/jbrowse.py` |
| 后端服务 | `src/cygnusx/application/services/jbrowse_service.py` |
| 后端 Schema | `src/cygnusx/application/schemas/jbrowse.py` |
| 配置加载器 | `src/cygnusx/infrastructure/config/jbrowse_config.py` |
| 索引任务 | `src/cygnusx/infrastructure/celery_app/tasks/jbrowse.py` |
| 平台配置 | `tools/jbrowse/jbrowse_config.yaml` |
| nginx | `deploy/docker/nginx/nginx.conf` |
| 下载脚本 | `scripts/download_jbrowse2.sh` |
| **本构建产物** | `pipelines/jbrowse2/`（即本目录，v2.15.1） |

---

## 12. 本目录内容

```
pipelines/jbrowse2/
├── index.html            # JBrowse 2 SPA 入口（引用 static/js/main.<hash>.js）
├── static/               # webpack 打包的 JS/CSS/字体（hash 化，可长缓存）
├── asset-manifest.json   # 资源清单
├── favicon.ico
├── manifest.json
├── robots.txt
├── umd_plugin.js
├── version.txt           # 2.15.1
└── test_data/            # JBrowse 官方测试数据（生产可删）
```

> 本目录由脚本下载生成，**不要手动改 `index.html` / `static/`**（升级时会被覆盖）。平台定制全部通过后端 config 注入与前端 iframe 包装实现，与 JBrowse 源码解耦。
