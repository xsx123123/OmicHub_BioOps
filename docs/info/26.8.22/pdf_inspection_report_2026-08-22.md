# PDF 处理现状排查报告

> **调查依据**: `docs/info/26.8.22/pdf_inspect.md`  
> **排查日期**: 2026-08-22  
> **排查范围**: `src/cygnusx` 中所有 PDF 处理相关代码  
> **当前解析库**: `pypdf>=5.0.0`

---

## 1. 执行摘要

### 1.1 核心结论

| 维度 | 评估结论 |
|------|---------|
| **技术可行性** | 高 — 引入 pdf-inspector 可行，但需先统一现有三处 PDF 实现 |
| **兼容性风险** | 中 — 下游目前只消费纯文本，Markdown 输出可直接兼容 |
| **迁移成本** | 中低 — 主要是建立 `PDFProcessor` 统一入口和输出标准化层 |
| **当前最大问题** | 三处独立实现、无降级路径、无 OCR、无统一 schema |

### 1.2 推荐策略

- **短期**：统一三处 PDF 提取逻辑为 `PDFProcessor`，保留 `pypdf` 作为唯一解析引擎。
- **中期**：引入 `pdf-inspector` 作为主路径，`pypdf` 作为降级路径。
- **长期**：评估 OCR 按需触发、扫描件自动识别后，逐步淘汰 `pypdf`。

---

## 2. 当前 PDF 处理现状

### 2.1 实现位置清单

代码中共有 **3 处独立的 PDF 文本提取实现**，全部基于 `pypdf`：

| # | 文件路径 | 行号 | 用途 | 输出格式 | 字符限制 |
|---|---------|------|------|---------|---------|
| 1 | `src/cygnusx/application/services/chat_service.py` | 9369 | 聊天附件 PDF 文本读取 | `[第 N 页]\n文本` | 50,000 |
| 2 | `src/cygnusx/application/services/knowledge_asset_service.py` | 152 | 知识库 Markdown 引用 PDF 索引 | `[第 N 页]\n文本` | 40,000/资产 |
| 3 | `src/cygnusx/infrastructure/mcp/presets.py` | 553 | 工作区 `workspace_read_file` PDF 读取 | JSON `{content, truncated, pages_read}` | 50,000 |

### 2.2 共同特征

- 全部使用 `from pypdf import PdfReader`。
- 全部使用 `page.extract_text()` 逐页提取。
- 全部只做纯文本输出，不保留布局、表格、坐标、字体信息。
- 全部按总字符数硬截断，可能在页面中间断开。

### 2.3 依赖声明

```toml
# pyproject.toml:75
"pypdf>=5.0.0",
```

未使用 `pdfplumber`、`pymupdf`、`pdf-inspector` 等库，PDF OCR 也未启用。

---

## 3. 按 `pdf_inspect.md` 清单逐项排查

### 3.1 系统边界（文档 §2.1-A）

| 检查项 | 现状 |
|--------|------|
| 支持格式 | PDF + DOCX + PPTX + 图片，PDF 处理硬编码在三处 |
| 同步/异步 | PDF 解析本身是同步阻塞；chat_service 用 `anyio.to_thread.run_sync` 包装，其余两处直接同步执行 |
| 文件大小限制 | PDF 层无大小检查，仅按字符数截断 |
| 并发处理 | 无专用线程池/队列 |

### 3.2 现有 Pipeline 结构（文档 §2.1-B）

| 检查项 | 现状 |
|--------|------|
| 解析库 | `pypdf` |
| OCR 能力 | 仅 `KnowledgeAssetService._ocr()` 对图片调用 `tesseract`；PDF 扫描件无 OCR |
| 输出格式 | 纯文本 + 分页标记 |
| 布局信息 | 不保留 |

### 3.3 下游消费方（文档 §2.1-C）

| 检查项 | 现状 |
|--------|------|
| 消费者 | LLM 上下文（聊天附件、工作区读取）、知识库 RAG |
| Schema 依赖 | 三处输出格式不一致，无统一 schema |
| 分块/向量化 | 不在 PDF 解析层，应在知识库消费侧 |

### 3.4 部署环境（文档 §2.1-D）

| 检查项 | 现状 |
|--------|------|
| 运行环境 | Python 服务，Docker/K8s（见 `deploy/`） |
| Rust 编译 | 当前不需要；引入 pdf-inspector 需评估 |
| 网络限制 | 当前无外网 OCR/API 依赖 |

---

## 4. 关键风险与问题

### P1 — 三处独立实现，无统一入口

三处代码重复了几乎相同的 `pypdf` 提取循环，输出格式和限制还不一致。这直接违反了 `pdf_inspect.md` 推荐的 `PDFProcessor` 统一入口设计。

**位置**：
- `src/cygnusx/application/services/chat_service.py:9369`
- `src/cygnusx/application/services/knowledge_asset_service.py:152`
- `src/cygnusx/infrastructure/mcp/presets.py:553`

**建议**：按文档 §5.2 实现统一的 `PDFProcessor` 类。

### P1 — 扫描版/加密 PDF 无降级处理

当 `extract_text()` 返回空时，仅返回用户提示信息。缺少：
- 置信度/质量门控
- OCR 降级路径
- `fallback_triggered` 标记
- 结构化日志标记（如 `WARN: empty_output`）

**位置**：`src/cygnusx/infrastructure/mcp/presets.py:580`

**建议**：按文档 §3.2 实现明确的降级触发条件。

### P2 — 测试环境缺少 `pytest-asyncio`

`tests/unit/test_chat_attachment_reading.py:9` 使用 `@pytest.mark.asyncio`，但当前 Python 环境未安装 `pytest-asyncio`，导致测试失败。

```text
async def functions are not natively supported.
You need to install a suitable plugin for your async framework
```

`pyproject.toml:88` 已声明 `pytest-asyncio>=0.23.5`，`pyproject.toml:158` 已配置 `asyncio_mode = "auto"`，但当前 interpreter 未安装。

**建议**：在活跃虚拟环境中安装 dev 依赖，或检查 CI 是否安装了 dev group。

### P2 — 聊天附件路径解析可进一步加强

`ChatService._resolve_attachment_path` 使用 `Path(filename).name` 并检查 `path.is_file()`，但不像 `_resolve_workspace_file` 那样用 `relative_to` 校验解析后的路径确实落在用户上传目录内。

**位置**：`src/cygnusx/application/services/chat_service.py:9265`

**建议**：增加 `resolved.relative_to(upload_dir.resolve())` 校验，与 workspace 文件解析保持一致。

### P3 — 输出分页标记不一致

- 聊天/知识库：`[第 N 页]`
- 工作区：`[Page N]`

**建议**：通过 `PDFOutputNormalizer` 统一输出 schema。

---

## 5. 验证记录

### 5.1 测试运行结果

```bash
python -m pytest tests/unit/test_chat_attachment_reading.py \
                 tests/unit/test_knowledge_asset_service.py \
                 tests/unit/test_general_assistant_regression.py -q
```

结果：
- `test_chat_attachment_reading.py::test_read_attachment_text_extracts_local_pdf` **失败**（缺少 pytest-asyncio）
- 其余 10 个测试 **通过**

### 5.2 三处实现确认

通过脚本确认三处文件均使用 `from pypdf import PdfReader` 和 `extract_text()`。

---

## 6. 集成 pdf-inspector 可行性评估

| 评估项 | 现有方案 | pdf-inspector | 差距分析 |
|--------|---------|---------------|---------|
| 解析速度 | 未实测 | ~200ms | 待 A/B 测试 |
| 文本顺序准确性 | 依赖 pypdf | 内置阅读顺序校正 | 待验证 |
| 表格保留能力 | 无 | 矩形检测 + 启发式对齐 | 待验证 |
| 多栏排版支持 | 弱 | 原生支持 | 待验证 |
| 编码问题处理 | 无 | 自动检测 | 待验证 |
| OCR 触发策略 | 无 | 智能按需 OCR | 待评估 |
| 输出结构化程度 | 纯文本 | Markdown + 元数据 | 需适配层 |

**总体结论**：可行，但建议先完成统一抽象层，再引入 pdf-inspector 作为主路径。

---

## 7. 迁移路线图建议

### Phase 1: 统一重构（1 周）

- [ ] 新建 `src/cygnusx/application/services/pdf_processor.py`
- [ ] 实现 `PDFProcessor` 统一入口（参考 `pdf_inspect.md` §5.2）
- [ ] 实现 `PDFOutputNormalizer`（参考 `pdf_inspect.md` §3.3）
- [ ] 迁移 chat_service、knowledge_asset_service、presets 三处调用
- [ ] 修复 `pytest-asyncio` 环境问题
- [ ] 补充统一后的单元测试

### Phase 2: 引入 pdf-inspector（1-2 周）

- [ ] 在 `PDFProcessor` 中实现主路径（pdf-inspector）和降级路径（pypdf）
- [ ] 实现质量门控和降级触发条件（`pdf_inspect.md` §3.2）
- [ ] 配置按需 OCR（可先复用现有 tesseract）

### Phase 3: 灰度与监控（2-4 周）

- [ ] 按流量比例切换主路径
- [ ] 补充监控指标：耗时、成功率、降级率、OCR 比例
- [ ] 收集异常样本，优化门控规则

### Phase 4: 清理（1-2 周）

- [ ] 确认 pdf-inspector 稳定运行
- [ ] 移除或保留 pypdf 作为极端情况备用
- [ ] 更新文档和运维手册

---

## 8. 附录：相关文件与代码位置

### 8.1 PDF 处理代码

- `src/cygnusx/application/services/chat_service.py:9265` — `_resolve_attachment_path`
- `src/cygnusx/application/services/chat_service.py:9284` — `_is_internal_url`
- `src/cygnusx/application/services/chat_service.py:9336` — `_read_attachment_text`
- `src/cygnusx/application/services/chat_service.py:9369` — `_extract_pdf_text`
- `src/cygnusx/application/services/knowledge_asset_service.py:152` — `_extract_pdf`
- `src/cygnusx/infrastructure/mcp/presets.py:553` — `_extract_workspace_pdf_text`
- `src/cygnusx/infrastructure/mcp/presets.py:597` — `_resolve_workspace_file`

### 8.2 测试文件

- `tests/unit/test_chat_attachment_reading.py`
- `tests/unit/test_knowledge_asset_service.py`
- `tests/unit/test_general_assistant_regression.py`

### 8.3 配置与依赖

- `pyproject.toml:75` — `pypdf>=5.0.0`
- `pyproject.toml:88` — `pytest-asyncio>=0.23.5`
- `pyproject.toml:158` — `asyncio_mode = "auto"`
