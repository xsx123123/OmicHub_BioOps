# BioReport: 标准化生物信息分析报告生成系统

**BioReport** 是一个基于 Python 和 Quarto 的自动化报告生成框架，旨在将生物信息学标准分析流程（如 RNA-seq）的结果转化为交互式、美观的 HTML 报告，并支持一键云端部署。

## 🏗 核心架构 (Architecture)

本系统采用 **"Copy-Inject-Render"** (复制-注入-渲染) 的工程模式，而非简单的单文件模板渲染。

### 理想工作流

1.  **Initialize (初始化)**: 为每次分析创建一个独立的构建目录 (Build Workspace)。
2.  **Clone (克隆)**: 将 `templates/RNA_Project/` 的完整结构（包含 `_quarto.yml`, `theme/`, `logo/`）复制到构建目录。
3.  **Inject (注入)**:
    *   **数据**: 将上游分析产生的 MultiQC 数据、图片复制到构建目录的 `data/` 中，覆盖模板占位符。
    *   **配置**: 使用 Jinja2 修改 `_quarto.yml` (如项目标题、Logo路径) 和 `*.qmd` 文件中的动态文本。
4.  **Build (构建)**: 在构建目录中执行 `quarto render`，生成静态 HTML 站点。
5.  **Deploy (部署)**: 将构建产物推送到 Nginx 服务器。

## 📂 目录结构 (Directory Structure)

```text
bioreport/                  # 项目根目录
├── bioreport/              # 核心代码包
│   ├── ai/                 # AI 智能解读模块实现
│   │   ├── cli.py          # 命令行入口
│   │   ├── engine.py       # 推理引擎 (容错/成本/截断)
│   │   └── wrapper.py      # 业务逻辑封装
│   ├── core.py             # 核心渲染逻辑
│   ├── loader.py           # 数据加载与搬运
│   └── main.py             # 任务编排
├── data/                   # 数据集中心
│   └── ai_demo/            # AI 解读示例输入数据
├── ai_report/              # AI 报告输出目录 (Log/MD/JSON)
├── templates/              # Quarto 项目模板库
│   └── RNA_Project/        # RNA-seq 交互式报告模板
├── docs/                   # 项目文档
│   └── ai_readme.md        # AI 模块详细技术文档
├── requirements.txt        # 依赖清单
└── README.md               # 项目主说明文档
```

## 🤖 AI 智能解读 (AI Interpretation)

BioReport 集成了生产级的 AI 解读引擎，支持多模态生物信息学数据分析报告的自动化生成。

**核心特性：**

*   **多云架构 (Multi-Provider)**: 同时支持 **火山引擎 (Volcengine/豆包)** 和 **阿里云 (Aliyun/通义千问)**，灵活切换。
*   **高可用保障 (Auto-Fallback)**: 内置自动降级机制，主供应商 API 异常时自动切换备用链路，确保任务成功率。
*   **成本透明 (Cost Estimation)**: 实时计算 Token 消耗并预估资金成本 (CNY)，支持自定义费率配置。
*   **双模日志 (Dual Logging)**: 同时生成 **文本日志 (.log)** 供人工查阅和 **结构化日志 (.json)** 供机器分析。
*   **智能流控**: 内置 Token 预估与智能截断 (Top-N) 策略，防止超出模型上下文限制。

👉 **[查看 AI 模块完整文档 (docs/ai_readme.md)](docs/ai_readme.md)**

## 🚀 部署架构演进 (Deployment Architecture)

本系统规划了从独立交付到平台集成的演进路线。

### 第一阶段：V1 独立交付模式 (Current MVP)

**核心理念**：快速、轻量、无需开发后端。利用 Nginx 自带的 `auth_basic` 模块实现基础的密码保护。

*   **部署方式**：Docker 容器化部署 Nginx。
*   **鉴权方式**：HTTP Basic Auth (浏览器原生弹窗)。
*   **数据管理**：宿主机目录挂载。

**交付流程**:
1.  **渲染**: 本地 `quarto render`。
2.  **上传**: `scp` 到服务器。
3.  **设密**: `htpasswd` 生成密码。
4.  **交付**: 发送链接和密码给客户。

### 第二阶段：V2 平台集成模式 (Future SaaS)

**核心理念**：无感鉴权、统一入口。将静态报告作为子模块嵌入自建 Web 平台，利用平台的账户体系控制访问权限。

*   **架构原理**: 利用 Nginx 的 `auth_request` 模块，将鉴权动作“外包”给 Web 后端 (Django/FastAPI)。
*   **访问流程**:
    1.  用户访问报告页面。
    2.  Nginx 拦截请求 -> 发起内部请求至后端 `/api/check_permission`。
    3.  后端 API 检查 Cookie/Session。
    4.  Nginx 根据返回状态码 (200/403) 决定是否放行。
*   **前端体验**: 用户登录平台后，在项目详情页通过 Iframe 查看报告，实现无缝衔接。

## ⚠️ 关键架构审查 (Critical Review) - 待修复问题

当前代码库 (`main.py`, `deploy.py`, `core.py`) 存在以下阻塞性问题，需在下一阶段开发中优先修复以符合上述架构设计：

### 1. 运行上下文断裂 (Context Disconnect)
*   **现状**: `main.py` 试图渲染单个 `.qmd` 文件到 `output/` 目录；而 `deploy.py` 试图在当前根目录运行 `quarto render`。
*   **问题**: `templates/RNA_Project/_quarto.yml` 定义了相对路径 (`./qmd/`, `./theme/`)。如果在根目录或错误的目录下运行渲染，Quarto 将找不到 CSS 和图片资源，导致构建失败。
*   **修正方案**:
    *   `main.py` 必须创建一个**临时构建目录** (e.g., `work/run_2025_01/`)。
    *   将 `templates/RNA_Project` **完整拷贝** 到该目录。
    *   所有的渲染和 `quarto render` 命令必须在该目录下执行 (cwd)。

### 2. Jinja2 与 Quarto 语法冲突
*   **现状**: 两者都使用 `{{ variable }}`。
*   **风险**: Quarto 的 Shortcodes (如 `{{< include >}}`) 会被 Jinja2 误判为未定义变量而报错。
*   **修正方案**: 在 `bioreport/core.py` 中初始化 Jinja2 环境时，强制修改定界符：
    ```python
    env = Environment(
        variable_start_string='[[', variable_end_string=']]',
        block_start_string='[%', block_end_string='%]'
    )
    ```

### 3. deploy.py 的职责边界
*   **现状**: `deploy.py` 包含渲染逻辑 (`quarto render`)，且硬编码了服务器 IP 和密码生成逻辑。
*   **问题**: 部署脚本不应负责构建，应只负责传输。
*   **修正方案**:
    *   `deploy.py` 应仅接受一个参数：**`--site-dir`** (即 `main.py` 生成的 `_site` 目录)。
    *   敏感信息 (IP, User) 移至 `.env` 文件或环境变量。

## 📅 开发计划 (Roadmap)

### Phase 1: 核心逻辑修正 (Immediate)
- [ ] **重构 `main.py`**: 实现 "Workspace" 模式，不再原位修改或单文件输出。
- [ ] **重构 `deploy.py`**: 剥离构建逻辑，专注于 `scp/ssh` 操作，增加环境变量支持。
- [ ] **配置 Jinja2**: 更改默认定界符，避免与 Quarto 冲突。

### Phase 2: 数据流打通
- [ ] **Loader 增强**: 实现 `shutil.copytree` 逻辑，将 MultiQC 结果从分析目录搬运到构建目录的 `data/`。
- [ ] **JSON Schema**: 定义标准中间数据格式，确保模板渲染的鲁棒性。

### Phase 3: 交付与平台化 (Delivery & Platform)
- [ ] **Docker**: 编写 `Dockerfile`，预装 Python, Quarto, R (ggplot2), Nginx Client。
- [ ] **CLI**: 封装为 `bioreport run --input <dir> --deploy` 形式的命令行工具。
- [ ] **V2 迁移**: 实现后端鉴权 API 接口对接，升级 Nginx 配置以支持 `auth_request`。

---

## 🛠 开发指南

**本地调试模板：**
可以直接在 `templates/RNA_Project/` 目录下运行：
```bash
quarto preview
```
这将启动实时预览服务器，用于调整 CSS 和布局。

**调试生成逻辑：**
请确保 `main.py` 正确执行了“复制模板 -> 替换变量”的流程，检查生成的构建目录结构是否完整。
