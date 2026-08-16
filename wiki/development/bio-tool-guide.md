# 生信工具接入指南

本页汇总 `tool_configs/tools_design.md` 的核心要求，指导如何新增一个生信工具到工具箱。

## 工具注册

在 `tool_configs/tools_setting.yaml` 登记前端工具卡片元信息：

```yaml
tools:
  - key: volcano
    name: 火山图
    route: /tools/volcano
    icon: FlameOutline          # @vicons/ionicons5 图标名
    gradient: "linear-gradient(135deg, #ff7e5f, #feb47b)"
    group: visualization        # sequence / visualization / genome / function / environment
    enabled: true
    order: 10
    config_dir: volcano         # tool_configs/volcano/ 配置目录
```

`group` 必须为以下之一：

- `sequence`：序列相关
- `visualization`：可视化
- `genome`：基因组
- `function`：功能注释
- `environment`：环境/工具

## 数据透传链路

```text
YAML(`tool_configs/tools_setting.yaml`，前端卡片)
  → 后端 Pydantic 配置模型
  → ToolItemDTO
  → GET /api/v1/tools
  → 前端 ToolItem 类型
  → components/bio-tools/ToolCard.vue
```

必须保证 `group` 字段在上述链路中完整透传。

## 工具箱展示规则

- 按分组顺序和组内 `order` 升序展示；
- 禁用工具不计数；
- 未知分组归入“其他工具”；
- 分组默认展开，折叠状态使用 `localStorage` 键 `omicHub_tools_group_collapsed` 记忆；
- 卡片必须复用 `components/bio-tools/ToolCard.vue`。

## 图形绘制工具强制闭环

火山图、散点图、热图、箱线图、柱/折线图等必须形成：

```text
导入/粘贴/示例数据 → 自动与手动列映射 → 校验与计算 → 交互式绘图 → 结果表 → PNG/SVG 导出
```

### 参数覆盖

- 数据映射（x/y/group/color/size 等）
- 核心计算（p值阈值、fold change 阈值、聚类等）
- 颜色、坐标轴、标题、标签
- 样式与导出尺寸/DPI

### 分组配色

- 2–6 组：默认 `color_discrete_friendly`
- 7 组：`colors_discrete_friendly_long`
- 8–12 组：`colors_discrete_friendly_long_2`
- 超过色板容量必须提示或筛选，**禁止静默重复颜色**
- 连续数值使用连续色板并显示 colorbar，不能当作分类色板

### 图表质量

- 处理逻辑放入 `utils/<tool>Processor.ts` 的纯函数；
- 处理 `NA` / `NaN` / `Infinity` / 极端值；
- 支持亮暗主题；
- 可解释 hover；
- 受控重绘和页面卸载销毁；
- PNG 导出至少支持 300/600/1000 DPI 或等效倍率；
- SVG 用于矢量导出。

## 工具专属配置目录

在 `tool_configs/<tool>/` 放置：

- 参考数据、物种配置、参数模板；
- Dockerfile（如需要自定义容器）；
- 测试数据；
- README.md 说明使用方法和数据来源。

## 接入 checklist

- [ ] 在 `tools_setting.yaml` 注册前端卡片，指定正确的 `group` 和 `config_dir`
- [ ] 若工具需要被 AI 调用，同时在 `tools_schema.yaml` 注册 function schema、调用模式与结果字段
- [ ] 后端 Pydantic 模型包含 `group` 字段并透传到 DTO
- [ ] 前端 `ToolItem` 类型包含 `group`
- [ ] 工具箱按分组和顺序正确展示
- [ ] 图形工具完成数据闭环与 PNG/SVG 导出
- [ ] 亮/暗主题、空数据、错误状态均已处理
- [ ] 新增依赖已写入 `frontend/package.json` 或 `pyproject.toml`
- [ ] 工具 README.md 已补充
