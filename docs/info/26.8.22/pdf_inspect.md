# PDF Inspector 集成调查文档

> **文档版本**: v1.0  
> **调查目标**: 评估将 pdf-inspector 作为 PDF 处理主路径的可行性，现有流程作为降级备选  
> **适用场景**: 已有 PDF 处理 pipeline 的平台/系统

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [现状分析框架](#2-现状分析框架)
3. [目标架构设计](#3-目标架构设计)
4. [详细代码审查清单](#4-详细代码审查清单)
5. [集成方案对比](#5-集成方案对比)
6. [风险评估与缓解](#6-风险评估与缓解)
7. [迁移路线图](#7-迁移路线图)
8. [附录：Agent 代码审查提示词](#8-附录agent-代码审查提示词)

---

## 1. 执行摘要

### 1.1 核心结论

| 维度 | 评估结论 |
|------|---------|
| **技术可行性** | 高 — pdf-inspector 提供 Python 绑定 + 现成 MCP 包装器，集成成本低 |
| **性能提升** | 显著 — 纯文本 PDF 解析从秒级降至 ~200ms，结构化输出质量大幅提升 |
| **兼容性风险** | 中 — 需验证现有下游消费方对 Markdown 格式的兼容性 |
| **迁移成本** | 中低 — 建议渐进式迁移，保留现有流程作为降级路径 |

### 1.2 推荐策略

**主路径**: pdf-inspector → 结构化 Markdown  
**降级路径**: 现有 PDF 处理流程（保留 3-6 个月，逐步淘汰）  
**触发降级条件**: pdf-inspector 解析失败 / 输出置信度低于阈值 / 特殊格式 PDF

---

## 2. 现状分析框架

### 2.1 需要收集的信息清单

在正式审查代码前，请确认以下信息：

#### A. 系统边界
- [ ] 平台当前支持哪些文件格式？（仅 PDF？还是 PDF + Word + Excel？）
- [ ] PDF 处理是同步还是异步？（用户上传后立即解析 vs 后台队列处理）
- [ ] 单文件大小限制？（10MB？100MB？无限制？）
- [ ] 并发处理量？（QPS 峰值多少？）

#### B. 现有 Pipeline 结构
- [ ] 现有 PDF 解析依赖什么库？（PyPDF2 / pdfplumber / pymupdf / 自研？）
- [ ] 是否包含 OCR 能力？（Tesseract / PaddleOCR / 云 API？）
- [ ] 输出格式是什么？（纯文本 / HTML / JSON / 自定义结构？）
- [ ] 是否保留原始布局信息？（坐标、字体、颜色？）

#### C. 下游消费方
- [ ] 解析结果给谁用？（RAG 检索 / LLM 上下文 / 结构化存储 / 全文搜索？）
- [ ] 下游是否依赖特定的输出 schema？
- [ ] 是否有分页、分块、摘要等后处理？

#### D. 部署环境
- [ ] 运行环境？（Docker / K8s / 裸机 / Serverless？）
- [ ] 是否支持 Rust 编译？（pdf-inspector 核心为 Rust，需编译环境）
- [ ] 网络限制？（能否安装 PyPI 包？能否访问外部 OCR API？）

### 2.2 现状评估矩阵

| 评估项 | 现有方案 | pdf-inspector | 差距分析 |
|--------|---------|---------------|---------|
| 解析速度 | ___ ms/页 | ~20ms 分类 + ~200ms 提取 | 待测 |
| 文本顺序准确性 | ___ | 内置阅读顺序校正 | 待验证 |
| 表格保留能力 | ___ | 矩形检测 + 启发式对齐 | 待验证 |
| 多栏排版支持 | ___ | 原生支持 | 待验证 |
| 编码问题处理 | ___ | 自动检测编码问题 | 待验证 |
| OCR 触发策略 | ___ | 智能按需 OCR | 待评估 |
| 输出结构化程度 | ___ | Markdown + 元数据 | 需适配 |

---

## 3. 目标架构设计

### 3.1 核心流程图

```
用户上传 PDF
    ↓
┌─────────────────────────────┐
│     PDF 路由层 (Router)      │
│  ┌───────────────────────┐  │
│  │ 1. 文件大小检查       │  │
│  │ 2. 格式合法性校验     │  │
│  │ 3. 密码保护检测       │  │
│  └───────────────────────┘  │
└────────┬────────────────────┘
         ↓
┌─────────────────────────────┐     失败/异常
│   主路径：pdf-inspector      │────────────────┐
│  ┌───────────────────────┐  │                 │
│  │ ① detect_pdf()        │  │                 │
│  │   → 获取 pdfType      │  │                 │
│  │   → 获取置信度        │  │                 │
│  │   → 获取编码状态      │  │                 │
│  │                       │  │                 │
│  │ ② process_pdf()       │  │                 │
│  │   → 结构化 Markdown   │  │                 │
│  │   → 页面级元数据      │  │                 │
│  │   → OCR 需求标记      │  │                 │
│  └───────────────────────┘  │                 │
└────────┬────────────────────┘                 │
         │ 成功                                 │
         ↓                                      │
┌─────────────────────────────┐                 │
│   质量门控 (Quality Gate)    │                 │
│  ┌───────────────────────┐  │                 │
│  │ • 输出非空检查        │  │                 │
│  │ • 置信度 ≥ 阈值       │  │                 │
│  │ • 编码问题标记检查    │  │                 │
│  │ • 异常页码比例检查    │  │                 │
│  └───────────────────────┘  │                 │
└────────┬────────────────────┘                 │
    通过 │      未通过 ──────────────────────────┘
         ↓                                      │
┌─────────────────────────────┐                 │
│   输出标准化层 (Normalizer)  │                 │
│  ┌───────────────────────┐  │                 │
│  │ • Markdown → 目标格式 │  │                 │
│  │ • 分块策略适配        │  │                 │
│  │ • 元数据注入          │  │                 │
│  └───────────────────────┘  │                 │
└────────┬────────────────────┘                 │
         ↓                                      │
┌─────────────────────────────┐◄────────────────┘
│   降级路径：现有处理流程      │
│  ┌───────────────────────┐  │
│  │ ① 现有解析器处理      │  │
│  │ ② 输出转换为目标格式  │  │
│  │ ③ 标记为降级处理      │  │
│  └───────────────────────┘  │
└────────┬────────────────────┘
         ↓
┌─────────────────────────────┐
│      下游消费方              │
│  (RAG / LLM / 存储 / 搜索)  │
└─────────────────────────────┘
```

### 3.2 降级触发条件（明确规则）

| 触发条件 | 说明 | 日志标记 |
|---------|------|---------|
| `pdf-inspector` 解析异常 | Rust 核心 panic / Python 绑定异常 | `ERROR: inspector_crash` |
| 输出为空 | Markdown 内容长度 = 0 | `WARN: empty_output` |
| 置信度低于阈值 | 分类置信度 < 0.7 | `WARN: low_confidence` |
| 编码问题标记 | `hasEncodingIssues = true` | `WARN: encoding_issues` |
| 高比例页面需 OCR | > 50% 页面需要 OCR 且未启用 OCR | `WARN: high_ocr_ratio` |
| 文件大小超限 | > 100MB（pdf-inspector 未充分测试） | `WARN: size_limit` |
| 密码保护 | 加密 PDF | `ERROR: encrypted_pdf` |
| 已知格式问题 | 特定版本 PDF 生成器已知兼容问题 | `WARN: known_format_issue` |

### 3.3 输出标准化层设计

pdf-inspector 输出的是 Markdown，但你的下游可能期望其他格式。标准化层需要处理：

```python
class PDFOutputNormalizer:
    """将 pdf-inspector 的输出转换为平台统一格式"""
    
    def normalize(self, inspector_result: dict) -> PlatformPDFDocument:
        return PlatformPDFDocument(
            # 基础信息
            source="pdf-inspector",
            version=inspector_result.get("version"),
            
            # 内容（多种格式并存，下游按需取用）
            content_markdown=inspector_result["markdown"],
            content_plaintext=self._markdown_to_text(inspector_result["markdown"]),
            
            # 结构化数据
            pages=[
                Page(
                    number=page["page_number"],
                    markdown=page["markdown"],
                    text=page.get("text", ""),
                    needs_ocr=page.get("needs_ocr", False),
                    confidence=page.get("confidence", 1.0),
                )
                for page in inspector_result.get("pages", [])
            ],
            
            # 元数据
            metadata=PDFMetadata(
                pdf_type=inspector_result["pdf_type"],
                total_pages=inspector_result["total_pages"],
                has_encoding_issues=inspector_result.get("has_encoding_issues", False),
                pages_needing_ocr=inspector_result.get("pages_needing_ocr", []),
            ),
            
            # 处理追踪
            processing_info=ProcessingInfo(
                primary_path="pdf-inspector",
                fallback_triggered=False,
                processing_time_ms=inspector_result.get("processing_time_ms"),
            )
        )
```

---

## 4. 详细代码审查清单

### 4.1 现有 PDF 处理模块审查

#### 4.1.1 入口层审查

| # | 检查项 | 审查方法 | 风险等级 |
|---|--------|---------|---------|
| 1 | PDF 文件是如何进入系统的？（HTTP API / 消息队列 / 文件系统监听？） | 查看路由/控制器代码 | - |
| 2 | 文件上传后是否先落盘？还是直接内存处理？ | 检查文件处理逻辑 | 高（影响大文件处理） |
| 3 | 是否有文件类型校验？（仅检查扩展名还是魔数检测？） | 查看校验逻辑 | 中 |
| 4 | 上传文件是否有大小限制？在哪里限制？ | 查看配置和中间件 | - |
| 5 | 是否支持批量上传？批量时如何调度？ | 查看队列/线程池配置 | 中 |

#### 4.1.2 解析层审查

| # | 检查项 | 审查方法 | 风险等级 |
|---|--------|---------|---------|
| 6 | 使用的 PDF 解析库及版本？ | 查看 requirements.txt / package.json | - |
| 7 | 解析是同步还是异步？ | 查看解析函数签名 | 高（影响集成方式） |
| 8 | 解析结果是否缓存？缓存策略？ | 查看缓存层代码 | - |
| 9 | 是否处理了解析异常？异常时如何反馈？ | 查看 try/except 块 | 高 |
| 10 | 是否支持重试机制？ | 查看重试逻辑 | - |
| 11 | 解析是否依赖外部服务？（云 OCR / 第三方 API？） | 查看网络调用 | 高（影响成本） |

#### 4.1.3 输出层审查

| # | 检查项 | 审查方法 | 风险等级 |
|---|--------|---------|---------|
| 12 | 解析输出的 schema 是什么？ | 查看输出模型/DTO | - |
| 13 | 输出是否包含位置信息？（坐标、页码、段落） | 查看输出结构 | 中 |
| 14 | 输出是否包含格式信息？（字体、大小、颜色） | 查看输出结构 | 低 |
| 15 | 表格是如何表示的？（纯文本 / HTML / JSON？） | 查看表格处理代码 | 高 |
| 16 | 图片是如何处理的？（提取 / 忽略 / 转描述？） | 查看图片处理代码 | 中 |
| 17 | 输出是否经过清洗/后处理？ | 查看后处理管道 | - |

#### 4.1.4 下游消费审查

| # | 检查项 | 审查方法 | 风险等级 |
|---|--------|---------|---------|
| 18 | 解析结果存储在哪里？（数据库 / 对象存储 / 搜索引擎？） | 查看存储层 | - |
| 19 | 下游消费方有哪些？（列表全部） | 查看调用链 / 事件订阅 | - |
| 20 | 下游是否对输出格式有强依赖？ | 查看下游解析代码 | 高 |
| 21 | 是否有分块(chunking)逻辑？基于什么策略？ | 查看分块代码 | 高 |
| 22 | 是否有向量化/embedding 步骤？ | 查看 RAG 管道 | - |
| 23 | 全文搜索是如何实现的？ | 查看搜索索引代码 | 中 |

### 4.2 部署与运维审查

| # | 检查项 | 审查方法 |
|---|--------|---------|
| 24 | 当前部署方式？（Docker / K8s / 裸机） | 查看 Dockerfile / k8s yaml |
| 25 | CI/CD 流程？构建时间？ | 查看 CI 配置 |
| 26 | 是否有限制网络访问的安全策略？ | 查看安全组 / 防火墙规则 |
| 27 | 当前资源占用？（CPU / 内存 / 磁盘） | 查看监控面板 |
| 28 | 是否有 PDF 处理的专项监控？（成功率 / 耗时 / 错误率） | 查看监控配置 |
| 29 | 是否有 PDF 样本测试集？ | 查看测试目录 |

---

## 5. 集成方案对比

### 5.1 三种集成模式

| 模式 | 描述 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|---------|
| **A. 代理模式** | pdf-inspector 包装为 MCP Server，Agent 直接调用 | 解耦、Agent 原生支持 | 增加网络层、延迟稍高 | Agent 驱动的平台 |
| **B. 库模式** | 直接在代码中 import pdf-inspector Python 绑定 | 最低延迟、完全控制 | 耦合度高 | 高性能要求的平台 |
| **C. 服务模式** | 独立部署 pdf-inspector 微服务，内部 gRPC/HTTP 调用 | 独立扩缩容、团队自治 | 运维复杂度增加 | 大型平台、多团队 |

### 5.2 推荐：库模式 + 降级包装

对于已有 PDF 处理 pipeline 的平台，**推荐库模式**：

```python
# pdf_processor.py —— 统一入口，内部实现主/降级路径

from typing import Optional
from dataclasses import dataclass
import pdf_inspector  # pdf-inspector Python 绑定

@dataclass
class PDFProcessResult:
    success: bool
    content: str
    metadata: dict
    source: str  # "pdf-inspector" | "legacy"
    fallback_reason: Optional[str] = None

class PDFProcessor:
    """统一 PDF 处理器：主路径 pdf-inspector，降级路径现有解析器"""
    
    def __init__(
        self,
        legacy_processor,  # 现有解析器实例
        confidence_threshold: float = 0.7,
        max_file_size_mb: float = 100.0,
        enable_ocr: bool = False,
    ):
        self.legacy = legacy_processor
        self.confidence_threshold = confidence_threshold
        self.max_file_size_mb = max_file_size_mb
        self.enable_ocr = enable_ocr
        
        # 指标收集
        self.stats = {
            "inspector_success": 0,
            "inspector_fail": 0,
            "fallback_triggered": 0,
            "avg_processing_time_ms": 0,
        }
    
    async def process(self, file_path: str) -> PDFProcessResult:
        """处理 PDF 文件，自动选择主路径或降级路径"""
        
        # 前置检查
        if not self._pre_check(file_path):
            return await self._fallback(file_path, "pre_check_failed")
        
        # 主路径：pdf-inspector
        try:
            result = await self._process_with_inspector(file_path)
            
            # 质量门控
            if self._pass_quality_gate(result):
                self.stats["inspector_success"] += 1
                return PDFProcessResult(
                    success=True,
                    content=result["markdown"],
                    metadata=result,
                    source="pdf-inspector",
                )
            else:
                self.stats["inspector_fail"] += 1
                return await self._fallback(file_path, "quality_gate_failed")
                
        except Exception as e:
            self.stats["inspector_fail"] += 1
            return await self._fallback(file_path, f"inspector_exception: {e}")
    
    async def _process_with_inspector(self, file_path: str) -> dict:
        """使用 pdf-inspector 处理"""
        # ① 快速分类
        detection = pdf_inspector.detect_pdf(file_path)
        
        # ② 完整提取
        result = pdf_inspector.process_pdf(
            file_path,
            options={
                "extract_markdown": True,
                "extract_metadata": True,
                "enable_ocr": self.enable_ocr,
            }
        )
        
        return {
            "pdf_type": detection.pdf_type,
            "confidence": detection.confidence,
            "has_encoding_issues": detection.has_encoding_issues,
            "pages_needing_ocr": result.pages_needing_ocr,
            "markdown": result.markdown,
            "pages": result.pages,
            "total_pages": result.total_pages,
        }
    
    def _pass_quality_gate(self, result: dict) -> bool:
        """质量门控检查"""
        if not result["markdown"] or len(result["markdown"].strip()) == 0:
            return False
        if result["confidence"] < self.confidence_threshold:
            return False
        if result.get("has_encoding_issues", False):
            return False
        # 可扩展更多规则
        return True
    
    async def _fallback(self, file_path: str, reason: str) -> PDFProcessResult:
        """降级到现有处理流程"""
        self.stats["fallback_triggered"] += 1
        legacy_result = await self.legacy.process(file_path)
        return PDFProcessResult(
            success=legacy_result.success,
            content=legacy_result.content,
            metadata=legacy_result.metadata,
            source="legacy",
            fallback_reason=reason,
        )
    
    def _pre_check(self, file_path: str) -> bool:
        """前置检查"""
        import os
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > self.max_file_size_mb:
            return False
        return True
```

---

## 6. 风险评估与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| pdf-inspector 解析特定 PDF 失败 | 中 | 高 | 降级路径自动接管 + 告警 |
| 输出 Markdown 与下游格式不兼容 | 高 | 中 | 标准化层统一转换 + 渐进迁移 |
| Rust 编译环境部署问题 | 低 | 中 | 提供预编译 wheel / Docker 镜像 |
| OCR 功能未启用导致扫描件解析差 | 中 | 中 | 配置按需 OCR，扫描件自动触发 |
| 性能未达预期 | 低 | 中 | A/B 测试对比，保留调参空间 |
| 团队成员学习成本 | 中 | 低 | 文档 + 培训 + 渐进 rollout |

---

## 7. 迁移路线图

### Phase 1: 调研与验证（1-2 周）

- [ ] 收集 100+ 代表性 PDF 样本（覆盖所有业务场景）
- [ ] 搭建 pdf-inspector 测试环境
- [ ] 运行样本对比测试（现有方案 vs pdf-inspector）
- [ ] 输出对比报告，确认质量提升幅度

### Phase 2: 适配层开发（1-2 周）

- [ ] 实现 `PDFProcessor` 统一入口类
- [ ] 实现输出标准化层（Markdown → 现有格式）
- [ ] 实现质量门控逻辑
- [ ] 集成降级路径
- [ ] 补充单元测试和集成测试

### Phase 3: 灰度发布（2-4 周）

- [ ] 5% 流量切到 pdf-inspector 主路径
- [ ] 监控成功率、耗时、降级率
- [ ] 逐步扩大至 50% → 100%
- [ ] 收集异常样本，持续优化门控规则

### Phase 4: 清理与优化（1-2 周）

- [ ] 确认 pdf-inspector 稳定运行 2 周无异常
- [ ] 移除降级路径（或保留为极端情况备用）
- [ ] 清理旧依赖
- [ ] 更新文档和运维手册

---

## 8. 附录：Agent 代码审查提示词

### 8.1 通用代码审查提示词（复制粘贴使用）

```markdown
# 角色设定
你是一位资深平台架构师和代码审查专家，专注于文档处理系统和 PDF 解析 pipeline 的架构设计。

# 任务目标
请对以下平台的 PDF 处理相关代码进行全面审查，目标是评估将 "pdf-inspector"（https://github.com/firecrawl/pdf-inspector）作为 PDF 处理主路径、现有流程作为降级备选的可行性。

# 审查范围
请重点关注以下模块和文件：
1. PDF 文件上传/接收入口
2. PDF 解析核心逻辑
3. 解析输出格式定义
4. 下游消费方调用链
5. 异常处理和重试机制
6. 部署和配置相关代码

# 审查维度

## 维度一：架构耦合度
- 现有 PDF 解析逻辑是否被高度耦合到业务代码中？
- 是否存在统一的 PDF 处理抽象层/接口？
- 替换解析引擎需要改动多少文件？
- 是否使用了依赖注入或策略模式？

## 维度二：输出格式兼容性
- 现有解析器输出什么格式？（纯文本/HTML/JSON/自定义对象）
- 下游消费方对输出格式的依赖程度？
- 是否需要额外的适配层来转换 pdf-inspector 的 Markdown 输出？
- 表格、图片、超链接等特殊元素是如何表示的？

## 维度三：性能特征
- 当前解析的平均耗时？（单页/整份文档）
- 是否有性能瓶颈？（大文件、扫描件、复杂排版）
- 当前是同步处理还是异步队列？
- pdf-inspector 的 ~200ms 解析速度是否满足需求？

## 维度四：异常处理
- 当前解析失败率是多少？主要失败原因？
- 异常时是否有降级机制？
- 是否有死信队列或人工介入流程？
- pdf-inspector 的降级触发条件应如何设计？

## 维度五：部署与运维
- 当前运行环境是否支持 Rust 编译？
- 是否使用 Docker？镜像大小是否敏感？
- 是否有 PDF 处理的专项监控和告警？
- 引入 pdf-inspector 后需要新增哪些监控指标？

## 维度六：安全与合规
- PDF 处理是否涉及敏感数据？
- 当前解析是否在内存中完成？是否有数据落盘？
- 引入新依赖的安全审计状态？

# 输出要求

请按以下结构输出审查报告：

## 1. 代码结构总览
- 用 Mermaid 图或文字描述 PDF 处理 pipeline 的完整流程
- 列出所有相关文件和它们的职责

## 2. 关键发现（按优先级排序）
对每个发现，请包含：
- 发现描述
- 所在文件和代码位置
- 风险等级（P0-阻塞 / P1-高 / P2-中 / P3-低）
- 具体建议

## 3. 集成可行性评估
- 总体可行性结论（可行/需改造/不建议）
- 需要改造的关键点
- 预估改造工作量（人天）

## 4. 具体集成方案建议
- 推荐的集成模式（库模式/服务模式/MCP模式）
- 推荐的降级策略
- 推荐的灰度发布方案

## 5. 代码改进建议
- 为支持 pdf-inspector 集成，建议对现有代码做的重构
- 提供具体的代码示例或伪代码

# 输入代码
[请在此处粘贴需要审查的代码，或上传代码文件]
```

### 8.2 快速扫描提示词（针对大代码库）

```markdown
# 角色设定
你是一位代码架构分析师，擅长快速理解大型代码库的结构。

# 任务
请快速扫描以下代码库，找出所有与 PDF 处理相关的文件、类和函数。

# 输出要求
1. 文件清单：列出所有 PDF 相关文件，标注其职责
2. 依赖关系图：用文本或 Mermaid 描述 PDF 处理链的调用关系
3. 关键接口：列出 PDF 解析的入口函数/方法签名
4. 外部依赖：列出所有 PDF 相关的第三方库
5. 配置项：列出所有 PDF 处理相关的配置参数

# 输入
[请在此处粘贴代码库结构或上传代码]
```

### 8.3 对比测试提示词

```markdown
# 角色设定
你是一位 QA 工程师，负责 PDF 解析质量的对比测试。

# 任务
请对以下同一份 PDF 的两份解析结果进行对比分析：
- 结果 A：现有解析器输出
- 结果 B：pdf-inspector 输出

# 评估维度
1. 文本完整性：是否有内容丢失？
2. 阅读顺序：段落顺序是否正确？
3. 表格质量：表格结构是否保留？数据是否准确？
4. 格式保留：标题层级、列表、代码块等是否识别正确？
5. 特殊元素：超链接、脚注、页眉页脚的处理

# 输出
请逐项评分（1-5分），给出总体结论和改进建议。

# 输入
[粘贴两份解析结果]
```
