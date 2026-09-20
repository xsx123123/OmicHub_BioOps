# CygnusX 系统架构设计 — 执行计划

## 目标
为华中农业大学园艺林学学院课题组设计一套完整的组内多组学分析云平台（CygnusX）系统架构文档，DDD风格，可直接进入技术评审。

## 阶段划分

### Stage 1 — 并行模块设计（7个子代理同时工作）

| 子代理 | 负责模块 | 输出 |
|--------|----------|------|
| 架构总览设计师 | 6.1 系统架构总览 + 5.1-5.5 核心架构重点总结 | Mermaid架构图、模块划分图、文字说明 |
| 数据库架构师 | 6.2 数据库Schema设计 | 完整建表SQL、索引设计、JSONB字段标注、ER图描述 |
| API接口设计师 | 6.3 API接口设计（REST + WebSocket） | Pydantic DTO定义、路由表、WebSocket事件协议 |
| YAML规范设计师 | 6.4 YAML配置规范（Schema）+ 5.1 YAML动态表单架构详细设计 | Pydantic Model定义、条件渲染规则、参数类型系统、完整示例 |
| 前端架构师 | 6.5 前端路由与页面结构 + 5.2 AI对话窗口架构 | 路由表、组件树、Pinia Store设计、AI面板布局 |
| DevOps架构师 | 6.6 Docker Compose部署方案 + 5.4 WMS混合执行架构 + 5.5 安全设计 | docker-compose.yml、网络规划、安全策略、初始化脚本 |
| 里程碑规划师 | 6.7 开发里程碑（MVP → v1.0） | 3阶段里程碑、每阶段功能点、验收标准 |

### Stage 2 — 整合与审校
- 合并所有子代理输出为一份完整架构文档（Markdown）
- 统一术语、交叉引用、格式一致性检查

### Stage 3 — 文档交付
- 加载 `docx` 技能
- 转换为 .docx 格式输出

## 技能加载
- Stage 1: 无预设技能匹配，自定义子代理
- Stage 2: 无
- Stage 3: `docx` 技能

## 文件传播
- Stage 1 → Stage 2: 各子代理输出写入 /mnt/agents/output/modules/ 目录
- Stage 2 → Stage 3: 整合后的完整 .md 文件
