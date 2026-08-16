# BioReport AI 解读模块 (AI Interpretation Module)

该模块已进化为**高度模块化、多云支持、生产级可用**的生物信息学报告 AI 生成系统。它集成了自动容错、成本估算、流量控制和结构化验证等多项高级特性。

## ✨ 核心特性 (Key Features)

- **多供应商支持 (Multi-Provider)**: 同时支持**火山引擎 (Volcengine/豆包)** 和 **阿里云 (Aliyun/通义千问)**。
- **自动降级 (Auto-Fallback)**: 当主选供应商 API 失败 (Timeout/5xx) 时，自动无缝切换到备用供应商，确保任务高可用。
- **成本估算 (Cost Estimation)**: 每次生成报告后，自动统计 Token 消耗并根据配置的费率预估本次调用成本。
- **全链路追踪 (Trace ID)**: 每个任务生成唯一 UUID (TraceID)，贯穿日志全流程，便于故障排查。
- **智能截断 (Token Management)**: 自动预估 Prompt Token 数，若超出模型限制 (如 32k)，自动执行 Top-N 数据截断，防止 API 报错。
- **结构化验证 (Structured Output)**: 强制模型输出 XML 标签 `<bio_report>`，并自动校验和提取内容，确保输出格式规范。
- **配置驱动 (Config-Driven)**: 统一管理模型、费率、Fallback 策略和全局参数。

## 🏗 架构组件 (Architecture)

- **`bioreport/ai/cli.py`**: 纯粹的命令行入口，负责参数解析。
- **`bioreport/ai/wrapper.py`**: 业务编排层。负责加载配置、生成 TraceID、配置日志、检查环境变量以及调度引擎。
- **`bioreport/ai/engine.py`**: 核心执行引擎。
    - **Client Factory**: 动态初始化 Ark/OpenAI 客户端。
    - **Inference Logic**: 执行推理、重试 (`tenacity`)、降级循环和成本计算。
    - **Data Processing**: Pydantic 校验、Token 截断、Jinja2 渲染。
- **`bioreport/ai/schemas.py`**: 严格的数据契约定义。

## 📂 目录结构 (Structure)

```text
bioreport/
├── config.yaml             # [核心] 全局配置 (模型、费率、策略)
├── ai/
│   ├── cli.py              # CLI 命令定义
│   ├── wrapper.py          # 任务流封装
│   ├── engine.py           # 底层引擎实现
│   └── schemas.py          # 数据模型
└── templates/
    └── common/ai/          # Prompt 模板
        └── standard_rna.j2
```

## 🚀 快速开始 (Quick Start)

### 1. 配置环境

安装依赖并设置 API 密钥：

```bash
pip install -r requirements.txt
# 根据需要设置
export ARK_API_KEY="your_volc_key"
export DASHSCOPE_API_KEY="your_ali_key"
```

### 2. 模型状态检查

检查配置的模型列表及 API Key 状态：

```bash
python3 -m bioreport.ai.cli model-check
```

### 3. 生成报告 (标准用法)

```bash
python3 -m bioreport.ai.cli report \
  --project-id "PROJ_001" \
  --data-file ./ai_demo/rna_seq_results.json \
  --tissue-type "Liver Tissue" \
  --language "Chinese" \
  --output ./ai_report/
```

### 4. 进阶用法 (覆盖配置)

```bash
python3 -m bioreport.ai.cli report \
  --project-id "PROJ_001" \
  --data-file data.json \
  --provider aliyun \
  --model qwen-plus \
  --temperature 0.7 \
  -e focus_gene=TP53
```

## 🛠 配置说明 (Config)

编辑 `bioreport/config.yaml` 以调整核心策略：

```yaml
ai:
  provider: "volcengine"  # 默认首选供应商
  
  # 自动降级策略：当主供应商失败时，按顺序尝试以下列表
  fallback_providers: ["aliyun"]
  
  # 全局 Token 限制 (触发截断的阈值)
  max_input_tokens: 30000

  # 供应商模型配置
  volcengine:
    model: ["doubao-seed-1-6-251015", "deepseek-v3-2-251201"]
  aliyun:
    model: ["qwen3-max", "qwen-plus"]
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

  # 费率配置 (用于成本预估, 单位: CNY/1k tokens)
  pricing:
    doubao-seed-1-6-251015:
      input: 0.0008
      output: 0.002
    qwen-plus:
      input: 0.004
      output: 0.012
    default:
      input: 0.001
      output: 0.002
```

## 📊 日志与监控

系统会自动在输出目录生成同名的 `.log` 文件 (JSON 格式)，包含详细的运行元数据：

```json
{
  "trace_id": "a1b2c3d4",
  "level": "INFO",
  "message": "生成成功 | Cost: ¥0.0124 | Tokens: {'prompt_tokens': 12000, 'completion_tokens': 1400}",
  "timestamp": "2026-01-02 10:00:00"
}
```

---
*Powered by BioReport AI Engine*