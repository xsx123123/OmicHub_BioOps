# 日志格式优化计划 (Log Formatting Enhancement Plan)

## 1. 现状分析 (Current State)

目前系统的日志配置位于 `bioreport/ai/wrapper.py` 的 `configure_logging` 函数中。
- **控制台 (Console)**: 使用 `RichHandler`，格式为 `"{message}"`，主要依赖 Rich 的自动着色和排版。
- **文件 (File)**: 使用 `serialize=True`，输出标准的 JSON 格式，包含了 Loguru 默认的所有字段（时间戳、级别、模块、消息等）。

## 2. 优化目标 (Goals)

我们希望明天的修改能达成以下目标：
1.  **更丰富的控制台输出**: 在保持美观的同时，增加关键上下文（如 TraceID、时间戳）。
2.  **可定制的文件日志**: 允许用户在 `config.yaml` 中定义日志文件的字段和结构，或者简化 JSON 输出以减少体积。
3.  **统一 TraceID**: 确保所有相关日志都显式包含 TraceID。

## 3. 建议的日志格式 (Proposed Formats)

### 3.1 控制台格式 (Console)
推荐包含时间、TraceID 和消息。

**当前:** `Starting task...`
**建议:** `[10:00:05] [a1b2c3d4] INFO | Starting task...`

### 3.2 文件日志格式 (File - JSON)
Loguru 的 `serialize=True` 默认输出非常详细。我们可以通过自定义 `sink` 或 `format` 函数来精简它，使其更聚焦于业务指标。

**建议的精简 JSON:**
```json
{
  "time": "2026-01-02 10:00:05",
  "level": "INFO",
  "trace_id": "a1b2c3d4",
  "module": "engine",
  "message": "生成成功 | Cost: ¥0.0124",
  "extra": {
    "cost": 0.0124,
    "tokens": 15000
  }
}
```

## 4. 实施步骤 (Implementation Steps)

### 步骤 1: 修改 `bioreport/config.yaml`
增加日志格式配置项。

```yaml
logging:
  level: "INFO"
  save_json: true
  # 新增配置
  console_format: "<green>{time:HH:mm:ss}</green> | <cyan>[{extra[trace_id]}]</cyan> <level>{message}</level>"
  file_format: "json_simplified" # 或 "standard"
```

### 步骤 2: 修改 `bioreport/ai/wrapper.py`

更新 `configure_logging` 函数，支持从配置读取格式。

```python
def configure_logging(level: str, json_file: str = None, console: bool = True, config: dict = None):
    logger.remove() 
    
    # 1. 获取配置的 TraceID (如果当前上下文有)
    # Loguru 支持通过 logger.bind(trace_id=...) 绑定上下文，
    # 我们需要在 format 中处理 trace_id 可能不存在的情况。
    
    console_fmt = config.get("logging", {}).get("console_format", 
        "<green>{time:HH:mm:ss}</green> | <level>{message}</level>"
    )

    if console:
        # 注意：RichHandler 自带时间戳，如果 format 里也加时间会重复。
        # 建议自定义 handler 或者调整 RichHandler 参数。
        logger.add(
            RichHandler(rich_tracebacks=True, markup=True, show_path=False, show_time=False), 
            format=console_fmt, 
            level=level.upper()
        )

    if json_file:
        # 实现自定义 JSON 序列化器
        def sink_serializer(message):
            record = message.record
            simplified = {
                "time": record["time"].strftime("%Y-%m-%d %H:%M:%S"),
                "level": record["level"].name,
                "message": record["message"],
                "trace_id": record["extra"].get("trace_id", "N/A"),
                # ... 其他需要的字段
            }
            with open(json_file, "a") as f:
                f.write(json.dumps(simplified, ensure_ascii=False) + "\n")

        logger.add(sink_serializer, level="DEBUG")
```

### 步骤 3: 绑定 TraceID (Context Binding)

在 `run_interpretation_task` 中，使用 `logger.bind` 来注入 TraceID，而不是手动在每条日志里写 f-string。

**当前:**
```python
logger.info(f"[{trace_id}] Starting...")
```

**建议 (修改 wrapper.py & engine.py):**
```python
# wrapper.py
with logger.contextualize(trace_id=trace_id):
    logger.info("Starting...")
    engine.generate_report(...)

# engine.py
# 移除所有 f"[{trace_id}] ..."，直接使用 logger.info(...)
# 因为 trace_id 已经在上下文中，会自动包含在日志里（如果 format 配置了 {extra[trace_id]}）
```

这是明天最值得做的重构，能极大地清理代码并统一日志风格。
