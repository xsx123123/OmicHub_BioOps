# OmicHub "AI Copilot 与交互式代码执行沙盒"模块技术栈选型与评估报告

> **文档版本**: v1.0  
> **评估日期**: 2025年7月  
> **评估人**: 技术选型分析团队  
> **项目背景**: 华中农业大学园艺林学学院 - 私有化多组学分析平台  
> **核心约束**: 组内仅1人生信维护，要求极简运维、单服务器部署、并发<20

---

## 目录

1. [前端UI技术选型](#1-前端ui技术选型)
2. [后端调度服务选型](#2-后端调度服务选型)
3. [动态执行沙盒选型（重点）](#3-动态执行沙盒选型重点)
4. [LLM Agent框架选型](#4-llm-agent框架选型)
5. [总结：推荐技术栈总表](#5-总结推荐技术栈总表)

---

## 1. 前端UI技术选型

### 1.1 代码编辑器对比

| 维度 | Monaco Editor (VS Code核心) | CodeMirror 6 | Ace Editor |
|------|---------------------------|--------------|------------|
| **包体积** | ~5MB (gzipped ~2MB)，需懒加载 | ~50-300KB，tree-shakable | ~400KB，不可tree-shake |
| **Vue 3 兼容性** | 需 vue-monaco-editor 包装 | 原生 ESM，Vue 3 无缝集成 | vue3-ace-editor 可用 |
| **TypeScript 支持** | 内置顶级 TS/JS IntelliSense | 需额外 @codemirror/lang-javascript | 基础语法高亮 |
| **Python 语言支持** | 语法高亮+自动补全+诊断 | 语法高亮+基础补全 | 语法高亮 |
| **移动端支持** | 极差，不支持触摸 | 优秀，原生触摸支持 | 一般 |
| **多实例性能** | 多个实例内存占用大 (~64MB each) | 轻量，多实例友好 (~48MB) | 中等 |
| **主题定制** | JS Theme API，VS Code主题兼容 | CSS 变量，灵活轻量 | 预置主题，有限定制 |
| **社区活跃度** | 极高 (Microsoft 维护) | 极高 (Mozilla/Replit 等使用) | 中等，维护缓慢 |
| **学习曲线** | 高，Worker配置复杂 | 中，模块化组装 | 低，API简单 |
| **Vite 集成** | 需特殊 Worker 配置 | 开箱即用 | 简单 |

**评级总结**：

| 方案 | 评级 | 一句话理由 |
|------|------|-----------|
| Monaco Editor | 可用 | 适合需要VS Code完整体验的场景，但包体积大、Vue3集成需额外配置 |
| **CodeMirror 6** | **推荐** | tree-shakable轻量架构与Vue3/Vite生态完美契合，多实例性能优秀，是"产品中嵌入编辑器"的最佳选择 |
| Ace Editor | 不推荐 | 项目维护缓慢，架构陈旧，生态逐渐被CodeMirror 6和Monaco蚕食 |

**选择 CodeMirror 6 的核心理由**：

1. **Vue 3 生态原生契合**：CodeMirror 6 的 ESM 模块化架构与 Vite 的 tree-shaking 完美配合，而 Monaco 需要复杂的 Worker 加载配置
2. **包体积差距悬殊**：基础功能仅 ~50KB vs Monaco ~2MB，对于侧边栏编辑器场景至关重要
3. **多实例友好**：OmicHub 需要同时展示多个代码片段（对话历史中的代码块），CodeMirror 6 的轻量实例更符合需求
4. **触屏支持**：未来可能需要在平板设备上使用
5. **维护简单**：升级通过 npm 即可完成，无需处理 Worker 文件路径问题

---

### 1.2 图表渲染引擎对比

| 维度 | ECharts | Plotly.js | Observable Plot | ScatterGL (大细胞数据) |
|------|---------|-----------|-----------------|----------------------|
| **包体积** | ~800KB (核心)，按需加载 | ~3MB (完整版) | ~200KB | ~100KB (ECharts GL扩展) |
| **UMAP/降维可视化** | scatter GL 支持 100k+ 点 | 原生支持，交互丰富 | 需手动实现 | 专门为大散点优化 |
| **热图 (Heatmap)** | 内置，性能优秀 | 内置，交互强 | 基础支持 | N/A |
| **火山图/MA图** | 可组合实现 | 内置统计图表多 | 可组合 | N/A |
| **交互式操作** | 缩放/平移/刷选/数据区域缩放 | 全交互，工具提示丰富 | 基础交互 | 仅基础交互 |
| **单细胞数据 (10万+细胞)** | ECharts GL scatter 可达 100万点 | 10万点开始卡顿 | 不适合 | WebGL 渲染 |
| **中文文档/社区** | 中文文档极完善 (百度开源) | 英文为主，社区大 | 较小 | 同 ECharts |
| **Vue 3 集成** | vue-echarts 官方组件 | vue-plotly 社区组件 | 需自行封装 | 同 ECharts |
| **导出图片** | 内置 canvas/svg 导出 | 内置导出 | SVG导出 | 同 ECharts |
| **维护状态** | 极活跃 (Apache 2.0) | 活跃 (MIT) | 活跃 | 同 ECharts |

**评级总结**：

| 方案 | 评级 | 一句话理由 |
|------|------|-----------|
| **ECharts + ECharts GL** | **推荐** | 中文文档完善、Vue生态成熟、GL扩展可处理100万+细胞散点，是生信可视化最优解 |
| Plotly.js | 可用 | 统计图表更丰富但包体积大，10万+细胞性能下降明显 |
| Observable Plot | 不推荐 | 适合简单探索，生信复杂图表需大量自定义 |
| ScatterGL (独立) | 备选 | 仅作为ECharts GL的一部分使用，不单独选用 |

**ECharts 生信场景专用配置示例**：

```typescript
// ECharts GL 大细胞散点配置
const option = {
  series: [{
    type: 'scatterGL',
    data: umapData,  // [[x1, y1, cluster1], ...]
    symbolSize: 2,
    itemStyle: { opacity: 0.6 }
  }],
  dataZoom: [
    { type: 'inside', xAxisIndex: 0 },
    { type: 'inside', yAxisIndex: 0 }
  ],
  brush: {
    toolbox: ['rect', 'polygon', 'clear'],
    brushMode: 'multiple'
  }
};
```

---

### 1.3 代码展示UI设计（Claude Artifacts 风格）

参考 Claude Artifacts、Vercel v0、E2B Fragments 的交互模式，针对 OmicHub 场景的定制化设计：

```
+-----------------------------------------------------------+
|  [文件名: analysis.py]              [复制] [编辑] [运行]   |
+-----------------------------------------------------------+
|                                                           |
|  import scanpy as sc                                      |
|  adata = sc.read_h5ad('/data/sample.h5ad')               |
|  sc.pp.neighbors(adata)                                   |
|  sc.tl.umap(adata)                                        |
|                                                           |
+-----------------------------------------------------------+
|  [代码] [结果] [图表] [日志]          [下载结果]          |
+-----------------------------------------------------------+
|  +------------------------+                               |
|  |                        |                               |
|  |   UMAP 散点图          |    <- 结果面板 (ECharts GL)   |
|  |   (WebGL渲染)          |                               |
|  |                        |                               |
|  +------------------------+                               |
|  细胞数: 50,000 | 运行时间: 3.2s | 内存: 1.2GB           |
+-----------------------------------------------------------+
```

**交互面板核心设计决策**：

| 设计决策 | 选择 | 理由 |
|---------|------|------|
| 代码-结果联动 | 标签页切换 (代码/结果/图表/日志) | 参考 Claude Artifacts，380px 侧边栏空间有限 |
| 编辑器模式 | 只读展示 → 点击编辑切换为 CodeMirror 6 | 默认只读节省资源，编辑时激活完整功能 |
| 图表交互 | ECharts 内置 dataZoom + brush | 细胞亚群框选是核心需求 |
| 运行按钮状态 | 空闲→运行中→完成/错误，颜色状态反馈 | 沙盒执行可能需要数秒 |
| 文件下载 | 结果文件（CSV/图片/h5ad）直接下载 | 用户需要导出分析结果 |

---

### 1.4 交互形态对比

| 交互形态 | 描述 | 优点 | 缺点 | 评级 |
|---------|------|------|------|------|
| **侧边栏编辑器** (380px) | 在现有右侧AI对话面板内嵌代码编辑 | 与对话上下文无缝衔接，随时修改 | 屏幕空间受限 | **推荐** |
| 主区域弹窗 (Modal) | 居中弹窗，覆盖全屏 | 编辑空间大，沉浸式 | 打断对话流，上下文丢失 | 可用 |
| 底部面板 (Bottom Panel) | 屏幕下方可拖拽面板 | 类似JupyterLab，空间大 | 需重新布局整个页面 | 复杂 |
| 内联卡片 (Inline Card) | 对话流中直接展开小编辑器 | 最轻量，不离开对话 | 编辑空间极小 | 仅展示 |

**OmicHub 推荐方案**：**侧边栏编辑器为主 + 主区域弹窗为辅**

- **默认状态**：AI 生成的代码在侧边栏以只读卡片展示（带运行按钮）
- **编辑模式**：点击"编辑" → 侧边栏切换为 CodeMirror 6 编辑器，支持修改
- **放大模式**：点击"全屏" → 主区域弹窗打开，获得完整编辑空间
- **结果回显**：运行结果（图表/表格）以标签页形式展示在代码下方

---

### 1.5 前端技术选型最终推荐组合

| 组件 | 推荐选型 | 版本 | 安装命令 |
|------|---------|------|---------|
| **代码编辑器** | CodeMirror 6 | ^6.0.0 | `npm install codemirror @codemirror/lang-python @codemirror/theme-one-dark` |
| **图表渲染** | ECharts 5 + ECharts GL | ^5.5.0 | `npm install echarts vue-echarts` |
| **代码展示UI** | 自定义 Vue 3 组件 (Artifacts 风格) | - | 自建组件 |
| **UI 组件库** | Naive UI (已有) | ^2.38 | 已集成 |
| **状态管理** | Pinia (已有) | ^2.1 | 已集成 |
| **代码Diff** | CodeMirror 6 Merge Extension | ^6.0 | `npm install @codemirror/merge` |

---

## 2. 后端调度服务选型

### 2.1 语言选型：Python (FastAPI) vs Rust

| 维度 | Python (FastAPI) | Rust (Actix/Axum) |
|------|-----------------|-------------------|
| **开发速度** | 极快，团队已有积累 | 慢，需重新学习生态系统 |
| **与现有后端集成** | 同一技术栈，共享模型/工具 | 需单独维护，跨语言调用复杂 |
| **Docker 容器操作** | docker-py SDK 成熟 | shiplift/bollard 可用但生态小 |
| **Jupyter 集成** | jupyter_client 原生支持 | 无原生支持，需 Python 桥接 |
| **性能 (沙盒调度)** | 足够，调度是IO密集型非CPU密集型 | 更高，但优势在调度场景不明显 |
| **维护者数量 = 1** | Python 一人全栈可维护 | Rust 需要专门学习曲线 |
| **生物信息学生态** | scanpy/anndata 等原生 Python | 需通过 PyO3 调用 |
| **编译/部署** | 解释型，热更新 | 需编译，增加部署复杂度 |

**结论：保持 Python FastAPI，不值得为沙盒调度引入 Rust。**

沙盒调度服务的核心 workload 是：**接收 HTTP 请求 → 调用 Docker API → 管理 WebSocket 转发**。这是典型的 **I/O 密集型** 场景，Python asyncio + FastAPI 完全胜任。引入 Rust 带来的性能提升（<10ms 级别）远低于跨语言集成增加的维护成本。

---

### 2.2 Jupyter 集成方案对比

| 维度 | JupyterHub | Jupyter Kernel Gateway | 自定义 Kernel 管理 |
|------|-----------|----------------------|-------------------|
| **架构重量** | 重，多用户Hub + Proxy + Spawner | 中等，独立Kernel网关 | 轻量，直接管理 |
| **用户认证** | 内置完善 | 需额外实现 | 复用 OmicHub 认证 |
| **并发能力** | 强，为教学场景设计 | 中等 | 满足 <20 并发 |
| **与 FastAPI 集成** | 独立服务，耦合困难 | 需适配 | 完全内嵌 |
| **资源占用** | 高（多个进程） | 中等 | 最低 |
| **维护复杂度** | 高（Jupyter 生态版本敏感） | 中等 | 最低，自主可控 |
| **消息协议** | 完整的 Jupyter Msg Spec | 完整的 Jupyter Msg Spec | 可简化为 WebSocket JSON |
| **代码补全** | 内置 | 内置 | 需自行实现 |
| **一人维护** | 不推荐 | 可行但不必要 | 推荐 |

**结论：不引入 JupyterHub/Kernel Gateway，采用自定义轻量 Kernel 管理。**

理由：
1. OmicHub 不需要 Jupyter 的笔记本界面，只需要**代码执行**能力
2. Jupyter 的完整消息协议过于复杂，实际需要只是：发送代码 → 获取输出/图表
3. JupyterHub 的资源占用和维护复杂度对单维护者不可承受
4. **自定义方案**：FastAPI WebSocket 直接转发到 Docker 容器内的 Python 进程，协议简单可控

---

### 2.3 代码执行 API 对比

| 维度 | 直接 Docker API | E2B 自托管 | 自定义容器编排 |
|------|----------------|-----------|--------------|
| **架构复杂度** | 最低，docker-py 直接调用 | 高，需部署 Terraform + 基础设施 | 中等 |
| **启动延迟** | 500ms-2s (冷启动) | <200ms (Firecracker) | 可优化至 <1s (预热池) |
| **安全隔离** | 容器级 namespace/cgroup | 微VM级 (Firecracker) | 同 Docker |
| **数据挂载** | 直接 bind mount 宿主目录 | 需特殊配置 | 直接 bind mount |
| **包安装 (pip/conda)** | 容器内自由安装 | 支持 | 容器内自由安装 |
| **私有化部署** | 单机 Docker Compose 即可 | 自托管路径不被官方支持 | 单机部署 |
| **维护成本** | 最低 | 高，需维护 Firecracker 集群 | 低 |
| **单维护者友好** | 完美 | 不友好 | 友好 |
| **网络访问控制** | Docker 网络隔离 | 内置出站控制 | 自定义 iptables |

**关于 E2B 自托管的重要发现**：

> E2B 的开源 SDK (Apache-2.0) 仅包含客户端 SDK，**核心的 Firecracker 微VM运行时并不开源**。E2B 官方提供的"自托管"选项是通过 Terraform 在云端部署，并非真正的私有化本地部署。官方文档明确说明：*"Only the SDKs are open source. The runtime that runs Firecracker microVMs is a managed cloud service with no self-hosted path."*

**结论：直接 Docker API 调度。**

理由：
1. **数据挂载是刚需**：OmicHub 需要挂载几GB到几十GB的 h5ad/rds 文件，Docker bind mount 是最直接方案
2. **包安装灵活性**：生信分析经常需要安装新的 Bioconda 包，容器内自由 pip/conda 安装至关重要
3. **维护极简**：一人维护场景下，Docker API 是最简单、文档最完善的选择
4. **性能可接受**：通过容器预热池，可将启动延迟控制在 1s 以内

---

### 2.4 会话管理策略对比

| 维度 | 每用户长生命容器 | 每次请求启动新容器 | 预热容器池 |
|------|----------------|-------------------|-----------|
| **启动延迟** | 零延迟（已运行） | 2-5s 冷启动 | <500ms（热启动） |
| **内存占用** | 高（空闲也占用） | 最低（用完即毁） | 中等（池大小可控） |
| **状态持久性** | 变量/导入跨请求保留 | 完全无状态 | 池内容器保留状态 |
| **资源泄漏风险** | 高（长时间运行累积） | 最低 | 可控（定期回收） |
| **并发能力** | 受限于服务器内存 | 高（快速轮换） | 受池大小限制 |
| **安全隔离** | 需定时回收 | 每次全新环境 | 池内定时回收 |
| **实现复杂度** | 低 | 中等 | 中等但最优 |
| **适合场景** | Jupyter Notebook 长期交互 | 无状态API调用 | **OmicHub 最佳平衡** |

**结论：预热容器池 + 会话亲和性 (Session Affinity)。**

**具体策略**：

```
用户发起对话 → 从池中取一个预热的 Python 容器 → 绑定到该用户会话
                ↓
         会话期间容器保持运行（变量/导入保留）
                ↓
         会话超时(30min) → 容器回收至池 或 销毁重建
                ↓
         池大小: 最小5个, 最大15个, 根据并发动态伸缩
```

**推荐参数**：
- 容器池预热数量：5 个（覆盖日常低峰）
- 最大池大小：15 个
- 会话超时：30 分钟无操作后回收
- 内存上限：单个容器 8GB，总容器内存预算 120GB
- CPU 限制：单个容器 4 核

---

### 2.5 后端调度服务最终推荐

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI (已有)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  AI对话API    │  │ 沙盒调度API   │  │ MCP服务API    │       │
│  │ (WebSocket)  │  │ (HTTP/WS)    │  │ (SSE)        │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                   │               │
│  ┌──────▼──────────────────▼───────────────────▼───────┐       │
│  │              沙盒管理器 (SandBoxManager)             │       │
│  │  - 容器池生命周期管理                                │       │
│  │  - WebSocket 消息转发 (前端 <-> 容器内Python)          │       │
│  │  - 会话超时检测与回收                                │       │
│  └──────┬──────────────────────────────────────────────┘       │
│         │                                                      │
│  ┌──────▼──────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Docker API  │  │ Redis (会话)  │  │ Celery (异步) │         │
│  │ (docker-py) │  │ (状态缓存)    │  │ (长任务)      │         │
│  └─────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

**关键设计**：沙盒调度服务作为 FastAPI 的子模块 (sandbox_router.py) 直接集成，**不拆分为独立服务**，降低运维复杂度。


---

## 3. 动态执行沙盒选型（重点）

### 3.1 沙盒方案全维度对比

| 维度 | 方案A: Docker API | 方案B: Jupyter Kernel | 方案C: Firecracker | 方案D: E2B | 方案E: K8s Pod | 方案F: systemd-nspawn |
|------|------------------|----------------------|-------------------|-----------|---------------|---------------------|
| **说明** | Web后端直接Docker API启动容器 | 每用户一个Jupyter Kernel进程 | AWS微虚拟机，强隔离 | E2B托管云/开源SDK | K3s动态创建Pod | 轻量级Linux命名空间容器 |
| **冷启动延迟** | 2-5s | 1-3s | <200ms | <200ms | 5-15s | 1-2s |
| **热启动延迟** | <500ms (预热池) | <100ms (已连接) | N/A (无热启动概念) | N/A | 3-10s | <500ms |
| **内存占用/实例** | 200-500MB | 150-300MB | 50-100MB | 50-100MB | 200-500MB + K8s开销 | 100-200MB |
| **安全隔离级别** | 容器 namespace | 进程级 (需额外隔离) | 微VM级 | 微VM级 | Pod 隔离 | 比Docker弱 |
| **安装新包 (pip/conda)** | 完全自由 | 完全自由 | 需预构建模板 | 受限 | 完全自由 | 完全自由 |
| **挂载宿主数据目录** | bind mount 直接 | 需配置 | 困难 (9P/VirtioFS) | 困难 | PVC 配置复杂 | bind mount 直接 |
| **私有化部署难度** | 单机Docker Compose | pip安装 | 需KVM+复杂配置 | 核心闭源 | 需K3s集群 | 内置systemd |
| **维护复杂度** | 极低 | 低 | 高 | 高 | 极高 | 中等 |
| **单维护者友好** | 最友好 | 友好 | 不友好 | 不友好 | 极不友好 | 较友好 |
| **生信工具链预装** | Dockerfile自定义 | conda environment | 模板构建 | 受限 | Docker镜像 | 类似Docker |
| **容器镜像生态** | Docker Hub 海量 | N/A | 极小 | 专用 | 丰富 | 极小 |
| **GPU支持** | NVIDIA Container Toolkit | 需配置 | 复杂 | 有限 | NVIDIA Device Plugin | 直接设备访问 |
| **网络隔离** | Docker网络+iptables | 需额外配置 | 内置防火墙 | 内置 | NetworkPolicy | 需手动配置 |
| **社区/文档** | 最完善 | 完善 | AWS生态 | 较小 | 庞大但复杂 | 较小 |

---

### 3.2 针对 OmicHub 场景的深度分析

#### OmicHub 场景特殊需求清单

| 需求 | 优先级 | 说明 |
|------|--------|------|
| 挂载宿主组学数据 | **P0** | 几GB到几十GB的 h5ad/rds 文件，必须 bind mount |
| 预装生信工具链 | **P0** | Scanpy/Seurat/Squidpy + Bioconda 包 |
| 用户安装新包 | **P1** | 持久化安装的包在会话期间可用 |
| 单服务器部署 | **P0** | 一台服务器，所有服务 Docker Compose |
| 并发 < 20 用户 | **P1** | 小规模使用 |
| 1人维护 | **P0** | 极简运维是硬性约束 |
| 秒级启动 | **P1** | 用户体验要求 |
| GPU 加速 (可选) | **P2** | UMAP 计算等可受益于 GPU |

#### 各方案评分（满分10分）

| 维度权重 | Docker API | Jupyter Kernel | Firecracker | E2B | K8s Pod | systemd-nspawn |
|---------|-----------|---------------|-------------|-----|---------|---------------|
| 数据挂载 (20%) | **10** | 6 | 2 | 2 | 5 | 9 |
| 包安装自由 (15%) | **10** | 10 | 4 | 5 | 10 | 10 |
| 私有化部署 (20%) | **10** | 9 | 3 | 1 | 3 | 8 |
| 维护极简 (20%) | **10** | 8 | 2 | 2 | 1 | 6 |
| 启动速度 (10%) | 7 | 9 | 10 | 10 | 3 | 7 |
| 安全隔离 (10%) | 7 | 5 | 10 | 10 | 7 | 5 |
| 生信生态 (5%) | **10** | 9 | 4 | 4 | 9 | 7 |
| **加权总分** | **9.3** | 7.9 | 4.5 | 3.8 | 5.2 | 7.5 |

---

### 3.3 方案详细评估

#### 方案A：Docker API（推荐）

**为什么 Docker API 是 OmicHub 的最佳选择：**

1. **数据挂载是生信平台的刚需**：组学数据文件 (h5ad/rds) 通常在 1GB-50GB，不可能打包进容器镜像。Docker 的 `bind mount` 可以直接挂载宿主目录：`-v /data/omics:/data:ro`，这是 Firecracker/E2B 难以做到的（它们使用 9P/VirtioFS，大文件IO性能差）。

2. **Bioconda 生态自由**：生信分析需要频繁安装新的 Bioconda 包（如 `samtools`、`star`、`cellranger` 等），Docker 容器内可以执行任意 `conda install`，而 Firecracker/E2B 需要重新构建模板。

3. **一人维护的现实约束**：Docker 是团队已有技术栈，维护文档最完善，出问题搜索引擎就能解决。Firecracker 需要深入理解 KVM、微VM 网络、VirtioFS，troubleshooting 门槛极高。

4. **通过预热池弥补启动延迟**：虽然 Docker 冷启动 (2-5s) 慢于 Firecracker (<200ms)，但**预热容器池**策略可将热启动控制在 <500ms，满足交互体验要求。

5. **安全性足够**：通过以下措施，Docker 容器的安全性对私有化内网场景已经足够：
   - `--read-only` 根文件系统 + `tmpfs` 临时目录
   - `--security-opt=no-new-privileges`
   - `--cap-drop ALL --cap-add SYS_PTRACE` (gdb调试需要)
   - 网络隔离：`--network sandbox-net` (无外部访问)
   - 资源限制：`--memory 8g --cpus 4`

#### 方案B：Jupyter Kernel per Session

**不推荐理由**：
- Jupyter Kernel 本质上是 Python 进程，**隔离级别远低于容器**（仅进程级，无 namespace/cgroup）
- 需要额外搭建 `jupyter_client` + `jupyter_kernel_gateway` 的复杂基础设施
- 多人共享 Kernel Gateway 时存在资源竞争和安全隐患
- **优势场景**是长期交互式 Notebook，而 OmicHub 需要的是**受控的代码执行沙盒**

#### 方案C：Firecracker 微VM

**不推荐理由**：
- **KVM 依赖**：需要 `/dev/kvm` 支持，嵌套虚拟化环境下不可用
- **数据挂载困难**：VirtioFS/9P 对大文件 (几GB h5ad) 的随机IO性能极差，而生信分析正是大量随机IO
- **包安装不灵活**：需要重新构建 VM 模板，无法动态 conda install
- **维护门槛高**：需要理解微VM网络配置、VMM 管理、Firecracker API
- **适合场景**：云厂商多租户安全沙盒（如 AWS Lambda），不适合数据密集型的生信分析

#### 方案D：E2B

**不推荐理由**：
- **核心运行时闭源**：只有 SDK 开源，Firecracker 运行时是不开源的托管服务
- **自托管路径不被官方支持**：官方文档明确说明 *"no self-hosted path"*
- **数据挂载困难**：设计用于无状态代码执行，不适合挂载大量本地数据
- **网络依赖**：需要连接 E2B 云服务，不满足私有化要求
- **适合场景**：快速原型验证、SaaS 产品的代码执行功能

#### 方案E：Kubernetes Pod

**不推荐理由**：
- **严重的过度设计**：单服务器 + <20 并发场景下，K3s 的控制平面本身就是资源浪费
- **维护复杂度爆炸**：需要维护 etcd、scheduler、controller-manager，一人团队不可能
- **Pod 启动延迟**：即使 K3s 也需要 3-10s 启动 Pod
- **适合场景**：多节点集群、大规模弹性伸缩、企业级部署

#### 方案F：systemd-nspawn

**备选但不推荐理由**：
- **生态极小**：没有类似 Docker Hub 的镜像生态，生信工具链需要从头构建
- **网络功能弱**：相比 Docker 的网络管理（bridge、overlay），systemd-nspawn 的网络配置需手动 iptables
- **GPU 支持**：虽然可以直接访问设备，但不如 NVIDIA Container Toolkit 成熟
- **适合场景**：超轻量级容器、不需要镜像生态的系统容器

---

### 3.4 推荐方案架构图

```
+-------------------------------------------------------------+
|                         单台服务器                           |
|                                                             |
|  +--------------+  +--------------+  +--------------------+ ||
|  |   Nginx      |  |  FastAPI     |  |   PostgreSQL       | ||
|  |   (网关)      |  |  (主应用)     |  |   + Redis          | ||
|  +------+-------+  +------+-------+  +--------------------+ ||
|         |                  |                                |
|         |         +--------v--------+                       |
|         |         |   沙盒管理器      |                       |
|         |         | (sandbox_mgr.py) |                       |
|         |         +--------v--------+                       |
|         |                  |                                |
|  +------v------------------v----------------------+        |
|  |              Docker Network: sandbox-net        |        |
|  |                                                 |        |
|  |  +------------+  +------------+  +-----------+ |        |
|  |  | 预热池容器0 |  | 预热池容器1 |  | 运行中容器 | |        |
|  |  | (Python +  |  | (Python +  |  | (用户会话  | |        |
|  |  |  Bioconda) |  |  Bioconda) |  |  绑定)     | |        |
|  |  +------------+  +------------+  +-----------+ |        |
|  |                                                 |        |
|  +-------------------------------------------------+        |
|                                                             |
|  数据挂载:                                                   |
|  /data/omics  ->  /data (只读)  [h5ad/rds 组学数据]         |
|  /data/ref    ->  /ref (只读)   [参考基因组]                 |
|  /tmp/sandbox ->  /tmp (读写)   [临时结果]                   |
|  pip/conda cache  ->  持久化包缓存                            |
+-------------------------------------------------------------+
```

---

### 3.5 Dockerfile 示例（生信沙盒镜像）

```dockerfile
# ============================================
# OmicHub 生信分析沙盒镜像
# 基于 mambaforge 预装常用生信工具链
# ============================================
FROM condaforge/mambaforge:24.3.0-0

LABEL maintainer="OmicHub"
LABEL description="Bioinformatics sandbox for OmicHub AI Copilot"

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libhdf5-dev libpng-dev libfreetype6-dev \
    liblapack-dev libopenblas-dev libxml2-dev libxslt1-dev \
    libcurl4-openssl-dev libssl-dev git wget unzip procps \
    r-base r-base-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置 conda 配置
RUN conda config --add channels bioconda \
    && conda config --add channels conda-forge \
    && conda config --set channel_priority strict

# 创建 omichub 环境 (Python 3.11)，预装核心生信工具链
RUN mamba create -n omichub python=3.11 -y \
    && mamba install -n omichub -y \
        scanpy=1.10 anndata=0.10 muon=0.1 \
        matplotlib=3.8 seaborn=0.13 \
        numpy=1.26 pandas=2.2 scipy=1.13 scikit-learn=1.5 \
        ipykernel=6.29 statsmodels=0.14 plotly=5.22 \
        requests=2.31 tqdm=4.66 openpyxl=3.1 \
    && mamba clean --all -y

# pip 安装 conda 中缺少的包
SHELL ["conda", "run", "-n", "omichub", "/bin/bash", "-c"]
RUN pip install --no-cache-dir \
    "squidpy>=1.4.0" "scvi-tools>=1.1.0" "celltypist>=1.6.0" \
    "decoupler>=1.6.0" "scanorama>=1.7" "scarches>=0.6" \
    "kaleido>=0.2.1"

# 安装 R 生信包
RUN Rscript -e "
    install.packages(c('Seurat', 'Signac', 'tidyverse'), repos='https://cloud.r-project.org/');
    if (!requireNamespace('BiocManager', quietly = TRUE))
        install.packages('BiocManager');
    BiocManager::install(c('SingleCellExperiment', 'scater', 'scran', 'monocle', 'DESeq2'));
"

# 沙盒入口脚本
COPY sandbox_entrypoint.py /opt/sandbox_entrypoint.py
RUN chmod +x /opt/sandbox_entrypoint.py

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import scanpy, numpy, pandas; print('OK')" || exit 1

EXPOSE 8888
ENV PATH=/opt/conda/envs/omichub/bin:$PATH
ENV CONDA_DEFAULT_ENV=omichub
WORKDIR /workspace

ENTRYPOINT ["python", "/opt/sandbox_entrypoint.py"]
```

---

### 3.6 沙盒入口脚本 (sandbox_entrypoint.py)

```python
#!/usr/bin/env python3
"""
OmicHub 沙盒容器入口脚本
功能：WebSocket 服务端，接收前端发送的 Python 代码，
      在容器内安全执行并返回结果/图表
"""

import asyncio
import websockets
import json
import sys
import io
import traceback
import base64
import os
import matplotlib
matplotlib.use('Agg')  # 无头模式

from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

OUTPUT_DIR = Path('/workspace/outputs')
OUTPUT_DIR.mkdir(exist_ok=True)

class SandboxExecutor:
    """安全的 Python 代码执行器"""

    def __init__(self):
        self.globals = {
            '__builtins__': __builtins__,
            'scanpy': __import__('scanpy'),
            'sc': __import__('scanpy'),
            'numpy': __import__('numpy'),
            'np': __import__('numpy'),
            'pandas': __import__('pandas'),
            'pd': __import__('pandas'),
            'matplotlib': __import__('matplotlib'),
            'plt': __import__('matplotlib.pyplot'),
            'seaborn': __import__('seaborn'),
            'sns': __import__('seaborn'),
        }
        self.execution_count = 0

    async def execute(self, code: str, cell_id: str) -> dict:
        """执行代码并返回结构化结果"""
        self.execution_count += 1
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        result = {
            'cell_id': cell_id,
            'execution_count': self.execution_count,
            'status': 'ok',
            'outputs': []
        }

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exec(code, self.globals)

            stdout = stdout_buffer.getvalue()
            stderr = stderr_buffer.getvalue()

            if stdout:
                result['outputs'].append({'type': 'stream', 'name': 'stdout', 'text': stdout})
            if stderr:
                result['outputs'].append({'type': 'stream', 'name': 'stderr', 'text': stderr})

            # 捕获 matplotlib 图表
            figs = [plt for plt in sys.modules['matplotlib'].pyplot.get_fignums()]
            for fig_num in figs:
                fig = sys.modules['matplotlib'].pyplot.figure(fig_num)
                img_path = OUTPUT_DIR / f'{cell_id}_fig_{fig_num}.png'
                fig.savefig(img_path, dpi=150, bbox_inches='tight', format='png')
                with open(img_path, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                result['outputs'].append({
                    'type': 'image', 'format': 'png', 'data': img_data,
                    'width': fig.get_figwidth() * fig.dpi,
                    'height': fig.get_figheight() * fig.dpi
                })
                sys.modules['matplotlib'].pyplot.close(fig_num)

        except Exception as e:
            result['status'] = 'error'
            result['outputs'].append({
                'type': 'error', 'ename': type(e).__name__,
                'evalue': str(e), 'traceback': traceback.format_exc().split('\n')
            })

        return result


async def handle_websocket(websocket, path):
    """WebSocket 连接处理"""
    executor = SandboxExecutor()
    print(f"Client connected from {websocket.remote_address}")
    try:
        async for message in websocket:
            try:
                msg = json.loads(message)
                msg_type = msg.get('type')

                if msg_type == 'execute':
                    code = msg.get('code', '')
                    cell_id = msg.get('cell_id', 'unknown')
                    await websocket.send(json.dumps({
                        'type': 'status', 'cell_id': cell_id, 'status': 'executing'
                    }))
                    result = await executor.execute(code, cell_id)
                    await websocket.send(json.dumps(result))

                elif msg_type == 'ping':
                    await websocket.send(json.dumps({'type': 'pong'}))

                elif msg_type == 'install_package':
                    package = msg.get('package', '')
                    manager = msg.get('manager', 'pip')
                    # 异步包安装逻辑...

            except json.JSONDecodeError:
                await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid JSON'}))
    except websockets.exceptions.ConnectionClosed:
        print(f"Client {websocket.remote_address} disconnected")


async def main():
    port = int(os.environ.get('SANDBOX_PORT', 8888))
    print(f"OmicHub Sandbox starting on port {port}")
    async with websockets.serve(handle_websocket, '0.0.0.0', port):
        await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
```

---

### 3.7 安全加固措施

```yaml
# docker-compose.sandbox.yml
version: '3.8'

services:
  sandbox-manager:
    build:
      context: ./sandbox
      dockerfile: Dockerfile
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - SYS_PTRACE  # Python 调试需要
    mem_limit: 8g
    cpus: '4.0'
    volumes:
      - /data/omics:/data:ro          # 组学数据只读
      - /data/reference:/reference:ro  # 参考基因组
      - sandbox-tmp:/tmp               # 临时文件
      - sandbox-pip:/root/.cache/pip   # pip缓存持久化
      - sandbox-conda:/opt/conda/envs/omichub/lib/python3.11/site-packages
    networks:
      - sandbox-net
    environment:
      - SANDBOX_PORT=8888
      - MPLBACKEND=Agg
      - PYTHONDONTWRITEBYTECODE=1
    tmpfs:
      - /tmp:size=2g,exec
    healthcheck:
      test: ["CMD", "python", "-c", "import scanpy, numpy; print('OK')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

networks:
  sandbox-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16

volumes:
  sandbox-tmp:
  sandbox-pip:
  sandbox-conda:
```

---

### 3.8 沙盒方案最终推荐

```
+-----------------------------------------------------------+
|  推荐方案：Docker API + 预热容器池 + 自定义生信镜像         |
+-----------------------------------------------------------+
|  核心技术：                                                |
|  - docker-py (Python Docker SDK)                          |
|  - 自定义 Bioconda 沙盒镜像                                |
|  - WebSocket 代码执行通信                                   |
|  - 容器预热池 (最小5, 最大15)                              |
+-----------------------------------------------------------+
|  关键优化：                                                |
|  - 镜像预装 scanpy/seurat/scvi 等核心工具链                 |
|  - pip/conda 缓存持久化 (避免重复下载)                      |
|  - /data 组学数据目录 bind mount 只读挂载                   |
|  - read-only rootfs + tmpfs 临时目录                       |
|  - 会话亲和性 (同一用户复用同一容器)                         |
|  - 30分钟超时自动回收                                      |
+-----------------------------------------------------------+
|  预期性能指标：                                            |
|  - 热启动延迟: <500ms (预热池命中)                         |
|  - 冷启动延迟: 2-5s (新镜像/池扩容)                        |
|  - 单容器内存: 200-500MB 基础 + 分析数据                    |
|  - 并发能力: 15个容器实例 (受限于服务器内存)                 |
+-----------------------------------------------------------+
```


---

## 4. LLM Agent框架选型

### 4.1 Agent 框架全维度对比

| 维度 | LangChain | LangGraph | CrewAI | AutoGen | OpenAI Assistants API | 原生实现 |
|------|-----------|-----------|--------|---------|---------------------|---------|
| **定位** | LLM应用编排框架 | 复杂Agent工作流图引擎 | 多Agent角色协作 | 微软多Agent对话框架 | 封闭API服务 | FastAPI+自定义逻辑 |
| **架构重量** | 重 (~10MB 依赖) | 重 (依赖LangChain) | 中等 (~5MB) | 中等 (~5MB) | N/A (云端) | 极简 |
| **FastAPI集成** | 可用 | 可用 | 可用 | 需适配 | HTTP API调用 | 完美 |
| **MCP协议支持** | 内置支持 | 内置支持 | 内置支持 | 支持 | 有限 | 直接集成 |
| **代码生成质量** | 依赖底层模型 | 依赖底层模型 | 依赖底层模型 | 内置代码执行循环 | 依赖底层模型 | 依赖底层模型 |
| **流式输出 (SSE/WS)** | 支持 | 原生支持 | 有限 | 有限 | 支持 | 完全控制 |
| **调试体验** | 复杂 (LangSmith付费) | 需LangSmith | 简单日志 | 对话日志 | 黑盒 | 完全透明 |
| **维护成本** | 高 (版本频繁变动) | 高 | 中等 | 中等 | 无 (托管) | 最低 |
| **学习曲线** | 陡峭 | 陡峭 | 平缓 | 中等 | 低 | 最平缓 (已有技能) |
| **社区活跃度** | 极高 (70M月下载) | 极高 | 高 (30K stars) | 高 (Microsoft) | 高 | N/A |
| **版本稳定性** | 频繁Breaking Change | 跟随LangChain | 较稳定 | 较稳定 | N/A | 完全可控 |
| **多Agent协作** | 通过LangGraph | 原生图结构 | 原生Crew模式 | 原生GroupChat | 有限 | 需自行实现 |
| **人工介入 (Human-in-Loop)** | 支持 | 内置Breakpoint | 有限 | UserProxyAgent | 不支持 | 完全自定义 |
| **私有化部署** | 开源 | 开源 | 开源 | 开源 | 闭源API | 完全自主 |
| **单维护者友好度** | 不友好 | 不友好 | 一般 | 一般 | 友好但有风险 | 最友好 |

---

### 4.2 各框架详细评估

#### LangChain / LangGraph

**不推荐理由（对 OmicHub 场景）**：

1. **过度设计**：LangChain 的抽象层级（Chains → LCEL → LangGraph）对于 OmicHub 的"代码生成→执行→返回结果"这一简单流程来说是严重的过度工程。LangChain 的设计目标是覆盖**所有**LLM应用场景（RAG、Agent、记忆、工具调用），而 OmicHub 只需要其中一个子集。

2. **版本不稳定**：LangChain 以频繁引入 Breaking Change 著称，v0.1 → v0.2 → v0.3 的迁移成本高昂。单维护者无法承担跟进版本更新的工作量。

3. **隐性成本**：LangSmith（调试和可观测性平台）是 LangGraph 的最佳搭档，但它是**付费服务**。没有 LangSmith 的 LangGraph 调试体验大打折扣。

4. **流式输出控制复杂**：LangChain 的流式输出需要通过特定的 Callback 机制实现，与 FastAPI 的 WebSocket 集成需要大量适配代码。

> **适合场景**：企业级多步骤 RAG 流程、需要持久化状态恢复的长时间运行 Agent、多工具并行调用的复杂场景。

#### CrewAI

**不推荐理由**：

1. **多 Agent 协作不适合代码执行场景**：CrewAI 的核心价值是"角色扮演"式的多 Agent 协作（研究员→写作者→编辑），而 OmicHub 的核心需求是**单 Agent 代码生成与执行**，不需要复杂的多 Agent 编排。

2. **隐藏依赖**：虽然 CrewAI 已脱离 LangChain 独立发展，但仍存在隐性的生态依赖。

3. **流式输出支持有限**：CrewAI 的流式输出能力较弱，不适合 OmicHub 的实时代码执行反馈需求。

> **适合场景**：内容生成管道（研究→写作→编辑）、多角色协作的自动化工作流、快速原型验证。

#### AutoGen

**不推荐理由**：

1. **对话模式不适合**：AutoGen 的核心是 GroupChat 对话模式，多个 Agent 通过对话协作解决问题。这种模式对于代码执行来说**效率低下**（每次任务可能需要 20+ 次 LLM 调用），且**不可预测**。

2. **Token 消耗高**：AutoGen 的群聊模式会导致每个 Agent 都能看到完整对话历史，上下文膨胀极快。

3. **Azure 偏向**：虽然支持任意 OpenAI 兼容 API，但最佳体验在 Azure 上。

> **适合场景**：代码审查协作、研究讨论、需要多视角辩论的决策任务。

#### OpenAI Assistants API

**不推荐理由**：

1. **封闭生态**：绑定 OpenAI 服务，不支持私有化部署的 Kimi API 等国产模型。
2. **无代码执行隔离**：Assistants API 的 Code Interpreter 运行在 OpenAI 的服务器上，数据离开本地，违反生信数据的隐私要求。
3. **与 OmicHub 后端集成困难**：Assistants API 的 Thread/Run 模型与 OmicHub 的 FastAPI 架构不匹配。

> **适合场景**：快速原型、无数据隐私要求的通用代码执行、ChatGPT 插件开发。

---

### 4.3 原生实现方案设计

**核心架构**：FastAPI + Python MCP SDK + 自定义 Agent 逻辑

```
+---------------------------------------------------------------+
|                    OmicHub Agent 架构                          |
+---------------------------------------------------------------+
|                                                               |
|  前端 Vue 3                                                    |
|     |                                                         |
|     v WebSocket (Streaming)                                   |
|  +-------------------------------------------------------+   |
|  |              FastAPI Agent Router                      |   |
|  |  +--------------+  +--------------+  +-------------+  |   |
|  |  | /chat        |  | /execute     |  | /mcp        |  |   |
|  |  | 对话接口      |  | 代码执行      |  | MCP协议      |  |   |
|  |  | (WebSocket)  |  | (HTTP+WS)    |  | (SSE)       |  |   |
|  |  +------+-------+  +------+-------+  +------+------+  |   |
|  |         |                  |                |           |   |
|  |  +------v------------------v----------------v------+    |   |
|  |  |           Agent Orchestrator                      |   |
|  |  |  (agent_orchestrator.py - 自定义编排)              |   |
|  |  +------+---------------------------+------+--------+   |
|  |         |                           |                   |   |
|  |  +------v------+            +-------v--------+         |   |
|  |  | Code Agent  |            | Analysis Agent |         |   |
|  |  |             |            |                |         |   |
|  |  | - 代码生成   |            | - 数据解读      |         |   |
|  |  | - 代码修复   |            | - 结果解释      |         |   |
|  |  | - 参数建议   |            | - 下一步建议    |         |   |
|  |  +------+------+            +----------------+         |   |
|  |         |                                               |   |
|  |  +------v--------------------------------------+        |   |
|  |  |              Tool Registry                    |        |   |
|  |  |  +--------+  +--------+  +--------+         |        |   |
|  |  |  |Docker  |  |MCP     |  |File    |         |        |   |
|  |  |  |Sandbox |  |Client  |  |System  |         |        |   |
|  |  |  +--------+  +--------+  +--------+         |        |   |
|  |  +----------------------------------------------+        |   |
|  +-------------------------------------------------------+   |
|                                                               |
|  +-------------------------------------------------------+   |
|  |              LLM Provider Interface                    |   |
|  |  +------------+  +------------+  +----------------+   |   |
|  |  | Kimi API   |  | OpenAI API |  | Local Models     |   |   |
|  |  | (Moonshot) |  | (兼容)      |  | (vLLM/llama.cpp)|   |   |
|  |  +------------+  +------------+  +----------------+   |   |
|  +-------------------------------------------------------+   |
+---------------------------------------------------------------+
```

---

### 4.4 原生 Agent 核心实现

```python
# agent_orchestrator.py - 简化的Agent编排器
"""
OmicHub Agent 编排器
- 支持代码生成、代码执行、结果分析的状态机
- 流式输出到前端 WebSocket
- 与 MCP 工具集成
- 支持 Kimi/OpenAI 多模型切换
"""

from enum import Enum, auto
from typing import AsyncGenerator, Optional
from dataclasses import dataclass, field
import json
import httpx

class AgentState(Enum):
    """Agent 状态机"""
    IDLE = auto()
    THINKING = auto()          # 分析用户需求
    GENERATING_CODE = auto()   # 生成代码
    EXECUTING = auto()         # 在沙盒中执行
    ANALYZING = auto()         # 分析执行结果
    FOLLOW_UP = auto()         # 生成后续建议
    ERROR = auto()             # 错误恢复

@dataclass
class AgentContext:
    """Agent 执行上下文"""
    session_id: str
    conversation_history: list = field(default_factory=list)
    current_code: str = ""
    execution_result: dict = field(default_factory=dict)
    data_schema: dict = field(default_factory=dict)
    state: AgentState = AgentState.IDLE


class OmicHubAgent:
    """OmicHub 代码执行 Agent"""

    SYSTEM_PROMPT = """你是 OmicHub AI Copilot，一个专业的生物信息学分析助手。
你的核心能力是根据用户的自然语言描述，生成可执行的 Python 代码（基于 Scanpy/Seurat 生态）。

规则：
1. 生成的代码必须是完整的、可执行的 Python 脚本
2. 数据文件路径使用 /data/ 前缀
3. 使用 scanpy (sc) 作为单细胞分析的主要库
4. 图表保存到 /workspace/outputs/ 目录
5. 所有导入语句必须放在代码开头
6. 对于大数据集，提供分块处理的选项
7. 如果用户请求超出当前数据范围，友好地提示

当前数据集信息：
{data_schema}
"""

    def __init__(self, llm_config: dict, sandbox_manager):
        self.llm_base_url = llm_config['base_url']
        self.llm_api_key = llm_config['api_key']
        self.llm_model = llm_config['model']
        self.sandbox = sandbox_manager

    async def stream_process(
        self, user_message: str, context: AgentContext
    ) -> AsyncGenerator[str, None]:
        """流式处理用户请求，yield JSON 状态更新"""
        try:
            # 状态1: 分析需求
            context.state = AgentState.THINKING
            yield self._emit('status', {'message': '正在分析您的需求...', 'state': 'thinking'})

            messages = self._build_messages(user_message, context)

            # 状态2: 流式生成代码
            context.state = AgentState.GENERATING_CODE
            yield self._emit('status', {'message': '正在生成分析代码...', 'state': 'generating'})

            generated_code = ""
            async for chunk in self._llm_stream(messages):
                generated_code += chunk
                yield self._emit('code_stream', {'chunk': chunk})

            context.current_code = generated_code
            yield self._emit('code_complete', {'code': generated_code})

            # 状态3: 在沙盒中执行代码
            context.state = AgentState.EXECUTING
            yield self._emit('status', {'message': '正在执行代码...', 'state': 'executing'})

            result = await self.sandbox.execute_code(
                session_id=context.session_id, code=generated_code
            )
            context.execution_result = result

            for output in result.get('outputs', []):
                yield self._emit('execution_output', output)

            # 状态4: 结果分析
            if result.get('status') == 'ok':
                context.state = AgentState.ANALYZING
                yield self._emit('status', {'message': '分析执行结果...', 'state': 'analyzing'})
                analysis = await self._analyze_result(context)
                yield self._emit('analysis', {'text': analysis})
                suggestions = await self._generate_suggestions(context)
                yield self._emit('suggestions', {'items': suggestions})
            else:
                context.state = AgentState.ERROR
                yield self._emit('status', {'message': '执行出错，尝试修复...', 'state': 'error'})
                fix_code = await self._attempt_fix(context)
                if fix_code:
                    yield self._emit('fix_suggestion', {'code': fix_code})

            context.state = AgentState.IDLE
            yield self._emit('complete', {})

        except Exception as e:
            yield self._emit('error', {'message': str(e)})
            context.state = AgentState.IDLE

    async def _llm_stream(self, messages: list) -> AsyncGenerator[str, None]:
        """调用 LLM API 流式输出"""
        async with httpx.AsyncClient() as client:
            async with client.stream(
                'POST', f'{self.llm_base_url}/chat/completions',
                headers={'Authorization': f'Bearer {self.llm_api_key}'},
                json={'model': self.llm_model, 'messages': messages, 'stream': True, 'temperature': 0.2},
                timeout=120
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]': break
                        try:
                            chunk = json.loads(data)
                            content = chunk['choices'][0]['delta'].get('content', '')
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError):
                            continue

    def _build_messages(self, user_message: str, context: AgentContext) -> list:
        return [
            {'role': 'system', 'content': self.SYSTEM_PROMPT.format(
                data_schema=json.dumps(context.data_schema, indent=2, ensure_ascii=False)
            )},
            *context.conversation_history,
            {'role': 'user', 'content': user_message}
        ]

    def _emit(self, event_type: str, data: dict) -> str:
        return json.dumps({'type': event_type, **data})

    async def _analyze_result(self, context: AgentContext) -> str:
        return "分析完成"

    async def _generate_suggestions(self, context: AgentContext) -> list:
        return ["查看特定基因的表达分布", "进行差异表达分析", "导出高分辨率图表"]

    async def _attempt_fix(self, context: AgentContext) -> Optional[str]:
        return None
```

---

### 4.5 MCP 协议集成设计

```python
# mcp_integration.py
"""
OmicHub MCP (Model Context Protocol) 集成
功能：
- 暴露 Nextflow/Snakemake 工作流作为 MCP 工具
- 允许 Agent 调用底层流程编排
- SSE 传输协议
"""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import json

mcp_router = APIRouter(prefix="/mcp", tags=["MCP"])
mcp_server = Server("omichub-workflows")

@mcp_server.tool()
async def run_nextflow_workflow(workflow_name: str, params: dict, profile: str = "docker") -> str:
    """运行 Nextflow 工作流"""
    return json.dumps({"status": "started", "run_id": "nf-xxx"})

@mcp_server.tool()
async def run_snakemake_workflow(snakefile: str, config: dict, cores: int = 4) -> str:
    """运行 Snakemake 工作流"""
    return json.dumps({"status": "started", "run_id": "sm-xxx"})

@mcp_server.tool()
async def list_available_workflows() -> str:
    """列出所有可用的分析工作流"""
    workflows = [
        {"name": "rnaseq-expression", "description": "RNA-Seq 差异表达分析", "pipeline": "Nextflow"},
        {"name": "scrnq-clustering", "description": "单细胞RNA测序聚类与注释", "pipeline": "Nextflow"},
        {"name": "atac-seq-peak", "description": "ATAC-Seq 峰 calling", "pipeline": "Snakemake"}
    ]
    return json.dumps(workflows)

@mcp_router.get("/sse")
async def mcp_sse_endpoint(request: Request):
    """MCP SSE 服务端点"""
    transport = SseServerTransport("/mcp/messages")
    async def event_generator():
        async with transport.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### 4.6 原生实现 vs 框架的核心优势

| 场景 | 原生实现优势 | 框架替代成本 |
|------|-------------|-------------|
| **代码生成 Agent** | 直接控制 prompt 模板，针对生信场景微调 | LangChain 的 PromptTemplate 抽象反而增加复杂度 |
| **沙盒执行集成** | WebSocket 直接转发，无需适配框架的抽象层 | LangChain 的 Tool 抽象与 WebSocket 流式输出不匹配 |
| **MCP 调度** | Python MCP SDK 原生集成，直接调用 | 框架的 MCP 适配层增加了中间层 |
| **流式输出** | 完全控制 SSE 事件格式，前端零适配 | 需适配框架的流式输出格式 |
| **错误恢复** | 自定义重试逻辑（如代码错误→自动修复） | 框架的 retry 机制不够灵活 |
| **调试** | 完整控制日志和追踪，print 即可调试 | 需要学习框架的调试工具 |
| **版本控制** | 无外部依赖版本冲突 | LangChain 版本升级可能导致 Breaking Change |

---

### 4.7 LLM Agent 最终推荐

```
+-----------------------------------------------------------+
|  推荐方案：原生实现 (FastAPI + Python MCP SDK)              |
+-----------------------------------------------------------+
|  核心理念：Agent 不是框架，是架构模式                        |
+-----------------------------------------------------------+
|  核心组件：                                                |
|  - Agent Orchestrator (状态机驱动)                          |
|  - LLM Provider Interface (Kimi/OpenAI 统一封装)            |
|  - Code Generator (专用 prompt 模板)                        |
|  - Sandbox Bridge (WebSocket -> Docker 沙盒)               |
|  - MCP Client (工作流调度)                                  |
|  - Result Analyzer (结果解读)                               |
+-----------------------------------------------------------+
|  Agent 状态机：                                            |
|  IDLE -> THINKING -> GENERATING_CODE -> EXECUTING ->       |
|  ANALYZING -> FOLLOW_UP -> IDLE                            |
|                    | (错误)                                 |
|                  ERROR -> (重试/修复) -> GENERATING_CODE    |
+-----------------------------------------------------------+
|  设计原则：                                                |
|  - 简单比强大更重要 (KISS)                                  |
|  - 显式优于隐式 (拒绝魔法抽象层)                             |
|  - 流式输出是核心需求 (SSE/WebSocket 原生控制)                |
|  - MCP 作为标准工具接口                                     |
|  - 针对生信场景的专用 prompt 优化                           |
+-----------------------------------------------------------+
```


---

## 5. 总结：推荐技术栈总表

### 5.1 完整技术栈总表

| 层级 | 组件 | 推荐选型 | 版本 | 理由（一句话） |
|------|------|---------|------|---------------|
| **前端框架** | UI框架 | Vue 3 (已有) | ^3.4 | 响应式系统成熟，组合式API契合复杂交互 |
| **前端框架** | 构建工具 | Vite (已有) | ^5.0 | 已集成，无需变更 |
| **前端框架** | UI组件库 | Naive UI (已有) | ^2.38 | 已集成，符合学术工具审美 |
| **前端框架** | 状态管理 | Pinia (已有) | ^2.1 | 已集成，轻量好用 |
| **代码编辑** | 编辑器 | **CodeMirror 6** | ^6.0 | tree-shakable轻量，Vue3原生契合，多实例友好 |
| **代码编辑** | Python语言支持 | @codemirror/lang-python | ^6.1 | 官方维护，语法高亮+缩进+折叠 |
| **代码编辑** | 主题 | @codemirror/theme-one-dark | ^6.1 | 暗色主题与Naive UI深色模式一致 |
| **代码编辑** | Diff对比 | @codemirror/merge | ^6.0 | 代码版本对比，用于AI修改展示 |
| **图表渲染** | 图表引擎 | **ECharts 5 + ECharts GL** | ^5.5 | 中文文档完善，GL扩展支持100万+细胞散点 |
| **图表渲染** | Vue封装 | vue-echarts | ^7.0 | ECharts官方Vue组件 |
| **图表渲染** | 统计图表 | 后端Plotly渲染 | ^5.22 | 沙盒内Plotly生成静态图，前端iframe展示 |
| **UI交互** | 代码展示面板 | **自定义Vue组件** | - | 参考Claude Artifacts设计，代码+运行+结果标签页 |
| **后端服务** | Web框架 | **FastAPI (已有)** | ^0.110 | 保持技术栈统一，Async原生支持 |
| **后端服务** | 沙盒调度器 | **docker-py + 自定义池** | ^7.0 | Docker API原生操作，预热池控制启动延迟 |
| **后端服务** | 会话管理 | **Redis (已有)** | ^7.0 | 会话状态+容器绑定关系缓存 |
| **后端服务** | 异步任务 | **Celery (已有)** | ^5.3 | 长任务（大文件分析）后台执行 |
| **后端服务** | 数据库 | PostgreSQL (已有) | ^16 | 代码历史/分析记录持久化 |
| **沙盒执行** | 容器运行时 | **Docker Engine** | ^25.0 | 团队已有技术，生态最完善 |
| **沙盒执行** | 沙盒镜像 | **自定义Bioconda镜像** | - | 预装scanpy/seurat/scvi完整生信工具链 |
| **沙盒执行** | 会话策略 | **预热容器池 + 会话亲和** | - | 热启动<500ms，状态持久，自动回收 |
| **沙盒执行** | 包管理 | pip + conda + 缓存持久化 | - | 用户自由安装，缓存加速 |
| **沙盒安全** | 隔离策略 | read-only rootfs + tmpfs + capability限制 | - | 分层防御，满足内网安全需求 |
| **沙盒通信** | 实时通信 | **WebSocket (双向)** | - | 代码发送->执行输出->图表流式回传 |
| **LLM Agent** | Agent框架 | **原生实现 (自定义状态机)** | - | 针对生信场景专用设计，避免框架过度工程 |
| **LLM Agent** | MCP协议 | **Python MCP SDK** | ^1.0 | 标准化工具接口，调度Nextflow/Snakemake |
| **LLM Agent** | LLM接口 | **统一封装 (Kimi/OpenAI)** | - | 支持多模型切换，流式输出统一处理 |
| **LLM Agent** | Prompt管理 | Jinja2模板 + 版本控制 | ^3.1 | 生信专用prompt可迭代优化 |
| **工作流调度** | 流程引擎 | Nextflow + Snakemake (已有) | - | 通过MCP暴露为Agent可调用的工具 |
| **部署** | 容器编排 | Docker Compose (已有) | ^2.24 | 单机部署最简单方案 |
| **部署** | 反向代理 | Nginx (已有) | ^1.24 | WebSocket长连接负载均衡 |
| **监控** | 日志收集 | Docker logging + 自定义 | - | 容器stdout/stderr集中收集 |
| **监控** | 性能监控 | 自定义 / Prometheus(可选) | - | 基础CPU/内存监控即可 |

---

### 5.2 关键决策清单

| # | 决策点 | 选择 | 替代方案 | 不选替代的理由 |
|---|-------|------|---------|--------------|
| 1 | 代码编辑器 | CodeMirror 6 | Monaco Editor | Monaco 5MB包体积对侧边栏场景过重，Worker配置复杂 |
| 2 | 图表引擎 | ECharts GL | Plotly.js | ECharts中文文档+GL大散点性能更适合生信场景 |
| 3 | 沙盒方案 | Docker API | Firecracker/E2B/K8s | 数据挂载刚需+单维护者约束，Docker是唯一现实选择 |
| 4 | Agent框架 | 原生实现 | LangGraph/LangChain | 框架过度工程+版本不稳定，原生实现更简单可控 |
| 5 | Jupyter集成 | 自定义 | JupyterHub/KernelGateway | 不需要Notebook界面，只需代码执行能力 |
| 6 | 后端语言 | Python | Rust | 沙盒调度是IO密集型，Python完全胜任，Rust增加维护负担 |
| 7 | 会话管理 | 预热池 | 每用户长容器 | 预热池在延迟和资源间取得最佳平衡 |
| 8 | MCP传输 | SSE | stdio | Web环境SSE原生支持，stdio不适合前后端分离架构 |

---

### 5.3 技术栈架构全景图

```
+-------------------------------------------------------------------------+
|                              用户浏览器                                   |
|  +---------------------------------------------------------------+     |
|  |                        Vue 3 前端                                |     |
|  |  +--------------+  +--------------+  +--------------------+   |     |
|  |  | AI对话侧边栏  |  | 代码编辑器   |  | 图表/结果展示       |   |     |
|  |  | (380px)      |  | (CodeMirror6)|  | (ECharts GL)        |   |     |
|  |  |              |  |              |  |                     |   |     |
|  |  | +----------+ |  | +----------+ |  | +----------------+ |   |     |
|  |  | |用户消息  | |  | |Python代码| |  | |UMAP散点图      | |   |     |
|  |  | +----------+ |  | |(可编辑)  | |  | |(WebGL 100万点) | |   |     |
|  |  | +----------+ |  | +----------+ |  | +----------------+ |   |     |
|  |  | |AI回复    | |  | [运行][复制] |  | +----------------+ |   |     |
|  |  | |(代码卡片)| |  |              |  | |热图             | |   |     |
|  |  | +----------+ |  | +----------+ |  | +----------------+ |   |     |
|  |  | +----------+ |  | |执行结果  | |  |                    |   |     |
|  |  | |结果分析  | |  | |(标签切换)| |  |                    |   |     |
|  |  | +----------+ |  | +----------+ |  |                    |   |     |
|  |  +--------------+  +--------------+  +--------------------+   |     |
|  +---------------------------------------------------------------+     |
|                                    |                                    |
|                         WebSocket (流式)                               |
+------------------------------------|------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                           Nginx 反向代理                                   |
|                    (WebSocket长连接负载均衡)                                |
+------------------------------------|------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                        FastAPI 主应用 (Docker)                            |
|  +--------------+  +--------------+  +--------------+  +-------------+  |
|  |  认证/授权    |  | AI对话API    |  | 沙盒调度API  |  | MCP SSE端点 |  |
|  |  (已有)      |  | (新增)       |  | (新增)       |  | (新增)      |  |
|  +--------------+  +------+-------+  +------+-------+  +------+------+  |
|                           |                  |                |         |
|              +------------v------------------v----------------v----+    |
|              |           Agent Orchestrator                        |    |
|              |  +--------+  +--------+  +--------+  +--------+    |    |
|              |  |Code    |  |Analysis|  |MCP     |  |Sandbox |    |    |
|              |  |Agent   |  |Agent   |  |Client  |  |Bridge  |    |    |
|              |  +--------+  +--------+  +--------+  +--------+    |    |
|              +-----------------------------------------------------+    |
|                                                                         |
|  +----------------------------------------------------------------------+|
|  |  已有服务: PostgreSQL | Redis | Celery Worker | Nextflow/Snakemake   ||
|  +----------------------------------------------------------------------+|
+-------------------------------------------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                      Docker 沙盒网络 (sandbox-net)                         |
|                                                                          |
|   +------------+  +------------+  +------------+  +-----------------+  |
|   | 预热池容器0 |  | 预热池容器1 |  | 预热池容器2 |  | ... 运行中容器    |  |
|   | (Python +  |  | (Python +  |  | (Python +  |  |     (用户会话绑定) |  |
|   |  Bioconda) |  |  Bioconda) |  |  Bioconda) |  |                    |  |
|   |            |  |            |  |            |  |  +--------------+  |  |
|   | WebSocket  |  | WebSocket  |  | WebSocket  |  |  | /data (只读)  |  |  |
|   | 服务端8888 |  | 服务端8888 |  | 服务端8888 |  |  | /workspace   |  |  |
|   +------------+  +------------+  +------------+  |  | /tmp (tmpfs) |  |  |
|                                                   |  +--------------+  |  |
|                                                   +--------------------+  |
|  数据挂载:                                                                |
|  - /data/omics  ->  h5ad/rds 组学数据 (只读)                              |
|  - /data/ref    ->  参考基因组 (只读)                                      |
|  - /workspace   ->  分析结果输出                                           |
|  - pip/conda cache -> 持久化包缓存                                         |
+-------------------------------------------------------------------------+
```

---

### 5.4 实施优先级建议

| 阶段 | 模块 | 预估工时 | 关键依赖 |
|------|------|---------|---------|
| **Phase 1 (2周)** | 沙盒核心：Docker镜像 + WebSocket执行 + 预热池 | 40h | Docker, docker-py |
| **Phase 1 (1周)** | 前端代码面板：CodeMirror 6 + 运行按钮 + 结果展示 | 20h | CodeMirror 6, ECharts |
| **Phase 2 (1周)** | Agent核心：Prompt模板 + LLM流式接口 + 代码生成 | 20h | Kimi API, FastAPI WS |
| **Phase 2 (1周)** | 图表渲染：ECharts GL UMAP + 热图 + 结果标签页 | 20h | ECharts GL, vue-echarts |
| **Phase 3 (1周)** | MCP集成：Nextflow/Snakemake工具暴露 + SSE端点 | 20h | MCP SDK |
| **Phase 3 (1周)** | 安全加固：read-only rootfs + 资源限制 + 网络隔离 | 20h | Docker security |
| **Phase 4 (1周)** |  polish：错误恢复 + 代码修复 + 性能优化 | 20h | - |
| **总计** | | **约10周 (1人全职)** | |

---

### 5.5 风险评估与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Docker 冷启动延迟 >2s | 中 | 中 | 预热池策略，最坏情况显示"正在准备环境" |
| 大文件 (10GB h5ad) 读取慢 | 高 | 高 | 数据预加载到内存映射文件，只读挂载 |
| LLM代码生成错误率高 | 高 | 高 | 内置代码验证 + 错误自动修复循环 + 人工确认 |
| 单维护者休假/离职 | 中 | 极高 | 文档完善 + 容器化部署简单可移交 |
| 沙盒容器内存泄漏 | 中 | 中 | 30分钟强制回收 + 资源监控告警 |
| 并发突增导致资源不足 | 低 | 高 | 容器池上限控制 + 排队等待提示 |

---

### 5.6 参考资源与延伸阅读

| 资源 | 链接 | 说明 |
|------|------|------|
| CodeMirror 6 文档 | https://codemirror.net/docs/ | 官方文档，模块化架构说明 |
| ECharts GL | https://github.com/ecomfe/echarts-gl | WebGL 扩展，大散点渲染 |
| Docker Python SDK | https://docker-py.readthedocs.io/ | docker-py 官方文档 |
| Python MCP SDK | https://github.com/modelcontextprotocol/python-sdk | MCP Python SDK |
| Scanpy 文档 | https://scanpy.readthedocs.io/ | 单细胞分析核心库 |
| Bioconda | https://bioconda.github.io/ | 生信软件包管理 |
| E2B 架构分析 | https://github.com/e2b-dev/e2b | SDK开源，运行时闭源 |
| LangGraph 文档 | https://langchain-ai.github.io/langgraph/ | 如需未来迁移参考 |

---

> **最终结论**：OmicHub "AI Copilot 与交互式代码执行沙盒"模块的推荐技术栈以 **"极简运维、单维护者友好、生信场景专用"** 为核心原则。前端采用 CodeMirror 6 + ECharts GL，后端保持 Python FastAPI，沙盒采用 Docker API + 预热容器池，Agent 采用原生实现 + MCP SDK。这套方案在当前约束条件下是**技术可行性和维护可持续性的最佳平衡点**。

