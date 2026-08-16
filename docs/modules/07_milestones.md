# 6.7 开发里程碑（MVP → v1.0）

> **项目背景**：OmicsHub 是组内多组学分析平台，当前维护者仅 1 人（全栈开发），组内无专业前端/UI 设计师。核心诉求是尽快替代命令行提交任务的方式，让组内成员通过 Web 界面即可提交和监控分析任务。
>
> **技术栈**：前端 Vue 3 + TypeScript + Naive UI；后端 FastAPI + Pydantic v2 + PostgreSQL + Redis + Celery；执行层 Snakemake（本地/远程混合模式）；部署 Docker + Docker Compose。

---

## 目录

- [里程碑时间线总览（甘特图）](#里程碑时间线总览甘特图)
- [Phase 1: MVP — 可实际使用的 RNA-seq 分析平台](#phase-1-mvp--minimum-viable-product)
- [Phase 2: v0.8 — 平台化扩展](#phase-2-v08--平台化扩展)
- [Phase 3: v1.0 — 生产就绪](#phase-3-v10--生产就绪)
- [风险与应对](#风险与应对)
- [技术债务管理](#技术债务管理)

---

## 里程碑时间线总览（甘特图）

假设开发起始日为 **Week 1 周一**，总计 **10-14 周**（约 2.5-3.5 个月）。

```mermaid
gantt
    title OmicsHub 开发里程碑
    dateFormat YYYY-MM-DD
    axisFormat W%W
    tickInterval 1week

    section Phase 1 MVP
    P1-1 基础设施搭建           :p1_infra, 2025-01-06, 5d
    P1-2 用户认证模块            :p1_auth, after p1_infra, 3d
    P1-3 YAML 配置与动态表单     :p1_yaml, after p1_auth, 5d
    P1-4 样本表上传与解析        :p1_sample, after p1_yaml, 3d
    P1-5 Snakemake 本地执行      :p1_exec, after p1_sample, 5d
    P1-6 任务列表与状态监控      :p1_monitor, after p1_exec, 4d
    P1-7 日志实时推送(WebSocket) :p1_ws, after p1_monitor, 3d
    P1-8 结果文件浏览与下载      :p1_result, after p1_ws, 3d
    P1-9 Docker Compose 部署     :p1_docker, after p1_result, 4d
    P1-10 集成测试与修复         :p1_test, after p1_docker, 5d
    P1 里程碑评审               :milestone, after p1_test, 0d

    section Phase 2 v0.8
    P2-1 流程配置中心(多流程)    :p2_flow, 2025-02-17, 5d
    P2-2 YAML校验与版本管理      :p2_val, after p2_flow, 3d
    P2-3 高级动态表单(条件渲染)  :p2_form, after p2_val, 4d
    P2-4 AI对话助手(基础版)      :p2_ai, after p2_form, 4d
    P2-5 MCP服务集成             :p2_mcp, after p2_ai, 4d
    P2-6 任务管理增强            :p2_task, after p2_mcp, 3d
    P2-7 集成测试与修复          :p2_test, after p2_task, 4d
    P2 里程碑评审               :milestone, after p2_test, 0d

    section Phase 3 v1.0
    P3-1 远程执行模式(Remote)    :p3_remote, 2025-03-17, 5d
    P3-2 结果可视化(ECharts)      :p3_viz, after p3_remote, 5d
    P3-3 项目管理(样本层级)      :p3_proj, after p3_viz, 4d
    P3-4 AI增强(工具调用)        :p3_ai2, after p3_proj, 4d
    P3-5 管理后台               :p3_admin, after p3_ai2, 3d
    P3-6 安全与运维加固          :p3_sec, after p3_admin, 3d
    P3-7 完整文档               :p3_doc, after p3_sec, 3d
    P3-8 生产环境部署与压测       :p3_prod, after p3_doc, 4d
    P3 里程碑评审(v1.0 发布)     :milestone, after p3_prod, 0d
```

**时间线说明**：

| 阶段 | 预计工期 | 日历时间 | 关键交付物 |
|------|----------|----------|-----------|
| Phase 1 MVP | 4-6 周 | Week 1-6 | 可提交 RNA-seq 任务的完整平台 |
| Phase 2 v0.8 | 3-4 周 | Week 7-10 | 多流程支持 + AI 对话 + MCP |
| Phase 3 v1.0 | 3-4 周 | Week 11-14 | 远程模式 + 可视化 + 生产就绪 |

> **缓冲策略**：每个阶段预留 1 周缓冲时间用于 Bug 修复和意外问题处理。

---

## Phase 1: MVP — Minimum Viable Product

### 目标

一个可实际使用的 RNA-seq 分析流程提交平台。组内成员完全告别命令行，通过 Web 界面即可完成 RNA-seq 分析任务的全生命周期管理。

### 开发优先级排序（按依赖关系）

| 优先级 | 功能点 | 预估工时 | 前置依赖 | 可演示时间点 |
|--------|--------|----------|----------|-------------|
| P0 | 项目脚手架与基础设施 | 5d | 无 | Week 1 第 5 天 |
| P0 | 数据库模型与 Alembic 迁移 | 2d | 基础设施 | Week 1 第 7 天 |
| P0 | 用户注册/登录（JWT + 组内邮箱） | 3d | 数据库模型 | Week 2 第 3 天 |
| P0 | YAML 流程配置解析引擎 | 4d | 数据库模型 | Week 2 第 7 天 |
| P0 | 动态表单渲染系统（字符串/数值/选择/布尔/文件） | 4d | YAML 解析引擎 | Week 3 第 4 天 |
| P0 | 样本表上传与自动解析（CSV/Excel） | 3d | 动态表单 | Week 3 第 7 天 |
| P0 | Snakemake 本地执行引擎（subprocess） | 4d | 样本表 | Week 4 第 4 天 |
| P0 | 任务目录隔离与文件管理 | 1d | 执行引擎 | Week 4 第 5 天 |
| P0 | 任务数据库模型与 CRUD API | 2d | 用户认证 | Week 4 第 7 天 |
| P1 | 任务列表页面与状态监控 | 3d | 任务 CRUD | Week 5 第 3 天 |
| P1 | WebSocket 日志实时推送 | 3d | 执行引擎 | Week 5 第 6 天 |
| P1 | 进度解析（X of Y steps done） | 2d | WebSocket | Week 5 第 8 天 |
| P1 | 结果文件列表与下载 | 3d | 任务目录 | Week 6 第 3 天 |
| P1 | Docker Compose 一键部署 | 4d | 所有功能 | Week 6 第 7 天 |
| P2 | 初始化脚本（DB/Admin/示例流程） | 2d | Docker | Week 6 第 9 天 |
| P2 | 集成测试与 Bug 修复 | 5d | 全部完成 | Week 7 第 5 天 |

**MVP 总工时：约 46 天（~9 周 person-days，考虑单维护者，日历时间约 5-6 周）**

### 详细功能说明

#### 1. 用户注册/登录（简单实现）

**需求描述**：组内使用，不需要复杂的权限管理。支持邮箱注册、登录、JWT Token 刷新。

**技术实现**：
- FastAPI + `python-jose` + `passlib`
- 邮箱域名白名单限制（如 `@lab.university.edu.cn`）
- 前端 `localStorage` 存储 JWT，Axios 拦截器自动刷新

**API 设计**：
```python
POST /api/v1/auth/register  # 注册（邮箱+密码+姓名）
POST /api/v1/auth/login     # 登录（邮箱+密码）
POST /api/v1/auth/refresh   # 刷新 Token
GET  /api/v1/auth/me        # 获取当前用户信息
```

**预估工时**：3 天

**可演示标准**：可以在前端完成注册和登录，登录后可以看到个人信息。

---

#### 2. RNA-seq 流程的 YAML 配置

**需求描述**：定义一套完整的 RNA-seq 分析流程配置规范，支持动态表单渲染。这是整个平台的核心基石。

**YAML 规范定义**：

```yaml
# /server/workflows/rnaseq.yaml
meta:
  id: rnaseq-v1
  name: "RNA-seq 差异表达分析"
  version: "1.0.0"
  description: "从原始 FASTQ 到差异表达基因的完整 RNA-seq 分析流程"
  category: "转录组学"
  author: "OmicsHub"
  docker_image: "omicshub/rnaseq:1.0"
  entrypoint: "Snakefile"

parameters:
  # === 输入参数 Section ===
  - section: "输入数据"
    description: "原始测序数据与参考基因组"
    collapsed: false
    fields:
      - name: raw_data_dir
        label: "原始数据目录"
        type: string
        required: true
        default: ""
        help: "存放 FASTQ.gz 文件的目录绝对路径"
        placeholder: "/data/raw/rnaseq/"
      
      - name: genome
        label: "参考基因组"
        type: select
        required: true
        options:
          - value: hg38
            label: "人类 (GRCh38/hg38)"
          - value: mm39
            label: "小鼠 (GRCm39/mm39)"
          - value: rn7
            label: "大鼠 (mRatBN7.2/rn7)"
        help: "选择比对参考基因组版本"
      
      - name: annotation
        label: "注释文件"
        type: select
        required: true
        options:
          - value: gencode_v43
            label: "GENCODE v43"
          - value: ensembl_v110
            label: "Ensembl v110"
        help: "基因注释文件版本"
  
  # === 比对参数 Section ===
  - section: "比对参数"
    description: "序列比对工具与参数"
    collapsed: true
    fields:
      - name: aligner
        label: "比对工具"
        type: select
        required: true
        default: "star"
        options:
          - value: star
            label: "STAR（推荐，速度快）"
          - value: hisat2
            label: "HISAT2（内存占用低）"
        help: "选择 reads 比对到参考基因组的工具"
      
      - name: star_threads
        label: "STAR 线程数"
        type: integer
        required: false
        default: 8
        min: 1
        max: 64
        condition:
          field: aligner
          equals: "star"
        help: "STAR 比对使用的 CPU 线程数"
      
      - name: hisat2_threads
        label: "HISAT2 线程数"
        type: integer
        required: false
        default: 8
        min: 1
        max: 64
        condition:
          field: aligner
          equals: "hisat2"
        help: "HISAT2 比对使用的 CPU 线程数"
  
  # === 差异分析参数 Section ===
  - section: "差异表达分析"
    description: "DESeq2 差异分析参数"
    collapsed: false
    fields:
      - name: padj_threshold
        label: "校正 p 值阈值"
        type: float
        required: false
        default: 0.05
        min: 0.001
        max: 1.0
        step: 0.001
        help: "差异表达基因的 BH 校正 p 值阈值"
      
      - name: log2fc_threshold
        label: "log2 倍数变化阈值"
        type: float
        required: false
        default: 1.0
        min: 0.0
        max: 5.0
        step: 0.1
        help: "差异表达基因的 log2(FoldChange) 绝对值阈值"
      
      - name: run_gsea
        label: "执行 GSEA 富集分析"
        type: boolean
        required: false
        default: true
        help: "是否执行基因集富集分析 (GSEA)"

  # === 高级参数 Section ===
  - section: "高级参数"
    description: "通常不需要修改的高级参数"
    collapsed: true
    fields:
      - name: fastp_options
        label: "fastp 附加参数"
        type: string
        required: false
        default: "--detect_adapter_for_pe"
        help: "传递给 fastp 质控工具的附加参数"
      
      - name: save_intermediates
        label: "保存中间文件"
        type: boolean
        required: false
        default: false
        help: "是否保留比对 BAM 等中间文件（占用大量存储空间）"
```

**动态表单渲染规则**：

| 参数类型 | Vue 组件 | 校验规则 | 特殊行为 |
|----------|----------|----------|----------|
| `string` | NInput | 必填校验、正则 | placeholder 提示 |
| `integer` | NInputNumber | min/max 范围 | step 步进 |
| `float` | NInputNumber | min/max、精度 | step 步进 |
| `select` | NSelect | 必选 | 支持 search/filter |
| `boolean` | NSwitch | 无 | 默认开关样式 |
| `file` | NUpload | 文件大小、类型 | 多文件支持 |

**预估工时**：5 天（YAML 规范设计 2d + 解析引擎 1.5d + 前端表单渲染 1.5d）

**可演示标准**：上传 YAML 后可以正确渲染出分组、折叠的表单，各字段类型正确显示。

---

#### 3. 样本表上传与自动解析

**需求描述**：用户上传 CSV/Excel 格式的样本表，系统自动解析列名、校验格式、检测分组信息。

**样本表格式规范**：

```csv
sample_name,fastq_1,fastq_2,group
WT_1,/data/raw/WT_1_R1.fastq.gz,/data/raw/WT_1_R2.fastq.gz,WT
WT_2,/data/raw/WT_2_R1.fastq.gz,/data/raw/WT_2_R2.fastq.gz,WT
KO_1,/data/raw/KO_1_R1.fastq.gz,/data/raw/KO_1_R2.fastq.gz,KO
KO_2,/data/raw/KO_2_R1.fastq.gz,/data/raw/KO_2_R2.fastq.gz,KO
```

**解析逻辑**：
1. 读取 CSV/Excel（pandas）
2. 列名校验（必须有 `sample_name`、`fastq_1`、`group`）
3. 文件路径存在性校验
4. 自动检测分组数量（用于差异分析对比组）
5. 重复样本名检测
6. 预览表格渲染（前端）

**预估工时**：3 天

**可演示标准**：上传样本表 CSV 后，前端显示解析预览，错误行高亮提示。

---

#### 4. 本地 Snakemake 执行模式

**需求描述**：通过 subprocess 调用 Snakemake，实现任务目录隔离、日志捕获、进度解析。

**执行引擎架构**：

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│   Frontend   │◄───►│  FastAPI WS  │◄───►│   Snakemake Runner   │
│  (Task Page) │ WS  │  (Celery)    │     │  (subprocess + log)  │
└──────────────┘     └──────────────┘     └──────────────────────┘
                           │                        │
                           ▼                        ▼
                    ┌──────────────┐       ┌──────────────────────┐
                    │  PostgreSQL  │       │  /data/tasks/{id}/   │
                    │  (Task Meta) │       │  (任务目录隔离)       │
                    └──────────────┘       └──────────────────────┘
```

**任务目录结构**：

```
/data/tasks/
└── {task_id}/                    # UUID v4
    ├── config.yaml               # Snakemake 配置文件（自动生成）
    ├── samples.csv               # 样本表（用户上传）
    ├── Snakefile -> /workflows/rnaseq/Snakefile  # 流程文件软链接
    ├── log/
    │   └── snakemake.log         # 完整执行日志
    ├── results/                  # 分析结果输出目录
    │   ├── 01_fastqc/
    │   ├── 02_fastp/
    │   ├── 03_align/
    │   ├── 04_count/
    │   ├── 05_deseq2/
    │   └── 06_gsea/
    └── status.json               # 任务状态文件（实时更新）
```

**执行核心代码**：

```python
# server/core/executor/local.py
import asyncio
import json
import subprocess
from pathlib import Path
from typing import AsyncGenerator

from celery import shared_task
from celery.signals import task_revoked


@shared_task(bind=True)
def run_snakemake_task(self, task_id: str, workflow_id: str, config: dict):
    """
    Celery 任务：执行 Snakemake 流程
    """
    task_dir = Path(f"/data/tasks/{task_id}")
    log_file = task_dir / "log" / "snakemake.log"
    status_file = task_dir / "status.json"
    
    # 更新任务状态为 running
    update_task_status(task_id, "running", progress=0)
    
    # 构建 Snakemake 命令
    cmd = [
        "snakemake",
        "--snakefile", str(task_dir / "Snakefile"),
        "--configfile", str(task_dir / "config.yaml"),
        "--directory", str(task_dir),
        "--cores", str(config.get("threads", 8)),
        "--use-conda",
        "--conda-prefix", "/opt/conda/envs/snakemake",
        "--latency-wait", "60",
        "--keep-going",
        "--rerun-incomplete",
    ]
    
    # 启动 subprocess，实时捕获输出
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    # 日志消费循环
    total_steps = estimate_total_steps(workflow_id)
    completed_steps = 0
    
    for line in process.stdout:
        # 写入日志文件
        log_file.write_text(line, append=True)
        
        # 解析进度
        if "Steps done" in line or " of " in line:
            completed_steps = parse_step_progress(line, total_steps)
            progress = int(completed_steps / total_steps * 100)
            update_task_status(task_id, "running", progress=progress)
            
            # 发送 WebSocket 更新
            broadcast_log(task_id, {
                "type": "progress",
                "completed": completed_steps,
                "total": total_steps,
                "progress": progress,
                "line": line.strip(),
            })
        else:
            broadcast_log(task_id, {
                "type": "log",
                "line": line.strip(),
            })
    
    # 等待进程结束
    return_code = process.wait()
    
    if return_code == 0:
        update_task_status(task_id, "completed", progress=100)
        broadcast_log(task_id, {"type": "status", "status": "completed"})
    else:
        update_task_status(task_id, "failed", error=f"Exit code: {return_code}")
        broadcast_log(task_id, {"type": "status", "status": "failed"})


def parse_step_progress(line: str, total: int) -> int:
    """解析 Snakemake 进度输出"""
    # 匹配 "X of Y steps (Z%) done" 或 "Finished job N."
    import re
    
    # Pattern 1: "5 of 23 steps (22%) done"
    match = re.search(r'(\d+)\s+of\s+(\d+)\s+steps', line)
    if match:
        return int(match.group(1))
    
    # Pattern 2: "Finished job N."
    match = re.search(r'Finished job (\d+)\.', line)
    if match:
        return int(match.group(1))
    
    return 0
```

**WebSocket 实时推送**：

```python
# server/api/ws.py
from fastapi import WebSocket, WebSocketDisconnect
from server.core.redis import redis_client

class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
    
    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)
    
    def disconnect(self, task_id: str, websocket: WebSocket):
        self.active_connections[task_id].remove(websocket)
    
    async def broadcast(self, task_id: str, message: dict):
        """广播消息到所有关注该任务的客户端"""
        if task_id in self.active_connections:
            for ws in self.active_connections[task_id]:
                await ws.send_json(message)


manager = ConnectionManager()

@router.websocket("/ws/tasks/{task_id}/log")
async def task_log_websocket(websocket: WebSocket, task_id: str):
    await manager.connect(task_id, websocket)
    try:
        while True:
            # 保持连接，等待客户端发送心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(task_id, websocket)
```

**预估工时**：5 天（执行引擎 2d + WebSocket 1.5d + 进度解析 1d + 目录管理 0.5d）

**可演示标准**：提交任务后，前端实时滚动显示 Snakemake 日志，进度条随步骤推进。

---

#### 5. 任务列表与状态监控

**需求描述**：任务的全生命周期管理——创建、查看状态、查看日志、下载结果。

**任务状态机**：

```
        ┌──────────┐
        │ pending  │  提交成功，等待调度
        └────┬─────┘
             │ Celery Worker 接收
             ▼
        ┌──────────┐
   ┌───►│ running  │◄──────┐  正在执行 Snakemake
   │    └────┬─────┘       │
   │         │              │
   │    success          failed (可重试)
   │         │              │
   │         ▼              │
   │    ┌──────────┐        │
   │    │completed │────────┘  执行成功，结果可用
   │    └────┬─────┘
   │         │
   │    failed (不可恢复)
   │         │
   │         ▼
   │    ┌──────────┐
   └───►│  failed  │  执行失败，可查看错误日志
        └──────────┘
```

**API 设计**：

```python
# 任务管理 API
POST   /api/v1/tasks              # 创建任务
GET    /api/v1/tasks              # 任务列表（分页、筛选、排序）
GET    /api/v1/tasks/{id}         # 任务详情
GET    /api/v1/tasks/{id}/log     # 获取任务日志（支持 offset 分页）
GET    /api/v1/tasks/{id}/results # 获取结果文件列表
GET    /api/v1/tasks/{id}/download/{path}  # 下载结果文件
DELETE /api/v1/tasks/{id}         # 删除任务（仅 pending/failed）
```

**前端页面**：

```
┌─────────────────────────────────────────────────────┐
│  OmicsHub                              [用户头像 ▼] │
├────────────┬────────────────────────────────────────┤
│            │  任务管理                              │
│  仪表盘     ├────────────────────────────────────────┤
│  新建任务   │  [+ 新建任务]  [搜索...] [状态 ▼]     │
│  任务列表 ► │                                        │
│  结果浏览   │  ┌──────────────────────────────────┐  │
│            │  │ ■ 任务 #20250106-001             │  │
│            │  │ RNA-seq 差异表达分析               │  │
│            │  │ 状态: ● running  进度: 68%        │  │
│            │  │ 提交: 2025-01-06 14:32            │  │
│            │  │ [查看详情] [查看日志] [取消]      │  │
│            │  └──────────────────────────────────┘  │
│            │                                        │
│            │  ┌──────────────────────────────────┐  │
│            │  │ ■ 任务 #20250105-003             │  │
│            │  │ RNA-seq 差异表达分析               │  │
│            │  │ 状态: ✓ completed  进度: 100%   │  │
│            │  │ 提交: 2025-01-05 09:15            │  │
│            │  │ [查看详情] [查看结果] [下载全部]  │  │
│            │  └──────────────────────────────────┘  │
│            │                                        │
├────────────┤  分页: [1] [2] [3] ... [10]           │
│            │                                        │
└────────────┴────────────────────────────────────────┘
```

**预估工时**：4 天（后端 API 2d + 前端页面 2d）

---

#### 6. Docker Compose 一键部署

**目录结构**：

```
omichub/
├── docker-compose.yml              # 主部署文件
├── docker-compose.override.yml     # 本地开发覆盖
├── .env.example                    # 环境变量模板
├── init/
│   ├── init-db.sql                 # 数据库初始化
│   ├── init-admin.py               # 创建默认管理员
│   └── init-workflows.py           # 导入示例流程
├── server/
│   ├── Dockerfile
│   ├── entrypoint.sh               # 启动脚本（迁移+启动）
│   └── ...
├── web/
│   ├── Dockerfile
│   └── ...
├── nginx/
│   └── nginx.conf                  # 反向代理配置
├── redis/
│   └── redis.conf
└── postgres/
    └── Dockerfile
```

**docker-compose.yml**：

```yaml
version: "3.8"

services:
  web:
    build: ./web
    container_name: omicshub-web
    ports:
      - "80:80"
    depends_on:
      - server
    networks:
      - omicshub-net

  server:
    build: ./server
    container_name: omicshub-server
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - SECRET_KEY=${SECRET_KEY:-change-me-in-production}
      - EXECUTION_MODE=local
      - TASK_DATA_DIR=/data/tasks
      - WORKFLOW_DIR=/workflows
    volumes:
      - ${TASK_DATA_HOST:-./data/tasks}:/data/tasks
      - ${WORKFLOW_HOST:-./workflows}:/workflows
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - omicshub-net

  worker:
    build: ./server
    container_name: omicshub-worker
    command: celery -A server.core.celery worker --loglevel=info --concurrency=2
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - TASK_DATA_DIR=/data/tasks
      - WORKFLOW_DIR=/workflows
    volumes:
      - ${TASK_DATA_HOST:-./data/tasks}:/data/tasks
      - ${WORKFLOW_HOST:-./workflows}:/workflows
    depends_on:
      - redis
      - postgres
    networks:
      - omicshub-net

  postgres:
    image: postgres:16-alpine
    container_name: omicshub-postgres
    environment:
      - POSTGRES_DB=omicshub
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=${DB_PASSWORD:-postgres}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init/init-db.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - omicshub-net

  redis:
    image: redis:7-alpine
    container_name: omicshub-redis
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - omicshub-net

volumes:
  postgres_data:
  redis_data:

networks:
  omicshub-net:
    driver: bridge
```

**预估工时**：4 天（Dockerfile 编写 1d + Compose 编排 1d + 初始化脚本 1d + 测试调优 1d）

---

### Phase 1 验收标准

| 验收项 | 标准 | 测试方法 |
|--------|------|----------|
| 用户注册/登录 | 组内邮箱可以注册并登录 | 手动测试：注册 → 登录 → 查看用户信息 |
| RNA-seq 任务提交 | 通过 Web 表单完成参数配置并提交 | 手动测试：填写表单 → 上传样本表 → 提交 → 验证 DB |
| 任务正常执行 | Snakemake 能跑完整个流程 | 使用测试数据集（ yeast 或小鼠公开数据）完整跑通 |
| 实时日志查看 | 前端页面实时滚动显示日志，无断连 | 提交任务 → 打开任务详情 → 观察日志实时更新 |
| 进度显示 | 进度条与 Snakemake 步骤同步 | 对比日志中的 "X of Y" 与前端进度条 |
| 结果文件下载 | 可以列出结果文件并下载 | 任务完成后 → 结果页面 → 点击下载 |
| 一键部署 | `docker-compose up -d` 后所有服务正常 | 全新环境执行，验证所有容器 healthy |

### Phase 1 技术债务（允许范围）

| 债务项 | 原因 | 偿还时间 |
|--------|------|----------|
| 用户权限只有 admin/user 两种角色 | 组内使用，不需要 RBAC | Phase 3 |
| 样本表不上传到服务器，只传路径 | MVP 快速实现，无文件存储管理 | Phase 2 |
| YAML 流程硬编码在前端或后端 | 快速实现单流程支持 | Phase 2（流程配置中心） |
| WebSocket 连接不做断线重连 | 组内局域网稳定 | Phase 2 |
| 没有任务取消功能 | Celery revoke 实现复杂度 | Phase 2 |
| 日志不做持久化归档 | 本地存储，任务目录即日志 | Phase 3 |

---

## Phase 2: v0.8 — 平台化扩展

### 目标

从单流程工具升级为真正的多组学分析平台。支持管理员动态上传流程，集成 AI 对话助手和 MCP 服务，提供更丰富的交互体验。

### 开发优先级排序

| 优先级 | 功能点 | 预估工时 | 前置依赖 | 可演示时间点 |
|--------|--------|----------|----------|-------------|
| P0 | 流程 YAML 配置中心（数据库模型 + CRUD API） | 3d | Phase 1 DB | Week 7 第 3 天 |
| P0 | 管理员上传/编辑 YAML 流程（前端） | 2d | CRUD API | Week 7 第 5 天 |
| P0 | YAML 校验引擎（schema 校验 + 语义校验） | 2d | 上传功能 | Week 7 第 7 天 |
| P0 | 多流程切换与动态加载 | 2d | 校验引擎 | Week 8 第 2 天 |
| P0 | 高级动态表单（条件渲染 + 可重复 Group + 折叠 Section） | 4d | 多流程加载 | Week 8 第 6 天 |
| P1 | AI 对话助手（基础版：常驻面板 + 基础问答） | 4d | 无 | Week 9 第 3 天 |
| P1 | MCP Server 注册（管理员后台） | 2d | AI 助手 | Week 9 第 5 天 |
| P1 | MCP 工具调用与结果渲染 | 2d | MCP 注册 | Week 9 第 7 天 |
| P1 | 任务取消功能（Celery revoke + 清理） | 2d | 无 | Week 10 第 2 天 |
| P1 | 任务优先级 + 邮件通知 | 2d | 取消功能 | Week 10 第 4 天 |
| P2 | 集成测试与修复 | 4d | 全部功能 | Week 10 第 8 天 |

**Phase 2 总工时：约 29 天（~6 周 person-days，日历时间约 3-4 周）**

### 详细功能说明

#### 1. 流程 YAML 配置中心

**需求描述**：管理员可以在 Web 界面上传、编辑、管理分析流程 YAML，支持多流程（RNA-seq、ATAC-seq、scRNA-seq 等）。

**数据库设计**：

```python
# server/models/workflow.py
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from server.models.base import BaseModel


class Workflow(BaseModel):
    """分析流程定义"""
    __tablename__ = "workflows"
    
    id = Column(String(32), primary_key=True)           # 如 "rnaseq-v1"
    name = Column(String(128), nullable=False)           # 显示名称
    version = Column(String(16), nullable=False)         # 语义化版本
    description = Column(Text)
    category = Column(String(64), index=True)            # "转录组学"/"表观组学"
    author = Column(String(64), default="OmicsHub")
    
    # YAML 配置内容（完整存储）
    yaml_content = Column(Text, nullable=False)
    
    # 解析后的元数据（冗余存储，加速查询）
    meta_json = Column(JSON)                             # meta 部分
    parameters_schema = Column(JSON)                     # parameters 部分
    docker_image = Column(String(256))
    entrypoint = Column(String(256), default="Snakefile")
    
    # 状态管理
    is_active = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)          # 内置流程不可删除
    
    # 版本控制
    parent_id = Column(String(32), ForeignKey("workflows.id"), nullable=True)
    changelog = Column(Text)
    
    # 统计
    task_count = Column(Integer, default=0)
    
    # 关联
    tasks = relationship("Task", back_populates="workflow")
    versions = relationship("Workflow", backref="parent", remote_side=[id])
```

**API 设计**：

```python
# 流程管理 API（管理员）
POST   /api/v1/admin/workflows              # 上传新流程 YAML
PUT    /api/v1/admin/workflows/{id}         # 编辑流程
POST   /api/v1/admin/workflows/{id}/clone   # 克隆流程（创建新版本）
DELETE /api/v1/admin/workflows/{id}         # 删除流程（仅非内置）
POST   /api/v1/admin/workflows/{id}/validate # 校验 YAML

# 流程浏览 API（普通用户）
GET    /api/v1/workflows                    # 流程列表（支持分类筛选、搜索）
GET    /api/v1/workflows/{id}               # 流程详情
GET    /api/v1/workflows/{id}/parameters    # 获取参数 schema（用于渲染表单）
GET    /api/v1/workflows/{id}/versions      # 获取版本历史
```

**前端页面**：

```
┌────────────────────────────────────────────────────────────┐
│  流程管理（管理员）                                        │
├────────────────────────────────────────────────────────────┤
│  [+ 新建流程]  [搜索...]  [分类 ▼]  [仅显示内置 □]        │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  🔬 RNA-seq 差异表达分析          转录组学 | v1.2.0   │  │
│  │  内置流程 | 任务数: 156 | 最后更新: 2025-01-15        │  │
│  │  [查看参数] [编辑 YAML] [克隆] [查看版本]             │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  🧬 ATAC-seq 染色质可及性分析      表观组学 | v0.9.0  │  │
│  │  用户上传 | 任务数: 23 | 最后更新: 2025-01-20         │  │
│  │  [查看参数] [编辑 YAML] [克隆] [删除] [查看版本]      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  🧪 scRNA-seq 单细胞分析          单细胞组学 | v1.0.0 │  │
│  │  用户上传 | 任务数: 8 | 最后更新: 2025-01-22          │  │
│  │  [查看参数] [编辑 YAML] [克隆] [删除] [查看版本]      │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**预估工时**：5 天（数据库 1d + API 1.5d + 前端 2d + 版本管理 0.5d）

---

#### 2. YAML 校验引擎

**校验层次**：

```python
# server/core/workflow/validator.py
from pydantic import BaseModel, Field, validator
from typing import Literal, Any
import yaml


class FieldSchema(BaseModel):
    """参数字段 schema 校验"""
    name: str = Field(..., regex=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    label: str
    type: Literal['string', 'integer', 'float', 'select', 'boolean', 'file', 'group']
    required: bool = True
    default: Any = None
    help: str = ""
    placeholder: str = ""
    
    # 条件渲染
    condition: dict | None = None  # {field: str, equals: Any}
    
    # 数值范围
    min: float | None = None
    max: float | None = None
    step: float | None = None
    
    # select 选项
    options: list[dict] | None = None  # [{value, label}]
    
    # group（可重复组）
    repeatable: bool = False
    fields: list['FieldSchema'] | None = None  # 嵌套字段


class ParameterSection(BaseModel):
    """参数分组 Section 校验"""
    section: str
    description: str = ""
    collapsed: bool = False
    fields: list[FieldSchema]


class WorkflowMeta(BaseModel):
    """Meta 部分校验"""
    id: str = Field(..., regex=r'^[a-z0-9-]+$')
    name: str
    version: str = Field(..., regex=r'^\d+\.\d+\.\d+$')
    description: str
    category: str
    docker_image: str | None = None
    entrypoint: str = "Snakefile"


class WorkflowSchema(BaseModel):
    """完整 YAML 校验"""
    meta: WorkflowMeta
    parameters: list[ParameterSection]
    
    @validator('parameters')
    def check_unique_field_names(cls, v):
        """检查字段名全局唯一"""
        names = set()
        for section in v:
            for field in section.fields:
                if field.name in names:
                    raise ValueError(f"Duplicate field name: {field.name}")
                names.add(field.name)
        return v


def validate_workflow_yaml(yaml_content: str) -> tuple[bool, list[str]]:
    """
    校验 YAML 流程配置
    返回: (是否通过, 错误信息列表)
    """
    errors = []
    
    # Layer 1: YAML 语法校验
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return False, [f"YAML 语法错误: {e}"]
    
    # Layer 2: Schema 结构校验
    try:
        WorkflowSchema(**data)
    except Exception as e:
        return False, [f"Schema 校验失败: {e}"]
    
    # Layer 3: 语义校验
    meta = data.get('meta', {})
    params = data.get('parameters', [])
    
    # 3.1 检查 condition 引用的字段存在
    for section in params:
        for field in section.get('fields', []):
            if condition := field.get('condition'):
                ref_field = condition.get('field')
                if not any(f['name'] == ref_field 
                          for s in params 
                          for f in s.get('fields', [])):
                    errors.append(f"条件渲染引用了不存在的字段: {ref_field}")
    
    # 3.2 检查 select 选项非空
    for section in params:
        for field in section.get('fields', []):
            if field.get('type') == 'select' and not field.get('options'):
                errors.append(f"Select 字段 {field['name']} 缺少 options")
    
    # 3.3 检查 docker_image 格式（如果提供）
    if docker_image := meta.get('docker_image'):
        if ':' not in docker_image:
            errors.append(f"docker_image 应包含 tag: {docker_image}")
    
    return len(errors) == 0, errors
```

**预估工时**：3 天

---

#### 3. 高级动态表单

**条件渲染实现**：

```vue
<!-- web/components/DynamicForm.vue -->
<script setup lang="ts">
import { computed, watch } from 'vue'
import type { FieldSchema, FormValues } from '@/types/workflow'

interface Props {
  schema: FieldSchema[]
  modelValue: FormValues
}

const props = defineProps<Props>()
const emit = defineEmits<['update:modelValue']>()

// 计算字段可见性
const isFieldVisible = (field: FieldSchema): boolean => {
  if (!field.condition) return true
  const { field: refField, equals } = field.condition
  return props.modelValue[refField] === equals
}

// 当条件字段变化时，重置被隐藏字段的值
watch(() => props.modelValue, (newVal, oldVal) => {
  for (const field of props.schema) {
    if (field.condition && !isFieldVisible(field)) {
      emit('update:modelValue', {
        ...props.modelValue,
        [field.name]: field.default ?? null
      })
    }
  }
}, { deep: true })
</script>

<template>
  <div class="dynamic-form">
    <template v-for="field in schema" :key="field.name">
      <n-form-item
        v-if="isFieldVisible(field)"
        :label="field.label"
        :path="field.name"
        :required="field.required"
      >
        <!-- String -->
        <n-input
          v-if="field.type === 'string'"
          v-model:value="modelValue[field.name]"
          :placeholder="field.placeholder"
        />
        
        <!-- Integer / Float -->
        <n-input-number
          v-else-if="field.type === 'integer' || field.type === 'float'"
          v-model:value="modelValue[field.name]"
          :min="field.min"
          :max="field.max"
          :step="field.step"
          :precision="field.type === 'float' ? 2 : 0"
        />
        
        <!-- Select -->
        <n-select
          v-else-if="field.type === 'select'"
          v-model:value="modelValue[field.name]"
          :options="field.options?.map(o => ({ label: o.label, value: o.value }))"
          filterable
        />
        
        <!-- Boolean -->
        <n-switch
          v-else-if="field.type === 'boolean'"
          v-model:value="modelValue[field.name]"
        />
        
        <!-- File Upload -->
        <n-upload
          v-else-if="field.type === 'file'"
          v-model:file-list="modelValue[field.name]"
          :max="field.repeatable ? undefined : 1"
        />
        
        <!-- Repeatable Group -->
        <RepeatableGroup
          v-else-if="field.type === 'group' && field.repeatable"
          v-model="modelValue[field.name]"
          :fields="field.fields"
        />
        
        <!-- Help tooltip -->
        <template #feedback v-if="field.help">
          <n-tooltip>
            <template #trigger>
              <n-icon :component="HelpCircleOutline" />
            </template>
            {{ field.help }}
          </n-tooltip>
        </template>
      </n-form-item>
    </template>
  </div>
</template>
```

**可重复 Group 组件**：

```vue
<!-- web/components/RepeatableGroup.vue -->
<script setup lang="ts">
interface Props {
  modelValue: Record<string, any>[]
  fields: FieldSchema[]
}

const props = defineProps<Props>()
const emit = defineEmits<['update:modelValue']>()

const addGroup = () => {
  const newItem: Record<string, any> = {}
  for (const field of props.fields) {
    newItem[field.name] = field.default ?? null
  }
  emit('update:modelValue', [...props.modelValue, newItem])
}

const removeGroup = (index: number) => {
  const newValue = [...props.modelValue]
  newValue.splice(index, 1)
  emit('update:modelValue', newValue)
}
</script>

<template>
  <div class="repeatable-group">
    <n-card
      v-for="(item, index) in modelValue"
      :key="index"
      :title="`对比组 ${index + 1}`"
      closable
      @close="removeGroup(index)"
    >
      <DynamicForm
        :schema="fields"
        v-model="modelValue[index]"
      />
    </n-card>
    
    <n-button dashed @click="addGroup" block>
      <template #icon><n-icon :component="AddOutline" /></template>
      添加对比组
    </n-button>
  </div>
</template>
```

**预估工时**：4 天

---

#### 4. AI 对话助手（基础版）

**需求描述**：常驻右侧边栏的 AI 对话面板，支持基础问答、流程选择建议、参数解释。

**架构设计**：

```
┌──────────────────────────────────────────────────────────────┐
│  OmicsHub                                        [AI助手 ▶] │
├───────────────────────────────┬──────────────────────────────┤
│                               │  🤖 OmicsHub AI 助手         │
│  主内容区                      ├──────────────────────────────┤
│  （表单/任务列表等）             │                              │
│                               │  AI: 你好！我是 OmicsHub     │
│                               │  AI 助手，可以帮你：          │
│                               │  • 选择合适的分析流程         │
│                               │  • 解释参数含义               │
│                               │  • 分析结果解读               │
│                               │                              │
│                               │  ────────────────────────    │
│                               │  你: RNA-seq 和 scRNA-seq    │
│                               │  有什么区别？                 │
│                               │                              │
│                               │  AI: 两者的主要区别在于...    │
│                               │  [关键区别: 1. 样本处理 ...]  │
│                               │                              │
│                               ├──────────────────────────────┤
│                               │  [🎤] [输入问题...     ] [↑] │
│                               │  [📎 附件]                   │
└───────────────────────────────┴──────────────────────────────┘
```

**后端实现**：

```python
# server/api/ai.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ai")


class ChatRequest(BaseModel):
    message: str
    context: dict | None = None  # 当前页面上下文
    history: list[dict] = []     # 对话历史


class ChatResponse(BaseModel):
    reply: str
    suggested_actions: list[dict] | None = None


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    AI 对话接口
    支持上下文感知和基础问答
    """
    # 构建系统提示词
    system_prompt = build_system_prompt(request.context)
    
    # 构建消息列表
    messages = [
        {"role": "system", "content": system_prompt},
        *request.history[-10:],  # 保留最近 10 轮
        {"role": "user", "content": request.message},
    ]
    
    # 调用 LLM
    reply = await call_llm(messages)
    
    # 解析建议操作
    suggested_actions = parse_suggested_actions(reply)
    
    return ChatResponse(
        reply=reply,
        suggested_actions=suggested_actions,
    )


def build_system_prompt(context: dict | None) -> str:
    """根据上下文构建系统提示词"""
    base_prompt = """你是 OmicsHub 的 AI 助手，一个专业的生物信息学分析平台助手。
    
你可以帮助用户：
1. 选择合适的分析流程（RNA-seq、ATAC-seq、scRNA-seq 等）
2. 解释各流程参数的含义和推荐设置
3. 解读分析结果（差异表达基因、富集分析等）
4. 推荐下游分析策略
5. 解答生物信息学常见问题

回答原则：
- 专业但易懂，假设用户有生物学背景但编程经验有限
- 参数推荐要给出具体数值和理由
- 涉及统计方法时简要说明假设条件
"""
    
    if context:
        page = context.get('page')
        if page == 'workflow_submit':
            workflow_id = context.get('workflow_id')
            base_prompt += f"\n当前用户正在提交 {workflow_id} 流程任务。"
            base_prompt += "可以帮助用户理解参数含义和推荐设置。"
        elif page == 'task_detail':
            task_id = context.get('task_id')
            base_prompt += f"\n当前用户正在查看任务 {task_id} 的详情。"
            base_prompt += "可以帮助解读分析结果或排查问题。"
    
    return base_prompt
```

**预估工时**：4 天（后端 API 1d + LLM 集成 1d + 前端面板 1.5d + 提示词调优 0.5d）

---

#### 5. MCP 服务集成（基础版）

**MCP (Model Context Protocol) 集成**：让 AI 助手可以调用外部工具（如 PubMed 文献检索）。

**MCP Server 注册**：

```python
# server/models/mcp.py
class MCPServer(BaseModel):
    """MCP Server 配置"""
    __tablename__ = "mcp_servers"
    
    id = Column(String(32), primary_key=True)
    name = Column(String(64), nullable=False)
    description = Column(Text)
    
    # 连接配置
    transport: Literal["stdio", "sse", "http"] = Column(String(16))
    command: str | None = Column(String(256))  # stdio 模式命令
    args: list[str] = Column(JSON, default=list)
    url: str | None = Column(String(256))      # sse/http 模式 URL
    
    # 认证
    auth_type: str | None = Column(String(32))
    auth_config: dict = Column(JSON, default=dict)
    
    # 状态
    is_active = Column(Boolean, default=True)
    last_connected_at = Column(DateTime, nullable=True)
    
    # 可用工具（运行时缓存）
    tools: list[dict] = Column(JSON, default=list)
```

**PubMed MCP Server 示例**：

```python
# server/core/mcp/servers/pubmed.py
class PubMedMCPServer:
    """PubMed 文献检索 MCP Server"""
    
    def __init__(self):
        self.name = "pubmed-search"
        self.description = "搜索 PubMed 生物医学文献数据库"
    
    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "search_pubmed",
                "description": "使用关键词搜索 PubMed 文献",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "PubMed 搜索查询词"
                        },
                        "max_results": {
                            "type": "integer",
                            "default": 10,
                            "description": "返回的最大结果数"
                        },
                        "sort": {
                            "type": "string",
                            "enum": ["relevance", "date"],
                            "default": "relevance"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_article_details",
                "description": "获取指定 PMID 的文献详细信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pmid": {
                            "type": "string",
                            "description": "PubMed ID"
                        }
                    },
                    "required": ["pmid"]
                }
            }
        ]
    
    async def execute(self, tool_name: str, params: dict) -> dict:
        if tool_name == "search_pubmed":
            return await self._search(params)
        elif tool_name == "get_article_details":
            return await self._get_details(params)
        raise ValueError(f"Unknown tool: {tool_name}")
    
    async def _search(self, params: dict) -> dict:
        """调用 NCBI E-utilities API"""
        import aiohttp
        
        query = params["query"]
        max_results = params.get("max_results", 10)
        
        # ESearch
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": params.get("sort", "relevance")
            }) as resp:
                data = await resp.json()
                pmids = data["esearchresult"]["idlist"]
                
        return {
            "count": data["esearchresult"]["count"],
            "pmids": pmids,
            "query_translation": data["esearchresult"].get("querytranslation", "")
        }
```

**预估工时**：4 天（MCP Server 框架 1.5d + PubMed 接入 1d + 管理员页面 1d + 前端渲染 0.5d）

---

#### 6. 任务管理增强

**任务取消实现**：

```python
# server/api/tasks.py
@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """取消任务"""
    task = await Task.get_by_id(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    
    # 只有 pending 或 running 的任务可以取消
    if task.status not in ["pending", "running"]:
        raise HTTPException(400, f"Cannot cancel task with status {task.status}")
    
    # Celery revoke
    if task.celery_task_id:
        from celery import Celery
        celery_app = Celery('omicshub')
        celery_app.control.revoke(task.celery_task_id, terminate=True)
    
    # 终止 subprocess（如果是本地执行）
    if task.execution_mode == "local" and task.pid:
        import os, signal
        try:
            os.kill(task.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    
    # 更新状态
    await task.update(status="cancelled", ended_at=datetime.utcnow())
    
    # 清理资源（异步）
    from server.core.cleanup import cleanup_task_resources
    cleanup_task_resources.delay(task_id)
    
    return {"message": "Task cancelled successfully"}
```

**邮件通知**（使用 Celery beat 定时任务）：

```python
# server/core/notifications/email.py
from celery import shared_task
from server.core.email import send_email

@shared_task
def send_task_notification(task_id: str, event: str):
    """发送任务状态通知邮件"""
    task = Task.get_by_id(task_id)
    user = User.get_by_id(task.user_id)
    
    subject_map = {
        "completed": f"[OmicsHub] 任务 #{task.id} 已完成",
        "failed": f"[OmicsHub] 任务 #{task.id} 执行失败",
        "cancelled": f"[OmicsHub] 任务 #{task.id} 已取消",
    }
    
    template_map = {
        "completed": "task_completed.html",
        "failed": "task_failed.html",
        "cancelled": "task_cancelled.html",
    }
    
    send_email(
        to=user.email,
        subject=subject_map.get(event, f"[OmicsHub] 任务 #{task.id} 状态更新"),
        template=template_map.get(event),
        context={
            "user_name": user.name,
            "task_id": task.id,
            "task_name": task.name,
            "workflow_name": task.workflow_name,
            "detail_url": f"{settings.FRONTEND_URL}/tasks/{task.id}",
        }
    )
```

**预估工时**：3 天（取消功能 1.5d + 优先级 0.5d + 邮件通知 1d）

### Phase 2 验收标准

| 验收项 | 标准 | 测试方法 |
|--------|------|----------|
| 流程上传 | 管理员可以上传新 YAML 流程 | 上传 ATAC-seq YAML → 前端正确渲染表单 → 可提交任务 |
| YAML 校验 | 错误 YAML 给出明确错误信息 | 上传缺少必填字段的 YAML → 看到具体错误提示 |
| 条件渲染 | 参数联动正常工作 | 选择不同 aligner → 只显示对应线程数参数 |
| 可重复 Group | 可以动态添加/删除对比组 | 差异分析页面添加多个对比组 → 提交验证参数结构 |
| AI 对话 | AI 可以回答流程相关问题 | 提问 "RNA-seq 用什么比对器好" → 得到有意义的回答 |
| MCP PubMed | 可以通过 AI 查询 PubMed | 提问 "搜索 p53 相关文献" → 返回文献列表 |
| 任务取消 | 可以取消正在运行的任务 | 提交任务 → 点击取消 → 状态变为 cancelled |
| 邮件通知 | 任务完成时收到邮件 | 提交短任务 → 完成后检查邮箱 |

### Phase 2 技术债务

| 债务项 | 原因 | 偿还时间 |
|--------|------|----------|
| AI 对话不做持久化存储 | Phase 3 增强时再完善 | Phase 3 |
| MCP Server 只有 PubMed | 先验证架构可行性 | Phase 3 |
| 不做复杂的用户权限 | 仅 admin/user 角色 | Phase 3 |
| 邮件使用同步发送 | Celery 异步足够 | Phase 3 |

---

## Phase 3: v1.0 — 生产就绪

### 目标

平台达到生产环境部署标准。支持远程执行模式、结果可视化、AI 工具调用、完整管理后台和安全加固。

### 开发优先级排序

| 优先级 | 功能点 | 预估工时 | 前置依赖 | 可演示时间点 |
|--------|--------|----------|----------|-------------|
| P0 | 远程执行模式（Master 节点 FastAPI Executor） | 4d | Phase 2 | Week 11 第 4 天 |
| P0 | Web 与 Master 分离部署 + HTTP API | 2d | Executor | Week 11 第 6 天 |
| P0 | WebSocket 日志流（跨节点） | 2d | HTTP API | Week 11 第 8 天 |
| P0 | EXECUTION_MODE 环境变量切换 | 1d | 远程日志 | Week 12 第 1 天 |
| P0 | 结果可视化（差异表达表格 + 火山图 + 热图） | 4d | 远程模式 | Week 12 第 5 天 |
| P0 | UMAP/t-SNE（scRNA-seq） | 2d | ECharts | Week 12 第 7 天 |
| P1 | 项目管理（项目-样本层级） | 3d | 无 | Week 13 第 2 天 |
| P1 | 批量样本上传与校验 | 2d | 项目管理 | Week 13 第 4 天 |
| P1 | AI 工具调用（提交任务、查询样本） | 3d | Phase 2 AI | Week 13 第 7 天 |
| P1 | 确认机制（草稿 → 用户确认 → 执行） | 2d | 工具调用 | Week 14 第 2 天 |
| P1 | 管理后台（用户/MCP/监控） | 3d | 无 | Week 14 第 5 天 |
| P2 | 安全加固（文件隔离、IP 白名单） | 2d | 管理后台 | Week 14 第 7 天 |
| P2 | 完整文档 | 3d | 全部功能 | Week 15 第 3 天 |
| P2 | 生产环境部署与压测 | 3d | 文档 | Week 15 第 6 天 |

**Phase 3 总工时：约 38 天（~7.5 周 person-days，日历时间约 3-4 周）**

### 详细功能说明

#### 1. 远程执行模式（Remote Mode）

**架构设计**：

```
┌─────────────────────────────────────────────────────────────────┐
│                          远程模式架构                             │
│                                                                 │
│  ┌──────────────┐         HTTP API + WS        ┌──────────────┐ │
│  │  Web 节点     │◄────────────────────────────►│ Master 节点   │ │
│  │  (FastAPI)    │    任务提交/状态查询/日志流    │  (Executor)  │ │
│  │              │                              │              │ │
│  │  - REST API  │                              │  - 任务调度   │ │
│  │  - WebSocket │                              │  - Snakemake │ │
│  │  - 结果存储   │                              │    执行      │ │
│  │  - 数据库    │                              │  - 日志转发   │ │
│  │              │                              │  - 结果回调   │ │
│  └──────────────┘                              └──────────────┘ │
│         │                                              │        │
│         │         ┌──────────────┐                    │        │
│         └────────►│  PostgreSQL  │◄───────────────────┘        │
│                   │    Redis     │    共享状态存储                │
│                   └──────────────┘                             │
│                                                                 │
│  EXECUTION_MODE=remote                                         │
└─────────────────────────────────────────────────────────────────┘
```

**Master 节点 Executor Service**：

```python
# executor-service/main.py (独立 FastAPI 应用)
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

app = FastAPI(title="OmicsHub Executor Service")


@app.post("/execute")
async def execute_task(request: ExecuteRequest):
    """
    接收任务执行请求
    """
    task_dir = prepare_task_directory(request.task_id)
    
    # 下载任务配置
    await download_task_config(request.task_id, task_dir)
    
    # 启动 Snakemake
    process = await start_snakemake(
        task_dir=task_dir,
        config=request.config,
        cores=request.cores,
    )
    
    # 返回任务 PID
    return JSONResponse({
        "task_id": request.task_id,
        "pid": process.pid,
        "status": "started",
    })


@app.websocket("/ws/log/{task_id}")
async def log_websocket(websocket: WebSocket, task_id: str):
    """
    WebSocket 日志流：将 Snakemake 日志实时转发给 Web 节点
    """
    await websocket.accept()
    
    # 订阅 Redis 日志频道
    async for message in redis.subscribe(f"task:{task_id}:log"):
        await websocket.send_json(message)


@app.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    process = running_tasks.get(task_id)
    if process:
        process.terminate()
        return {"status": "cancelled"}
    return {"status": "not_found"}


@app.post("/callback/complete")
async def task_complete_callback(request: CompleteCallback):
    """
    任务完成回调：Master 节点通知 Web 节点
    """
    # 验证回调签名
    verify_callback_signature(request)
    
    # 更新任务状态
    await update_task_status(
        task_id=request.task_id,
        status="completed",
        results=request.results,
    )
    
    # 触发通知
    await send_notification(request.task_id, "completed")
    
    return {"status": "ok"}
```

**执行模式切换**：

```python
# server/core/executor/factory.py
from server.config import settings

class ExecutorFactory:
    @staticmethod
    def get_executor():
        if settings.EXECUTION_MODE == "local":
            from .local import LocalExecutor
            return LocalExecutor()
        elif settings.EXECUTION_MODE == "remote":
            from .remote import RemoteExecutor
            return RemoteExecutor(
                master_url=settings.MASTER_URL,
                api_key=settings.MASTER_API_KEY,
            )
        else:
            raise ValueError(f"Unknown execution mode: {settings.EXECUTION_MODE}")
```

**预估工时**：5 天（Executor Service 2d + Web-Master 通信 1.5d + WS 日志流 1d + 环境切换 0.5d）

---

#### 2. 结果可视化

**差异表达表格预览**：

```vue
<!-- web/components/results/DEGTable.vue -->
<template>
  <n-data-table
    :columns="columns"
    :data="degData"
    :pagination="pagination"
    :row-key="row => row.gene_id"
    @update:filters="handleFilterChange"
  />
</template>

<script setup>
const columns = [
  { title: 'Gene ID', key: 'gene_id', sorter: 'default', filter: true },
  { title: 'Gene Name', key: 'gene_name', filter: true },
  { title: 'Base Mean', key: 'baseMean', sorter: 'default' },
  { title: 'log2FoldChange', key: 'log2FoldChange', sorter: 'default' },
  { title: 'pvalue', key: 'pvalue', sorter: 'default' },
  { 
    title: 'padj', 
    key: 'padj', 
    sorter: 'default',
    render(row) {
      return h('span', {
        style: { color: row.padj < 0.05 ? '#18a058' : '#999' }
      }, row.padj?.toExponential(2) || 'NA')
    }
  },
  {
    title: 'Significant',
    key: 'significant',
    render(row) {
      if (row.padj < 0.05 && Math.abs(row.log2FoldChange) >= 1) {
        return h(NTag, { type: 'success' }, () => 'Yes')
      }
      return h(NTag, { type: 'default' }, () => 'No')
    }
  }
]
</script>
```

**火山图（ECharts）**：

```vue
<!-- web/components/results/VolcanoPlot.vue -->
<template>
  <v-chart class="chart" :option="option" autoresize />
</template>

<script setup>
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

const props = defineProps({ degData: Array })

const option = computed(() => {
  const up = props.degData.filter(d => d.padj < 0.05 && d.log2FoldChange > 1)
  const down = props.degData.filter(d => d.padj < 0.05 && d.log2FoldChange < -1)
  const ns = props.degData.filter(d => d.padj >= 0.05 || Math.abs(d.log2FoldChange) < 1)
  
  return {
    title: { text: 'Volcano Plot', subtext: `${up.length} up / ${down.length} down` },
    xAxis: { 
      name: 'log2(FoldChange)', 
      nameLocation: 'center',
      nameGap: 30 
    },
    yAxis: { 
      name: '-log10(padj)', 
      nameLocation: 'center',
      nameGap: 40 
    },
    tooltip: {
      formatter: (params) => {
        const d = params.data
        return `${d.gene_name}<br/>log2FC: ${d.log2FoldChange.toFixed(2)}<br/>padj: ${d.padj.toExponential(2)}`
      }
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    series: [
      {
        name: 'Up-regulated',
        type: 'scatter',
        data: up.map(d => ({ ...d, value: [d.log2FoldChange, -Math.log10(d.padj)] })),
        itemStyle: { color: '#d03050' },
        symbolSize: 6,
      },
      {
        name: 'Down-regulated',
        type: 'scatter',
        data: down.map(d => ({ ...d, value: [d.log2FoldChange, -Math.log10(d.padj)] })),
        itemStyle: { color: '#18a058' },
        symbolSize: 6,
      },
      {
        name: 'Not significant',
        type: 'scatter',
        data: ns.map(d => ({ ...d, value: [d.log2FoldChange, -Math.log10(d.padj)] })),
        itemStyle: { color: '#999999', opacity: 0.5 },
        symbolSize: 3,
      }
    ],
    legend: { data: ['Up-regulated', 'Down-regulated', 'Not significant'] }
  }
})
</script>
```

**UMAP/t-SNE（scRNA-seq）**：

```vue
<!-- web/components/results/UmapPlot.vue -->
<script setup>
// 使用 ECharts 散点图 + 不同颜色表示 cluster
data: umapData.map(d => ({
  value: [d.UMAP_1, d.UMAP_2],
  cluster: d.cluster,
  cell_type: d.cell_type,
  n_genes: d.n_genes
})),
itemStyle: {
  color: (params) => clusterColors[params.data.cluster]
}
</script>
```

**预估工时**：5 天（差异表达表格 1d + 火山图 1.5d + 热图 1.5d + UMAP/t-SNE 1d）

---

#### 3. AI 工具调用增强

**工具协议定义**：

```python
# server/core/ai/tools/registry.py
class AIToolRegistry:
    """AI 可用工具注册表"""
    
    TOOLS = [
        {
            "name": "submit_task",
            "description": "提交一个分析任务到 OmicsHub",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "流程 ID"},
                    "task_name": {"type": "string"},
                    "parameters": {"type": "object", "description": "流程参数"},
                    "samples": {"type": "array", "description": "样本表数据"}
                },
                "required": ["workflow_id", "parameters", "samples"]
            }
        },
        {
            "name": "query_tasks",
            "description": "查询当前用户的任务列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "running", "completed", "failed"]},
                    "limit": {"type": "integer", "default": 10}
                }
            }
        },
        {
            "name": "get_task_results",
            "description": "获取任务的分析结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"}
                },
                "required": ["task_id"]
            }
        },
        {
            "name": "search_workflows",
            "description": "搜索可用的分析流程",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "keyword": {"type": "string"}
                }
            }
        },
        {
            "name": "query_pubmed",
            "description": "搜索 PubMed 文献",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    ]
```

**确认机制流程**：

```
用户: "帮我提交一个 RNA-seq 任务，对比 WT 和 KO 组"

AI: 
  1. 调用 search_workflows → 找到 rnaseq-v1
  2. 调用 submit_task（草稿模式，不真正提交）
  
AI → 用户:
  "我已为你准备好任务草稿，请确认：
  
  📋 任务草稿
  流程: RNA-seq 差异表达分析 (rnaseq-v1)
  样本: 4 个 (WT: 2, KO: 2)
  比对: STAR (hg38)
  参数: padj=0.05, log2FC=1.0
  
  [确认提交]  [修改参数]  [取消]"

用户: "确认提交"

AI:
  1. 真正调用 submit_task
  2. 返回任务 ID
  
AI → 用户:
  "✅ 任务已提交！任务 ID: #20250201-001
  你可以在任务列表页面查看进度。"
```

**预估工时**：5 天（工具注册 1.5d + 调用实现 1.5d + 确认机制 UI 1.5d + 测试调优 0.5d）

---

#### 4. 管理后台

```
┌──────────────────────────────────────────────────────────────┐
│  管理后台                                                     │
├──────────────┬───────────────────────────────────────────────┤
│              │                                               │
│  📊 概览     │  系统概览                                      │
│  👥 用户管理  │  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  🔧 流程管理  │  │ 用户 15 │ │ 任务 156│ │ 流程 8  │       │
│  🔌 MCP管理  │  └─────────┘ └─────────┘ └─────────┘       │
│  📈 监控     │                                               │
│  ⚙️ 设置     │  ┌─────────────────────────────────────────┐  │
│              │  │ 任务趋势 (近30天)                        │  │
│              │  │                                         │  │
│              │  │  ▲ 完成  ████████████  142              │  │
│              │  │  │ 失败  ██              8              │  │
│              │  │  │ 取消  █               6              │  │
│              │  │  └───────────────────────────────        │  │
│              │  └─────────────────────────────────────────┘  │
│              │                                               │
├──────────────┤  ┌─────────────────────────────────────────┐  │
│              │  │ 最近任务                                  │  │
│              │  │ #20250201-005 ✓ completed  2分钟前      │  │
│              │  │ #20250201-004 ✗ failed     15分钟前     │  │
│              │  │ #20250201-003 ✓ completed  1小时前      │  │
│              │  └─────────────────────────────────────────┘  │
│              │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

**Flower 集成（Celery 监控）**：

```yaml
# docker-compose.yml (追加)
  flower:
    image: mher/flower:latest
    container_name: omicshub-flower
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/1
      - FLOWER_BASIC_AUTH=${FLOWER_AUTH:-admin:admin}
    ports:
      - "5555:5555"
    depends_on:
      - redis
    networks:
      - omicshub-net
```

**预估工时**：3 天

---

#### 5. 安全与运维

**文件系统隔离**：

```python
# server/core/security/isolation.py
import os
from pathlib import Path

class TaskDirectoryIsolator:
    """任务目录隔离器"""
    
    BASE_DIR = Path("/data/tasks")
    ALLOWED_PREFIXES = ["/data/raw/", "/data/ref/", "/data/public/"]
    
    @classmethod
    def create_task_dir(cls, task_id: str) -> Path:
        """创建隔离的任务目录"""
        task_dir = cls.BASE_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建子目录
        for subdir in ["log", "results", "temp"]:
            (task_dir / subdir).mkdir(exist_ok=True)
        
        return task_dir
    
    @classmethod
    def validate_path(cls, path: str) -> bool:
        """校验文件路径是否在允许范围内"""
        resolved = Path(path).resolve()
        return any(
            str(resolved).startswith(prefix)
            for prefix in cls.ALLOWED_PREFIXES
        )
    
    @classmethod
    def cleanup_task_dir(cls, task_id: str):
        """清理任务目录"""
        import shutil
        task_dir = cls.BASE_DIR / task_id
        if task_dir.exists():
            shutil.rmtree(task_dir)
```

**回调接口安全**：

```python
# server/api/callback.py
import hmac
import hashlib
from fastapi import Header, HTTPException

async def verify_callback(
    request: Request,
    x_signature: str = Header(None),
    x_task_id: str = Header(None),
):
    """验证回调请求签名"""
    if not x_signature:
        raise HTTPException(401, "Missing signature")
    
    # IP 白名单校验
    client_ip = request.client.host
    if client_ip not in settings.MASTER_IP_WHITELIST:
        raise HTTPException(403, "IP not whitelisted")
    
    # HMAC 签名校验
    body = await request.body()
    expected = hmac.new(
        settings.CALLBACK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "Invalid signature")
```

**预估工时**：3 天（文件隔离 1d + 回调安全 0.5d + 文档 1.5d）

### Phase 3 验收标准

| 验收项 | 标准 | 测试方法 |
|--------|------|----------|
| 远程模式切换 | `EXECUTION_MODE=remote` 正常执行 | 设置环境变量 → 提交任务 → 在 Master 节点看到执行 |
| Web-Master 分离 | Web 和 Master 可以独立部署 | 分别启动两个服务 → 任务正常提交和回调 |
| 火山图渲染 | 差异基因正确分类显示 | 打开 completed 任务 → 火山图红绿点分布合理 |
| 热图渲染 | 聚类热图正确显示 | 查看热图 → 样本按分组聚类 |
| AI 提交任务 | AI 可以辅助提交任务（带确认） | 对话 "帮我提交 RNA-seq 任务" → 看到草稿 → 确认 → 成功提交 |
| 管理后台 | 用户/MCP/监控页面正常 | 登录管理员 → 各管理页面功能正常 |
| 文件隔离 | 任务只能访问自己的目录 | 尝试跨目录访问 → 被拒绝 |
| 文档完整 | 部署/使用/API 文档齐全 | 检查文档覆盖度 |

### Phase 3 技术债务

| 债务项 | 原因 | 偿还时间 |
|--------|------|----------|
| 不做分布式任务队列（只用单 Celery Worker） | 组内使用量可控 | v1.1 |
| 不做高级缓存策略 | Redis 基础缓存足够 | v1.1 |
| AI 对话历史只保留最近 30 天 | 存储限制 | v1.1 |
| 结果可视化只有基础图表 | 满足核心需求 | v1.1 |

---

## 风险与应对

### 风险矩阵

| 阶段 | 风险类别 | 风险描述 | 可能性 | 影响 | 应对策略 |
|------|----------|----------|--------|------|----------|
| P1 | 技术风险 | Snakemake 进度解析不准确 | 中 | 中 | 多模式解析（正则匹配多种输出格式）+ 兜底方案（按时间估算） |
| P1 | 技术风险 | WebSocket 连接不稳定 | 低 | 中 | 实现自动重连机制（指数退避）+ 日志 fallback 到轮询 |
| P1 | 资源风险 | 维护者时间不足（课程/实验冲突） | 高 | 高 | 功能严格按优先级排序，P0 必须完成，P1/P2 可裁剪 |
| P1 | 依赖风险 | Snakemake 与 Conda 环境兼容性 | 中 | 高 | Docker 镜像锁定版本 + 预构建 Conda 环境 |
| P1 | 依赖风险 | Naive UI 组件不满足需求 | 低 | 中 | 预留自定义组件开发时间，或引入 Element Plus 补充 |
| P2 | 技术风险 | AI 对话质量不稳定 | 中 | 中 | 设计好 fallback 机制（无法回答时引导用户查看文档） |
| P2 | 技术风险 | MCP Server 协议变更 | 低 | 中 | 抽象 MCP 层，协议变更时只改适配器 |
| P2 | 资源风险 | 高级动态表单开发复杂 | 中 | 中 | 条件渲染优先，可重复 Group 次之，折叠 Section 最后 |
| P3 | 技术风险 | 远程模式网络延迟影响体验 | 中 | 高 | WebSocket 连接池 + 日志批量推送 + 本地缓存 |
| P3 | 技术风险 | 结果可视化大数据量性能 | 中 | 中 | 后端预计算 + 前端虚拟滚动 + 数据分页 |
| P3 | 安全风险 | 文件系统隔离被绕过 | 低 | 高 | 路径校验 + chroot jail + 定期安全审计 |

### 风险应对详细方案

#### 风险 1：维护者时间不足（最重要）

**应对策略**：
1. **严格 MVP 优先**：Phase 1 的 P0 功能必须全部完成，P1 尽量完成，P2 可推迟
2. **功能可裁剪**：每个阶段定义"最小可接受范围"和"理想范围"
3. **自动化优先**：优先做自动化测试和部署，减少手动测试时间
4. **每周站会**：每周五下午 30 分钟回顾进度，调整优先级

**裁剪优先级（万不得已时）**：
```
Phase 1: 先砍 Docker 优化（用简单配置）→ 再砍进度解析（只显示日志）
Phase 2: 先砍 MCP → 再砍邮件通知 → AI 用简单实现
Phase 3: 先砍 UMAP → 再砍管理后台 → 保留远程模式+可视化
```

#### 风险 2：Snakemake 进度解析

**多模式解析方案**：

```python
def parse_progress(line: str) -> tuple[int, int] | None:
    """多模式进度解析"""
    import re
    
    patterns = [
        # Pattern 1: Snakemake 默认 "5 of 23 steps (22%) done"
        r'(\d+)\s+of\s+(\d+)\s+steps',
        # Pattern 2: "Finished job N."
        r'Finished job\s+(\d+)',
        # Pattern 3: DRMAA "Submitted job N"
        r'Submitted job\s+(\d+)',
        # Pattern 4: 规则完成计数
        r'(\d+)\s+jobs\s+finished',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            # 根据模式返回不同的进度计算方式
            ...
    
    return None  # 无法解析


class ProgressTracker:
    """进度追踪器（兜底方案）"""
    
    def __init__(self, total_steps: int):
        self.total = total_steps
        self.completed = 0
        self.start_time = time.time()
        # 预估总时间（用于时间-based 进度）
        self.estimated_duration = self._estimate_duration()
    
    def get_progress(self, log_line: str) -> int:
        """获取当前进度（0-100）"""
        # 优先用步骤解析
        if result := parse_progress(log_line):
            completed, total = result
            return int(completed / total * 100)
        
        # 兜底：按时间估算（平滑增长）
        elapsed = time.time() - self.start_time
        time_progress = min(int(elapsed / self.estimated_duration * 100), 99)
        return time_progress
```

---

## 技术债务管理

### 技术债务登记册

| 阶段 | 债务项 | 严重程度 | 产生原因 | 偿还计划 | 估算偿还工时 |
|------|--------|----------|----------|----------|-------------|
| P1 | 简单两角色权限（admin/user） | 低 | 快速实现 | P3 管理后台重构 | 2d |
| P1 | 样本表只传路径不上传文件 | 中 | 避免文件存储复杂度 | P3 项目-样本管理 | 3d |
| P1 | YAML 流程硬编码 | 高 | 快速实现单流程 | P2 流程配置中心 | 已偿还 |
| P1 | WebSocket 无断线重连 | 中 | 局域网稳定假设 | P2 增强 | 1d |
| P1 | 无任务取消功能 | 高 | Celery revoke 复杂度 | P2 增强 | 已偿还 |
| P1 | 日志无归档策略 | 低 | 本地存储 | P3 运维完善 | 1d |
| P2 | AI 对话不做持久化 | 中 | 优先可用性 | P3 AI 增强 | 2d |
| P2 | MCP 只有 PubMed | 低 | 验证架构 | P3 扩展更多 Server | 3d |
| P2 | 邮件同步发送 | 低 | Celery 足够 | P3 无需改 | - |
| P3 | 单 Celery Worker | 中 | 组内量可控 | v1.1 分布式队列 | 5d |
| P3 | 无高级缓存策略 | 低 | Redis 基础够用 | v1.1 缓存优化 | 3d |
| P3 | AI 历史 30 天限制 | 低 | 存储考虑 | v1.1 持久化方案 | 2d |

### 债务偿还策略

1. **每个阶段预留 10% 时间偿还上一阶段债务**
   - Phase 2 第一周：偿还 Phase 1 债务（约 1-2 天）
   - Phase 3 第一周：偿还 Phase 2 债务（约 1-2 天）

2. **债务可视化**
   - 在每个阶段开始时，列出未偿还债务
   - 在代码中用 `TODO(tech-debt)` 标记债务点

3. **债务上限**
   - 任一时刻未偿还债务不超过 5 项
   - 单一项债务工时不超过 3 天
   - 总债务工时不超过 10 天

---

## 总结

### 三个阶段的演进路线

```
Phase 1 (MVP)                    Phase 2 (v0.8)                  Phase 3 (v1.0)
  [RNA-seq]                       [多流程平台]                     [生产就绪]
     │                                │                               │
     ▼                                ▼                               ▼
┌──────────┐                    ┌──────────┐                    ┌──────────┐
│ 单流程    │ ──► YAML 配置中心 ──►│ 多流程    │ ──► 远程模式 ────►│ 分布式    │
│ 本地执行  │ ──► AI 对话 ────────►│ 智能助手  │ ──► 可视化 ──────►│ 结果展示  │
│ 基础表单  │ ──► 高级表单 ───────►│ 复杂交互  │ ──► AI 工具调用 ──►│ 自动化    │
│ 命令替代  │ ──► MCP 扩展 ───────►│ 开放生态  │ ──► 安全加固 ────►│ 企业级    │
└──────────┘                    └──────────┘                    └──────────┘
   ~5 周                           ~3-4 周                        ~3-4 周
```

### 关键成功因素

1. **MVP 必须可用**：Phase 1 完成后，组内成员 100% 可以通过 Web 提交 RNA-seq 任务
2. **快速迭代**：每完成一个功能点即演示，及时调整方向
3. **技术债务可控**：每个阶段预留时间偿还债务，避免积重难返
4. **文档先行**：每个阶段结束后更新文档，降低维护成本

### 最终交付物

| 交付物 | 路径 | 说明 |
|--------|------|------|
| 平台源码 | `/mnt/agents/output/` | 完整前后端代码 |
| 部署文档 | `docs/deployment.md` | Docker Compose 部署指南 |
| 使用手册 | `docs/user-guide.md` | 面向组内用户 |
| API 文档 | `/api/docs` (Swagger) | 自动生成 |
| 开发文档 | `docs/development.md` | 面向后续维护者 |
