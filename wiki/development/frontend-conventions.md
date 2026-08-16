# 前端规范

## 技术栈（强制）

| 类别 | 选型 |
|---|---|
| 框架 | Vue 3 `<script setup lang="ts">` + Vite |
| UI 库 | Naive UI |
| 图标 | `@vicons/ionicons5` |
| 科学图表 | Plotly.js |
| 通用图表 | ECharts |
| 状态 | Pinia |
| HTTP | `@/api/client` |

## 文件组织

```text
frontend/src/
├── views/BioTools/{Tool}View.vue
├── utils/{tool}Processor.ts
├── components/{module}/
├── api/{module}.ts
├── types/{module}.ts
├── composables/use{Module}.ts
└── stores/{module}.ts
```

## 工具页面紧凑布局

```css
.{key}-page { padding: 16px; min-height: 100%; }
.{key}-layout {
  display: grid;
  grid-template-columns: 300px 1fr 280px;
  gap: 16px;
}
```

- 三栏：左参数 / 中工作区 / 右辅助
- 卡片背景 `var(--neutral-card)`，圆角 12px，padding 12px
- 响应式 `@media (max-width: 1200px)` 退化为单栏

## 工具接入 checklist

1. `tool_configs/tools_setting.yaml` 注册并指定 `group`。
2. `frontend/src/router/index.ts` 加 `tools/{key}` 子路由。
3. 新图标在 `ToolsHubView.vue` 的 `ICON_MAP` 登记。
4. 有后端的工具新建 `tool_configs/{tool-key}/` YAML。
5. 创建 `frontend/src/views/BioTools/{Tool}View.vue`。
