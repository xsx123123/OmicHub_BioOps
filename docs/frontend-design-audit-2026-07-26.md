# CygnusX 前端设计审计（2026-07-26）

## 范围与方法

- 基线：`cygnusx-frontend-design` 设计系统、`frontend/src` 当前实现、路由/主题/共享组件与主要任务页面。
- 方法：静态代码审计、设计令牌与主题链路检查、响应式/可访问性模式检索、生产构建、类型检查和现有单元测试。
- 本次未进行真实浏览器的截图比对、键盘逐页走查或 375px/高对比度设备验证；这些需要在整改合并前补充。

## 结论

当前平台已有可靠的基础能力：共享 `PageHeader`、Naive UI 主题覆盖、明暗主题令牌、减少动态偏好、页面级懒加载，以及多数页面的局部加载/刷新模式。`npm run type-check`、`npm run build` 与 `npm test` 当前均通过。

主要问题不在于“不能运行”，而在于设计系统尚未成为页面实现的唯一来源：个别页面直接违背布局/表格契约，样式令牌泄漏导致深色主题依赖全局补丁，且大型页面组件使后续一致性治理成本持续升高。

## 发现与整改建议

### P0 — 任务表格列宽违反固定宽度契约

- **证据**：`frontend/src/views/BioTools/BlastTaskHistoryView.vue:41` 与 `frontend/src/views/BioTools/BlastTaskHistoryView.vue:42` 对“查询名称”和“数据库”使用 `minWidth`；`frontend/src/views/BioTools/BlastTaskHistoryView.vue:93` 的 `scroll-x` 为 `920`，而现有列宽下限之和已为 `1040`。
- **影响**：长查询名称会吞占剩余宽度，压缩状态、算法、命中数与操作列；窄屏时表头和内容对齐不可预测。这与设计系统 §33 的“所有列固定 `width`，`scroll-x` 等于列宽之和”直接冲突。
- **整改**：全部改为固定 `width`，保留长文本的 `ellipsis: { tooltip: true }`；将各列宽度相加后作为 `scroll-x`，并为离散列设置 `align: 'center'`。
- **验收**：使用超长查询标题、最小桌面宽度和移动端水平滚动分别验证；不得保留 `minWidth` 或无宽度的列。

### P0 — 标准工作台页面被不必要地收窄

- **证据**：`frontend/src/views/ProfileView.vue:2` 使用自定义 `profile-page-wrapper`，而 `frontend/src/views/ProfileView.vue:206` 的 `.profile-content` 设置 `max-width: 1024px` 并居中。
- **影响**：个人中心与其他工作台页面的内容边界、操作密度和表格/卡片可用宽度不一致；在大屏上浪费科学工作台的横向空间。
- **整改**：改用共享 `.page-container`，移除页面级 `max-width`。只有管理配置中心允许采用 `.admin-config-center` 的 `width: min(100%, 1440px)` 模式。
- **验收**：1280px 与 1920px 下与“任务中心”页面的左右边界、页头和卡片网格保持一致。

### P1 — 令牌链路被硬编码样式与深色主题补丁绕开

- **证据**：视图和共享组件中检出 **239** 处硬编码颜色声明、**575** 处 `var(..., #fallback)`、**324** 处内联 `style`。`frontend/src/styles/global.css:778` 至 `frontend/src/styles/global.css:845` 通过属性选择器和 `!important` 修补部分浅色写法；注释也明确承认该补丁源于大量硬编码浅色样式。
- **影响**：深色主题、品牌换色、强制色彩和组件库升级都需要依赖脆弱的选择器兜底；动态样式、渐变和组件 scoped CSS 无法被这些补丁完整覆盖。
- **重点热点**：`frontend/src/components/ai-chat/KimiMessageItem.vue`、`frontend/src/views/AboutView.vue`、`frontend/src/views/StudioView.vue`、`frontend/src/components/admin/AgentResourceTab.vue`。
- **整改**：先为表面、边框、文本、状态、图表轨道和阴影补齐语义令牌的明暗成对值；将热点组件迁移到令牌；每迁移一批即删除对应的全局深色补丁，而不是继续扩大 `!important` 覆盖范围。
- **验收**：深色主题下不再依赖 `style*=` 选择器修正业务页面；新增页面不得出现页面级十六进制色值，Hero/认证等规范例外需有明确注释和减少透明度回退。

### P1 — 全局异常与路由 chunk 失败缺少统一恢复通道

- **证据**：`frontend/src/main.ts` 只创建并挂载应用，没有设置 `app.config.errorHandler`；`frontend/src/router/index.ts:388` 起仅包含导航守卫，未注册 `router.onError`；`frontend/src/components/AppErrorBoundary.vue:10` 只使用局部 `onErrorCaptured`，并在 `frontend/src/components/AppErrorBoundary.vue:21` 强制整页刷新。
- **影响**：异步错误、路由懒加载 chunk 失败和边界外异常可能只落到控制台或白屏；“刷新”会丢失页面上下文，未满足局部、状态保留的恢复目标。
- **整改**：在 `main.ts` 注册全局错误处理，在路由注册 `router.onError`，将 chunk 失败映射为可重试的 `NResult`；错误边界的首选动作改为“重试当前内容/返回安全页”，整页刷新只作最后降级。生产环境不展示内部错误信息。
- **验收**：模拟动态 import 失败与组件抛错，用户都能看到明确状态、重试动作和安全回退页。

### P1 — 可访问性覆盖未覆盖高对比度与逐页键盘验收

- **证据**：`frontend/src/styles/global.css:762` 已实现 `prefers-reduced-motion`，`frontend/src/styles/global.css:685` 有减少透明度规则；但仓库中没有 `forced-colors` 规则，且本次检索未发现统一的跳过导航链接。自定义视觉层大量存在于聊天、Studio、节日和工具页。
- **影响**：系统强制高对比度模式下，依赖颜色、透明度、阴影或背景图案的状态/边界可能不可辨；长页面的键盘用户需要重复穿过导航。
- **整改**：在全局样式补充 `forced-colors: active` 处理，确保边框、状态与焦点使用系统色；增加跳过导航链接并纳入壳层；对自定义 icon button、抽屉、模态和工作台面板做键盘焦点顺序验收。
- **验收**：键盘可从页面首部跳到主内容；焦点始终可见；强制色彩模式下状态不只靠颜色表达。

### P2 — 浏览器整页刷新用于会话流转，破坏本地状态

- **证据**：`frontend/src/layouts/DefaultLayout.vue:304` 至 `frontend/src/layouts/DefaultLayout.vue:315` 在退出登录和跨标签 token 清除后调用 `window.location.reload()`；其他位置还包括 `frontend/src/api/client.ts:32`、`frontend/src/views/LoginView.vue:184`。
- **影响**：整页刷新会清空可恢复的 UI 状态、增加网络开销，并与“局部刷新、状态保留”的平台约定相悖。
- **整改**：退出登录时清理 store 后使用 `router.replace('/login')`，跨标签事件仅重置认证相关 store 和路由；仅在应用运行时不可恢复时使用硬刷新。
- **验收**：退出/过期会话后不触发浏览器 reload，且不会残留受保护数据。

### P2 — 页面与组件规模已超出一致性治理阈值

- **证据**：共 **211** 个 Vue SFC，其中 **72** 个超过设计系统建议的 300 行拆分阈值。`frontend/src/components/FestivalEffect.vue` 为 1655 行，`frontend/src/components/ai-chat/KimiMessageItem.vue` 为 1593 行，`frontend/src/layouts/DefaultLayout.vue` 为 1429 行，`frontend/src/views/StudioView.vue` 为 1413 行。
- **影响**：视觉状态、数据请求、动画、响应式和交互逻辑耦合，令牌迁移和可访问性修复容易回归；也提高路由 chunk 与首屏解析压力。
- **整改**：优先按“页面壳层 / 数据加载 / 展示卡片 / 操作面板 / scoped 样式”拆分 Studio、聊天消息、布局和节日效果；将重复状态展示抽为共享组件或 composable。
- **验收**：新增和改造组件遵守 300 行拆分提醒；高风险页面拥有独立的交互/样式回归测试。

## 推荐实施顺序

1. **本迭代**：修正 BLAST 表格和 Profile 页面宽度；补齐全局错误/路由 chunk 回退；增加高对比度和跳过导航基础能力。
2. **下一迭代**：从聊天、Studio 和管理资源页开始清除硬编码颜色，按令牌补齐明暗主题；删除已无调用方的深色模式补丁。
3. **持续治理**：分拆超大 SFC，为关键路径添加 Playwright 视觉/键盘回归；在 375px、1280px、1920px、明暗主题、减少动态、减少透明度和强制色彩模式下进行人工验收。

## 验证基线

在 `frontend/` 目录执行，结果均通过：

```text
npm run type-check
npm run build
npm test

11 test files passed
68 tests passed
```

这些结果仅证明当前源码可类型检查、构建和通过既有单测；它们不替代上述视觉、可访问性和交互验收。
