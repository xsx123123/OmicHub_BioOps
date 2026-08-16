# OmicHub 前端设计系统与实现规范

> **用途**：这是 OmicHub 的前端视觉、交互和实现基线。新增页面、组件及样式改动必须以此文档和现有设计令牌为准。它同时可作为其它科学计算、数据平台或工作台类 Vue 项目的迁移参考。
>
> **使用方式**：先阅读“技术边界”和“页面配方”，再按“实施流程”和“验收清单”完成实现。业务组件只消费语义令牌与共享模式；新增全局规则时，必须同步更新本文件及相应源文件。

## 1. 设计目标与非协商原则

OmicHub 是面向生物信息学任务、数据资产与 AI 工作流的科学工作台。界面应传达**平静、清晰、可靠、可控**，而非追求装饰性。

1. **目的明确**：每个控件只服务一个主要任务；优先展示高频路径，复杂选项下沉。
2. **即时反馈**：按下、悬停、聚焦、加载、完成和失败都有即时且可理解的反馈；不等待操作结束才改变界面。
3. **空间一致**：同类对象使用同一圆角、间距、状态色和进入/退出路径；出现的位置决定它消失的方向。
4. **材质有层级**：页面、卡片、浮层、玻璃导航按层级区分；不通过堆叠重阴影或多层玻璃制造层次。
5. **动效克制且可打断**：普通状态变化使用短过渡；只有直接手势控制的抽屉、拖拽或面板才使用可中断的弹簧动效。
6. **可访问性默认交付**：键盘焦点、减少动态、减少透明度、高对比度、文本状态与窄屏布局不是可选项。
7. **真实状态优先**：系统健康、任务进度、权限和错误不能只靠颜色或乐观文案表达；必须与接口状态和加载状态同步。

## 2. 技术边界与权威来源

### 2.1 当前技术栈

| 范畴 | 当前选择 | 规则 |
| --- | --- | --- |
| 框架 | Vue 3 + TypeScript + Vite | 新组件使用 `<script setup lang="ts">` 与 Composition API。 |
| 组件库 | Naive UI + Arco Design Vue | 可按页面和交互场景选择 `NButton`/`NDataTable` 或 `<a-button>`/`<a-table>`；两套组件必须共享平台令牌和状态语义。 |
| 图标 | `@vicons/*` | 使用与现有页面一致的图标集；图标按钮必须提供 Tooltip 或可访问名称。 |
| 样式 | CSS 变量、Tailwind CSS、Sass | 页面优先消费变量和共享工具类；不要复制常量。 |
| 主题 | Pinia 主题状态 + Naive UI `themeOverrides` | 主题由应用层统一提供，业务页面不得覆写全局组件主题。 |

### 2.2 组件库并行使用

本仓库允许并行使用 `naive-ui` 与 `@arco-design/web-vue`。两套组件库服务于同一个平台，不要求每个页面只能使用其中一套；但视觉令牌、主题状态、图标策略、可访问性和交互反馈必须保持统一。

- 现有页面可以继续使用 Naive UI，并通过 `frontend/src/App.vue` 的 `themeOverrides` 维护 Naive UI 主题。
- 新页面、实验性页面或适合 Arco 交互模型的页面可以使用 Arco Design Vue，并通过 `a-config-provider` 与平台令牌接入统一主题。
- 同一页面可以混用两套组件，但不应让同一个交互控件同时由两套组件叠加实现；优先保持页面内部的组件风格连续。
- 两套组件库都必须在应用入口完成注册、样式加载、语言配置和主题配置；不得在业务页面重复初始化全局 Provider。

### 2.3 权威实现位置

| 主题 | 权威实现 | 使用规则 |
| --- | --- | --- |
| 品牌令牌、明暗主题基础值 | `frontend/src/styles/tokens.css` | 修改品牌、背景或文本基础值时在这里处理明暗成对变量。 |
| 全局语义变量、交互、辅助类 | `frontend/src/styles/global.css` | 业务样式优先使用其中变量、`card-hover`、`focus-ring` 等共享模式。 |
| Naive UI 主题覆盖 | `frontend/src/App.vue` | Naive UI 的色彩、圆角、菜单和组件基础外观只在此维护。 |
| 主框架、顶部栏、侧栏 | `frontend/src/layouts/DefaultLayout.vue` | 新导航或壳层变更遵循已有折叠、移动端和滚动规则。 |
| 通用页头 | `frontend/src/components/PageHeader.vue` | 统一标题、说明和右侧操作区；不要在页面重复造页头。 |
| 管理配置中心布局 | `frontend/src/styles/global.css` | 管理中心使用 `.admin-config-center` 和 `.admin-config-tabs`；嵌套资源页使用 `.admin-config-section`，不得以独立 `max-width` 收窄内容。 |
| 仪表盘实时状态模式 | `frontend/src/views/DashboardView.vue` | 系统健康、局部刷新、任务列表与进度条的推荐实现。 |
| 认证页材质与引言 | `frontend/src/views/LoginView.vue`、`frontend/src/views/RegisterView.vue`、`frontend/src/components/StardustQuote.vue` | 认证场景可使用星空和玻璃材质，普通工作台页面保持克制。 |

### 2.4 组件库应用层约定

- `frontend/src/main.ts` 负责注册 Naive UI；不要为单个页面重复安装组件库或引入第二套全局初始化方式。
- `frontend/src/main.ts` 同时负责注册 Arco Design Vue；两套组件库只在应用入口初始化一次。
- `frontend/src/App.vue` 负责 Naive UI 的 `NConfigProvider` 与 `themeOverrides`；Arco 的 `a-config-provider` 也必须在应用壳层统一维护。语言、日期语言、明暗主题、通用色彩、圆角及组件级覆盖不得分散到业务页面。
- `NMessageProvider`、`NDialogProvider` 与 `NNotificationProvider` 已在应用根部提供。`useMessage()`、`useDialog()`、`useNotification()` 只能在这些 Provider 的后代组件或组合式函数调用；需要新增 Provider 时，先说明其覆盖范围和全局影响。
- 本项目当前采用显式导入与全局注册的既有方式。未经构建体积、类型声明和现有代码验证，不要仅为局部页面迁移到自动导入或实验性 Naive UI 功能。
- Tailwind 基础样式、全局 CSS 与 Naive UI 外观发生冲突时，先检查 `global.css` 的选择器和加载顺序；不要用高优先级、深层穿透或 `!important` 批量覆盖 `n-*` 组件。确需控制 Naive UI 样式注入位置或禁用其 preflight 时，应作为应用层变更处理并验证所有页面。

## 3. 设计令牌

### 3.1 令牌使用规则

- 业务组件只使用语义变量，例如 `--neutral-card`、`--neutral-text-2`、`--arco-primary`；不要在 `.vue` 局部样式中硬编码浅色模式色值。
- 新令牌先定义在 `tokens.css` 或 `global.css`，并补全深色模式；再在业务组件中消费。
- 图表沿 `--kimi-chart-1` 至 `--kimi-chart-6` 的顺序取色；进度轨道使用 `--neutral-border`。
- 当组件库 API 需要字符串颜色时，允许传入 `var(--token-name)`，例如 `railColor: 'var(--neutral-border)'`。

### 3.2 色彩

| 语义 | 首选变量 | 浅色基准 | 深色基准/说明 |
| --- | --- | --- | --- |
| 主操作 | `--arco-primary` / `--brand-primary` | `#4C6FFF` | 使用 `#7691FF`；悬停/按下使用对应 `hover`、`active` 变量。 |
| 成功 | `--arco-success` | `#00B42A` | 深色组件使用可读的成功绿；同时提供成功文本或图标。 |
| 警告 | `--arco-warning` | `#FF7D00` | 用于可恢复风险、排队或注意事项。 |
| 错误 | `--arco-danger` | `#F53F3F` | 用于失败、不可用和破坏性操作；不能只用红色表达。 |
| 页面背景 | `--neutral-bg` | `#F5F6FA` | `#0B0F19`。 |
| 卡片/弹窗表面 | `--neutral-card` | `#FFFFFF` | `#151A25`。 |
| 一级文本 | `--neutral-text-1` | `#1D2129` | `#F2F3F8`。 |
| 二级文本 | `--neutral-text-2` | `#4E5969` | `#B8BCC8`。 |
| 辅助文本 | `--neutral-text-3` | `#86909C` | `#7A8194`。 |
| 边框/轨道 | `--neutral-border` | `#E5E6EB` | `#2A3040`。 |
| 悬停底色 | `--neutral-hover` | `#F2F3F8` | 使用深色主题的语义变量或半透明主色。 |

### 3.3 间距、圆角、阴影与排版

| 类别 | 规定 |
| --- | --- |
| 间距阶梯 | 仅使用 `4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48px`，对应 `--space-xs` 至 `--space-5xl`。 |
| 页面内边距 | 默认 `--page-padding: 32px`；密集工具页或窄屏可使用 `16px`。 |
| 卡片 | 默认内边距 `24px`、卡片间距 `20px`；紧凑工具卡片可使用 `12px`。 |
| 圆角 | 常规控件 `8px`、小控件 `4px`、卡片 `12px`、大型面板/认证卡片 `16px`、状态胶囊 `9999px`。 |
| 阴影 | 卡片使用 `--shadow-card` 或 `--shadow-soft`；悬停使用 `--shadow-card-hover`；下拉与弹出层使用 `--shadow-dropdown`。 |
| 字体 | `Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif`。 |

| 文本层级 | 字号 / 行高 | 字重 | 字距 |
| --- | --- | --- | --- |
| Display | `28px / 36px` | 600 | `-0.02em` |
| 页面标题 | `24px / 32px` | 600 | `-0.02em` |
| 区块标题 | `18px / 28px` | 600 | `-0.01em` |
| 卡片标题 | `16px / 24px` | 500 | 默认 |
| 正文 | `14px / 22px` | 400 | 默认 |
| 小正文 | `13px / 20px` | 400 | 默认 |
| 说明文字 | `12px / 18px` | 400 | 默认 |

大标题使用轻微负字距；正文和小字号不压缩字距。层级由字号、字重、行高和色阶共同建立，不只依赖字号。

## 4. 页面结构与材质层级

### 4.1 标准工作台页面配方

按以下顺序组织大多数业务页面：

1. `.page-container` 或页面根元素：提供页面背景、最小高度和 `--page-padding`。
2. `PageHeader`：标题、简短说明和 `#actions` 插槽中的页面级操作。
3. 信息横幅或筛选区：仅在确实影响当前任务时显示。
4. 主内容卡片/网格：采用 `16px` 或 `20px` 间距；页面区块以 `24px` 或 `32px` 分隔。
5. 结果表格、空状态或下一步操作：为首次使用和无数据场景提供明确路径。

页面级刷新、导出、新建等操作放在 `PageHeader` 的 `#actions` 中。卡片内部只放影响该卡片本身的操作，避免同一动作在页面和卡片中重复。

```vue
<PageHeader title="任务中心" subtitle="查看和管理正在运行的分析任务">
  <template #actions>
    <NButton secondary :loading="refreshing" @click="refreshTasks">
      刷新数据
    </NButton>
    <NButton type="primary" @click="createTask">提交任务</NButton>
  </template>
</PageHeader>
```

### 4.2 材质和玻璃表面

1. 页面底层使用 `--neutral-bg`。
2. 常规信息承载在 `--neutral-card` 卡片上，配合 `--neutral-border` 与克制阴影。
3. 顶栏、侧栏和认证场景可使用玻璃材质：半透明背景、`backdrop-filter`、细边界或内高光。
4. 普通内容卡片不叠加玻璃效果；不要在玻璃表面上再放一层浅色玻璃表面。
5. 模态任务使用遮罩与实体表面；并行、非阻塞面板可使用半透明与偏移，不必强制遮罩。

在 `prefers-reduced-transparency: reduce` 下，玻璃表面必须回退到 `--neutral-card` 实色背景并移除模糊。

### 4.3 管理配置中心与嵌套标签页

AI 配置、饼干中心及后续同类后台配置页面使用统一的全宽配置配方。配置中心的顶层标签页、嵌套资源标签页和其中的卡片/表格必须共享同一条内容边界，避免切换标签页时内容区域突然收窄。

| 场景 | 结构与类名 | 规则 |
| --- | --- | --- |
| 配置中心根容器 | `.admin-config-center` | 使用 `width: min(100%, 1440px)` 与 `margin-inline: auto`，承载 `PageHeader` 和顶层 `NTabs`。 |
| 独立配置资源页 | `.admin-config-section.admin-config-section--standalone` | 使用与配置中心相同的最大宽度，独立访问时保留自己的 `PageHeader`。 |
| 嵌入式资源页 | `.admin-config-section` | 必须 `width: 100%` 与 `min-width: 0`；嵌入顶层标签页时不得再设置 `max-width` 或居中外边距。 |
| 配置标签页 | `.admin-config-tabs` | 应用于所有顶层和嵌套 `NTabs type="line"`；导航下方统一保留 `var(--space-xl)` 间距。 |

```vue
<div class="admin-config-center">
  <PageHeader title="AI 配置中心" subtitle="统一维护模型与资源" />
  <NTabs v-model:value="activeTab" type="line" animated class="admin-config-tabs">
    <NTabPane name="providers" tab="模型配置">
      <AdminAIProvidersView embedded />
    </NTabPane>
    <NTabPane name="resources" tab="资源中心">
      <AdminAIResourceCenterView embedded />
    </NTabPane>
  </NTabs>
</div>
```

嵌入的资源页继续使用相同的标签页类，而不重新定义一个较窄的容器：

```vue
<div class="admin-config-section" :class="{ 'admin-config-section--standalone': !embedded }">
  <PageHeader v-if="!embedded" title="AI 资源中心" subtitle="集中管理 MCP、技能与助手资源" />
  <NTabs type="line" animated class="admin-config-tabs">
    <!-- MCP 服务、技能、助手等二级标签页 -->
  </NTabs>
</div>
```

实现规则：

1. 共享样式只定义在 `frontend/src/styles/global.css`；页面不复制 `.n-tabs-nav` 间距或各自维护不同的最大宽度。
2. 顶层与嵌套标签页都使用 Naive UI `type="line"`，沿用应用主题提供的激活态、焦点态和深色模式颜色；不要以局部硬编码颜色覆盖它们。
3. 资源中心处于嵌入模式时，MCP、技能、助手等二级标签的导航、工具栏、表格和空状态应与“模型配置”卡片的左右边界对齐。
4. 新增配置中心应优先复用 `.admin-config-center`、`.admin-config-section` 与 `.admin-config-tabs`；若确实需要较窄的阅读型内容，请建立明确的内容列，而不要修改配置页根容器的宽度。
5. 窄屏下保持 `width: 100%`，由页面壳层的现有水平内边距负责留白；不得通过固定宽度让标签或表格横向溢出。

## 5. 组件实现契约

### 5.1 按钮、链接与图标

| 类型 | 使用方式 |
| --- | --- |
| 主要动作 | `NButton type="primary"`；每个视觉区域通常只有一个主要动作。 |
| 次要动作 | `NButton secondary`、`tertiary` 或 `text`；不要用多个实心主按钮竞争注意力。 |
| 危险动作 | 使用 `type="error"`，并在不可逆或会清理数据时使用 `NPopconfirm` / `NModal`。 |
| 图标按钮 | 使用圆形/弱化按钮；必须有 `NTooltip` 或 `aria-label`。 |
| 页面刷新 | 使用按钮 `:loading` 表示请求中；禁止 `$router.go(0)` 或 `window.location.reload()`。 |

全局按压反馈已经通过共享样式提供轻微缩放。自定义按钮不得将按压缩放扩大为弹跳，不得在过渡期间禁止用户再次操作。

#### 紧凑型胶囊分段切换器

- 适用于 Token 单位、图表形态等同层级的二选一偏好，不用于主流程提交或危险操作。
- 复用全局 `.omichub-segmented-toggle`：`1px` `--neutral-border` 边框、`999px` 圆角、`--neutral-fill-2` 轨道、`11px` 加粗标签；选中态使用 `--arco-primary` 背景和 `--text-on-primary` 文字。
- 容器使用 `role="group"` 和可读 `aria-label`；按钮使用 `aria-pressed`，并提供 hover、focus-visible、键盘操作和 `prefers-reduced-motion` 适配。
- 窄屏保持紧凑但不得裁切标签；图表卡片工具栏在 `640px` 以下允许换行。

### 5.2 卡片

- 使用 `NCard` 或已有 `.arco-card` / `.omichub-card` 外观模式；新卡片优先复用 `NCard`。
- 卡片标题使用 `16px / 24px / 500`；卡片内信息按 `8px`、`12px`、`16px` 阶梯分组。
- 可点击卡片应有 hover、active、focus-visible 和 selected 状态；悬停位移不超过 `2px`。
- 只要卡片本身可点击，就不要在内部塞满冲突的次级点击区域；必要时使用显式操作菜单。

#### 可选择卡片协议

- 所有会保留选择结果的卡片使用 `.omichub-selectable-card`；已选项同时使用 `.is-selected`，或以 `aria-selected="true"`、`aria-checked="true"`、`data-selected="true"` 表达状态。
- 共享规则位于 `frontend/src/styles/global.css`：选中态使用完整、连续的主色内描边与左缘短状态线；状态线只用于已选项，hover 仅显示低强调预览。不要用状态线替代完整边框。
- 单选卡使用 `role="radiogroup"` / `role="radio"` 和 `aria-checked`；列表型选项使用 `role="listbox"` / `role="option"` 和 `aria-selected`。自定义卡片必须支持 `Enter` 与 `Space` 触发选择。
- 已选状态还必须通过现有标签、单选标记或文字说明表达；色彩与状态线不能是唯一的信息来源。

### 5.3 表单与输入

- 统一使用 `NForm`、`NFormItem`、`:model` 和规则校验；字段使用 `v-model`。
- 标签描述输入目的，辅助文本说明格式或副作用，错误文案放在对应字段附近。
- `required`、`disabled`、`loading`、`error` 和成功反馈都必须有可见状态。
- 两列表单在窄屏降为单列；长表单允许纵向滚动，禁止固定 `100vh` 后裁剪内容。
- 日期时间逻辑保持现有项目依赖；不要为单页额外引入重复日期库。
- 表单提交前调用 `FormInst.validate()`；简单字段通常在 `input` 与 `blur` 触发校验，涉及远端检查的异步校验优先在 `blur` 或显式操作后触发，避免每次输入都产生请求。
- 动态数组和嵌套对象必须使用稳定、可定位的 `path`，例如 `samples[${index}].name` 或 `metadata.projectName`；删除、重排或替换字段后，应同步更新模型、规则和错误状态。
- `v-model` 是受控模式：组件值、可选项和加载状态由页面状态统一维护。需要清空受控字段时使用组件接受的空值（通常是 `null`、空字符串或空数组），不要把受控值设为 `undefined` 以免意外切换为非受控模式。
- 远程 `NSelect` 应区分首次加载、关键词搜索和无结果状态；请求需防止旧响应覆盖新关键词结果，并在 `loading` 时保留已选值。多选、大选项集或可创建标签时，必须限制渲染量并清楚说明新值如何保存。
- `NUpload` 必须在客户端和服务端校验类型、大小与权限。需由用户确认后再提交的表单使用 `:default-upload="false"`；自定义上传请求必须报告进度、在成功/失败时调用对应回调，并为失败文件提供重试或移除入口。

### 5.4 数据表格、空状态与反馈

- 使用 `NDataTable`；列标题为 `12px` 辅助色，单元格为 `13px` 主文本色，行 hover 使用 `--neutral-hover`。
- 长标识符、路径和标题必须启用省略与 Tooltip，避免撑破布局。
- 任务状态使用 `NTag`，进度使用 `NProgress`；颜色必须来自语义令牌，轨道使用 `var(--neutral-border)`。
- 加载采用 `NSpin` 或 `NSkeleton`；无数据采用 `NEmpty`，并给出下一步按钮或解释。
- 成功、警告、错误消息使用 `useMessage()`；长期或富内容反馈使用 Notification / Result，不要把所有信息塞进 toast。
- 远程表格将页码、页大小、排序、筛选和关键词收敛为单一查询状态，由可重复调用的 `load*` 函数请求数据；切页、排序和筛选只更新该状态并局部刷新，不重载路由或丢失用户上下文。
- 表格行必须提供稳定唯一的 `row-key`。选择、展开和筛选若需要跨局部刷新保留，使用受控状态；数据更新后应明确移除已不存在行的选择，不能静默指向错误记录。
- 仅在数据量大且表格容器高度可预测时启用 `virtual-scroll`；虚拟表格避免不稳定行高、自动换行的大段内容和依赖完整 DOM 的交互。无法满足这些条件时，采用后端分页、列精简或独立详情页。
- 异步树和超长选项列表应按需加载并使用稳定键；展开、勾选和已加载节点与远端数据分开维护。不要一次性将完整层级或数万选项渲染到 DOM。
- 表格初次加载优先使用贴近列结构的 `NSkeleton`，局部刷新使用表格区域内的 `NSpin` 或按钮 `loading`；失败时保留可理解的上下文、重试入口和已成功加载的数据，而非用空白替换整个页面。

### 5.5 状态与实时数据卡片

运行状态卡片必须同时表达**文本、颜色、加载或异常语义**：

| 状态 | 文本 | 色彩 | 动效 | 行为 |
| --- | --- | --- | --- | --- |
| 检测中 | `检测中…` | 主色 | 低频脉冲 | 禁止展示旧的成功状态。 |
| 正常 | `系统运行正常` | 成功色 | 允许低频脉冲 | 刷新成功后显示最新结果。 |
| 异常 | `异常` / `后端未连接` | 错误色 | 停止循环脉冲 | 提供可重试入口；不误导为成功。 |

数据刷新应重新请求当前页面所需资源，保持滚动位置、筛选与页面上下文。刷新按钮本身展示 `:loading`，并用消息反馈结果。可按以下模式实现：

```ts
const refreshing = ref(false)

async function refreshDashboard() {
  if (refreshing.value) return
  refreshing.value = true
  await loadDashboard()
  refreshing.value = false
  message[healthOk.value ? 'success' : 'warning'](
    healthOk.value ? '仪表板已更新' : '部分平台状态暂不可用，请稍后重试',
  )
}
```

动态状态文本使用 `aria-live="polite"`；状态点仅作辅助，应使用 `aria-hidden="true"`，避免屏幕阅读器重复朗读装饰。

### 5.6 导航、弹窗与认证页

- 顶部导航和侧栏是持久化空间锚点；同一导航项在所有状态下保持相同位置和高亮逻辑。
- 菜单展开、收起、进入和退出遵循同一路径；移动端抽屉支持关闭、键盘逃逸和焦点管理。
- 普通确认使用 `NPopconfirm`；复杂表单或需要更多上下文时使用 `NModal` 或 `NDrawer`。
- 认证页可以使用星空、玻璃卡片、引言和低对比度装饰，但必须在减少透明度/动态模式下回退，并保证正文对比度。
- `NModal`、`NDrawer` 和受控 `NPopconfirm` 使用 `v-model:show` 管理可见性；打开时应将焦点落在标题、首个可操作项或表单首字段，关闭后将焦点返回触发元素。异步确认期间使用按钮 `loading` 并阻止重复提交。
- 短暂、可逆的操作结果使用 `useMessage()`；需要说明原因、提供链接或持续可见的系统事件使用 `useNotification()`、`NAlert` 或 `NResult`。破坏性操作必须先通过 `NPopconfirm` 或包含后果说明的弹窗确认，不能只依赖红色按钮。

### 5.7 渐变背景上的按钮（毛玻璃 + 高亮边框）

Hero 区域（`HomeView.vue`）、通知条幅（`AnnouncementBanner.vue`）等深色渐变背景上的按钮，禁止使用半透明文字按钮或默认主题按钮（对比度不足），统一采用以下两套方案，确保按钮有明确的"浮起"层级感。

**主按钮（白底实心 + 品牌色文字，如"开始分析"、Banner"立即查看"）：**

| 属性 | 值 |
| --- | --- |
| 背景 | `rgba(255,255,255,0.95)`，hover 纯白 `#fff` |
| 文字 | 品牌色（Hero 用 `#4f46e5`，Banner 用 `#6366f1`），`font-weight: 700` |
| 阴影 | `0 0 0 2px rgba(255,255,255,0.3), 0 4px 20px rgba(0,0,0,0.2)`；hover 外发光加强到 3px 并 `translateY(-1px)` |
| 圆角 / padding / 字号 | Hero `12px / 8px 20px / 14px`；Banner `10px / 6px 16px / 13px`（紧凑场景） |

**次按钮（毛玻璃 + 高亮白边，如"查看仪表盘"）：**

| 属性 | 值 |
| --- | --- |
| 背景 | `rgba(255,255,255,0.15)`，hover 加深到 `0.25` |
| 边框 | `1.5px solid rgba(255,255,255,0.6)`（关键：高亮白边保证可见性），hover 亮度提升到 `0.8` |
| 玻璃效果 | `backdrop-filter: blur(12px)` + 内高光 `box-shadow: inset 0 1px 0 rgba(255,255,255,0.1)` 制造玻璃厚度 |
| 文字 | 纯白，`font-weight: 700` |

**统一细节：**

- 所有渐变背景按钮：`letter-spacing: 0.3px`、`transition: all 0.2s ease`、图标与文字间距 `8px`（`.n-button__icon { margin-right: 8px }`）。
- **实现方式（踩坑记录）**：Naive UI 会把 `--n-*` 主题变量以内联 style 写在按钮元素上，class 级变量覆盖不生效。必须用 `.n-button.<自定义类>` 双类选择器直接写 `background-color`/`color`/`border` 等普通 CSS 属性；Naive 的描边由内部 `.n-button__border` 和 `.n-button__state-border` **两个**元素绘制，必须一并 `display: none`，否则会与外发光环叠成"两圈"；图标颜色用 `:deep(.n-button__icon)` 单独指定。
- 响应式下按钮样式不变；移动端依赖 `.hero-actions` 的 `flex-wrap` 换行即可。

## 6. 动效与交互

### 6.1 时间与属性

```css
--motion-quick: 140ms;
--motion-standard: 220ms;
--motion-spring: cubic-bezier(0.2, 0.8, 0.2, 1);
```

- 颜色、边框、焦点和轻微阴影：`140ms` 至 `180ms ease-out`。
- 卡片、导航宽度、面板材质变化：`220ms var(--motion-spring)`。
- 仅动画 `transform` 与 `opacity`；避免用布局属性造成卡顿。
- 悬停以颜色和阴影为主，位移最多 `2px`；`card-hover-lift` 是遗留兼容类，新页面优先用 `card-hover`。
- 普通按钮/菜单禁止无因的回弹、循环位移、长延迟和庆祝性动效。

### 6.2 手势和空间连续性

- 直接拖拽对象必须使用 Pointer Events、指针捕获、1:1 跟随和释放速度衔接。
- 抽屉、底部面板等可手势控制对象使用可中断弹簧；默认临界阻尼、无过冲，只有快速甩动才允许轻微回弹。
- 可逆转场从当前呈现位置继续，而不是从旧目标值跳变；进入和退出遵循同一路径。
- 不要给普通表单、列表刷新或静态卡片加入弹簧或无限循环动画。

### 6.3 减少动态

`prefers-reduced-motion: reduce` 下：取消循环、漂浮、弹跳和大位移，保留极短的颜色/透明度反馈。状态脉冲应变为静态弱晕染；路由转场应变为短暂淡入淡出。

## 7. 响应式与可访问性

### 7.1 响应式规则

- 页面优先保证可读和可操作，再缩减留白。
- 工具页在 `1200px` 以下将三列布局降为单列或两列；常规双栏在 `1024px` 以下降为单列。
- 页面内边距在 `768px` 以下通常降至 `16px`。
- `640px` 以下的页头操作区换行并占满可用宽度；触控目标保持足够尺寸。
- 允许表格水平滚动或选择简化列，禁止通过压缩文字破坏可读性。

### 7.2 可访问性最低要求

1. 所有键盘可操作元素保留 `2px solid var(--arco-primary)`、`3px` 外偏移的 `:focus-visible` 焦点环。
2. 任何仅靠颜色表达的内容都额外提供文字、图标、位置或 ARIA 语义。
3. 图标按钮提供 Tooltip 或 `aria-label`；加载状态使用组件 `loading` 属性，动态文本使用恰当 `aria-live`。
4. `prefers-reduced-transparency: reduce` 下移除模糊并使用实体背景；`prefers-contrast: more` 下增强焦点环、边界和文本对比。
5. 保持原生语义：页面标题用单个 `h1`，卡片区块按需使用 `section` 和 `h2/h3`，不要仅用 `div` 模拟交互控件。
6. 可选择卡片在状态变化后同步更新 `.is-selected` 与对应 ARIA / `data-selected` 属性；键盘触发路径必须与鼠标点击一致。

## 8. 跨平台迁移策略

将本规范用于新平台时，按以下顺序迁移，而非复制局部 CSS：

1. **建立令牌层**：先创建品牌、明暗主题、文本、边框、间距、圆角、阴影与动效令牌。
2. **选定单一组件库**：OmicHub 使用 Naive UI；新 Vue 平台可选择 Arco Design Vue，但不得混用。
3. **配置应用层主题**：在入口注册组件库、全局语言、主题和图标；将主色、圆角、背景与表面映射到令牌。
4. **建立壳层**：先完成顶部栏、侧边栏、移动端抽屉和统一页头，再开发业务页面。
5. **沉淀页面配方**：实现仪表盘、列表/表格、详情、表单、空状态和错误状态的标准模板。
6. **最后接入业务接口**：加载、重试、部分失败和权限状态必须按本规范呈现。

### 8.1 Naive UI 与 Arco Design Vue 对照

| 场景 | OmicHub（Naive UI） | 新平台如选择 Arco Design Vue |
| --- | --- | --- |
| 主按钮 | `NButton type="primary"` | `<a-button type="primary">` |
| 表单 | `NForm` + `NFormItem` | `<a-form>` + `<a-form-item>` |
| 数据表格 | `NDataTable` | `<a-table>` |
| 提示 | `useMessage()` | `Message` 服务 |
| 弹窗 | `NModal` / `NPopconfirm` | `<a-modal>` / `<a-popconfirm>` |
| 全局主题 | `NConfigProvider` + `themeOverrides` | `app.use(ArcoVue)` + `<a-config-provider>` / Arco 主题变量 |

Arco 项目遵守 Vue 3 `<script setup lang="ts">`、kebab-case 模板属性、`v-model`、`#slot`、`dayjs` 日期处理和 Arco 图标入口的约定。该对照用于保证 Naive UI 与 Arco Design Vue 并行时的实现一致性。

## 9. 实施流程

每次前端改动按以下流程执行：

1. **确认场景**：识别页面任务、目标用户、主要动作、失败状态和窄屏行为。
2. **复用现有组件**：先查 `PageHeader`、共享卡片、表格、空状态、认证页与全局工具类；避免重复实现。
3. **选择令牌**：只使用语义颜色、间距、圆角、阴影和排版变量；需要新变量时先补全明暗主题。
4. **实现完整状态**：至少覆盖 default、hover、active、focus-visible、disabled、loading、empty、error 和 success（适用时）。
5. **接入数据**：把接口请求收敛到可重复调用的 `load*` 函数；局部刷新调用该函数，而非重载整个路由。
6. **处理可访问性与响应式**：检查键盘、减少动态、减少透明度、高对比度、窄屏和长内容。
7. **验证**：运行 `npm run type-check` 与 `npm run build`；检查 `git diff --check`，并在可用时人工查看明暗主题与关键断点。
8. **同步文档**：若新增全局令牌、共享类、页面配方或交互模式，更新本文件并标注权威实现位置。

## 10. 变更验收清单

- [ ] 页面是否复用 `tokens.css`、`global.css` 与 `App.vue` 的主题体系？
- [ ] Naive UI 与 Arco Design Vue 是否共享同一套令牌、主题状态、可访问性和交互语义？
- [ ] 是否复用了 `PageHeader`，并把页面级操作放入 `#actions`？
- [ ] 是否避免硬编码只适用于浅色模式的背景、边框、图表轨道和状态颜色？
- [ ] 按钮、卡片、输入和表格是否具备 hover、active、focus-visible、disabled、loading 和 error 等适用状态？
- [ ] 所有可选择卡片是否使用 `.omichub-selectable-card`，并提供连续选中描边、左缘状态线、文本或图标提示与键盘选择？
- [ ] 系统健康、进度和任务状态是否同时呈现文本、颜色与加载/错误语义？
- [ ] 刷新是否保持页面上下文，而不是使用整页重载？
- [ ] 是否处理了空状态、部分失败、权限不足和长文本溢出？
- [ ] 动效是否短促、必要、可中断，并在减少动态下安全回退？
- [ ] 是否验证了浅色、深色、窄屏、高对比度和键盘焦点？
- [ ] 是否通过 `npm run type-check`、`npm run build` 和 `git diff --check`？
- [ ] 叠层与装饰覆盖层是否符合 §31：无 `.x > *` 等过宽定位/布局选择器；装饰层保持出流并 `pointer-events:none`、`aria-hidden`？
- [ ] 样式改动是否在**构建产物或 nginx 实际响应**中 grep 到对应选择器/属性（注意路由分包 chunk，不在主 `index-*.css`），并硬刷新验证（§31.5）？
- [ ] 数据表格/卡片是否符合 §33.2：进度经归一化函数渲染、`NProgress` 百分比不换行（`.n-progress-graph{min-width:0}`）、**所有列固定 `width` 且 `scroll-x`=列宽之和**、短值列 `align:'center'`、卡片垂直间距 24px？
- [ ] 进度/百分比/计数等派生数值是否在任何数据尺度下都正确（§33.2 进度尺度归一化），而非依赖单一写死约定？
- [ ] 设计是否规避 §33.1 的「AI 默认」清单（纯白无氛围、三列等宽 hero、统一间距/圆角、通用无衬线、对称留白），在不破坏 §1 克制原则的前提下具备品牌辨识度与层次？

## 11. 可复用 Skill 入口

本规范对应本机 Codex 技能 `$omichub-frontend-design`。技能入口保持简洁，完整参考保存在本文件；当令牌、共享组件或工作流变化时，先更新本文件，再同步技能引用副本。

建议的调用方式：

```text
使用 $omichub-frontend-design 优化此 Vue 工作台页面；沿用项目已有组件库和主题，先检查设计令牌、页面状态、响应式与可访问性，再实施并验证构建。
```

技能用于提供一致的实施流程，不替代具体仓库中的 `AGENTS.md`、前端架构说明或组件库文档；发生冲突时，以当前仓库的直接指令和实现为准。

## 12. 工具详情页返回按钮与页头对齐规范

工具箱中的工具详情页统一使用 `frontend/src/components/PageHeader.vue` 作为页头：

```vue
<PageHeader
  title="FASTQ 极速质控"
  subtitle="使用 fastp 与 MultiQC 完成测序数据质控与汇总"
  back-to="/tools"
  back-label="返回工具箱"
/>
```

- 返回按钮必须位于标题与副标题文本块的垂直中线位置，不得固定贴在标题顶部。
- `PageHeader` 的 `.page-header-main` 使用 `align-items: center`，标题、副标题和返回按钮作为同一组进行垂直对齐。
- 工具页的返回按钮保留圆形弱化按钮、Tooltip 和 `aria-label`，桌面端与窄屏端都必须可见、可聚焦、可操作。
- 新增工具优先复用 `PageHeader`，不要在视图中重复实现返回按钮和标题布局。
- 全屏工具可以保留专用工具栏，但返回按钮仍需与标题信息块垂直居中；JBrowse、YAML 基因组浏览器和终端遵循各自已有工具栏样式。

## 13. 数据可视化规范

本项目使用 **ECharts 5**（含 `echarts-gl`、`vue-echarts`）和 **Plotly.js** 两套图表引擎。新增图表必须遵循以下规则。

### 13.1 引擎选择

| 场景 | 推荐引擎 | 理由 |
| --- | --- | --- |
| 交互式统计图（柱状、折线、饼图、散点） | ECharts (`vue-echarts`) | 声明式配置、主题集成好、体积可控 |
| 火山图、曼哈顿图、热图等生信专用图 | ECharts + 自定义 processor | 已有 `volcanoProcessor`、`manhattanProcessor` 等成熟实现 |
| 3D 曲面、GL 散点 | ECharts GL | 已安装 `echarts-gl` |
| 系统发育树、复杂交互式树图 | Plotly.js 或专用 SVG 渲染 | 已有 `phyloProcessor` 处理 Newick → 坐标 |
| 富集分析气泡图、柱状图 | ECharts | 已有 `enrichmentProcessor` |
| 需要导出为静态出版级图片 | Plotly.js (`toImage`) | 内置高清导出 |

**规则**：同一页面不得同时引入 ECharts 和 Plotly；若页面已有 ECharts 图表，新增图表优先使用 ECharts。

### 13.2 主题与配色

- 图表系列色按 `--kimi-chart-1` 至 `--kimi-chart-6` 顺序取色；超过 6 个系列时循环使用并增加透明度区分。
- 背景透明（`backgroundColor: 'transparent'`），让卡片背景透出。
- 坐标轴文字使用 `--neutral-text-3`（12px），轴标题使用 `--neutral-text-2`（13px）。
- 网格线使用 `--neutral-border`，虚线 `dashed`。
- 深色模式下通过 CSS 变量自动适配；不得在 JS 中硬编码 `#fff` 或 `#333`。
- **ECharts option 中禁止直接写 `'var(--xxx)'`**：ECharts 在 canvas 上绘制时无法解析 CSS 变量，会得到黑色（2026-07 仪表盘"任务提交趋势"黑色柱状图即此 bug）。必须先用 `getComputedStyle(document.documentElement).getPropertyValue(...)` 解析为具体色值再传入 option，并 watch 主题切换后 `nextTick` 重新解析（参考 `TrendChart.vue` 的 `cssVar` + `themeVersion` 模式）。DOM 内联样式不受此限。
- 显著性标注（p-value 阈值线、差异基因高亮）使用 `--arco-danger` 和 `--arco-success`。

### 13.3 交互与响应式

- 所有图表必须提供 `tooltip`；tooltip 背景使用 `--neutral-card`，边框使用 `--neutral-border`，文字使用 `--neutral-text-1`。
- 数据点超过 500 时启用 `large` 模式或 `sampling`；超过 5000 时使用 `dataZoom` 或后端聚合。
- 图表容器使用 `ResizeObserver` 或 `vue-echarts` 的 `autoresize` 响应容器尺寸变化。
- 窄屏下图表最小高度 `240px`，允许水平滚动而非压缩到不可读。
- 图表加载使用 `NSkeleton`（矩形块）占位；加载失败显示 `NEmpty` + 重试按钮。

### 13.4 导出与无障碍

- 需要导出的图表提供"下载 PNG/SVG"按钮，放在卡片 `#header-extra` 或工具栏中。
- 图表必须提供 `aria-label` 或相邻的数据摘要表格，不能仅靠视觉传达关键结论。
- 颜色编码的信息（如上调/下调）必须同时使用形状、标签或图例文字表达。

### 13.5 Processor 模式

生信图表的数据转换统一放在 `frontend/src/utils/*Processor.ts`：

- 每个 processor 是纯函数，输入后端原始数据，输出 ECharts `option` 或 Plotly `data + layout`。
- Processor 不得发起网络请求或访问全局状态。
- 新增 processor 文件命名：`{domain}Processor.ts`，并在对应 View 中按需导入。

### 13.6 仪表盘"任务提交趋势"图（TrendChart）

`frontend/src/components/dashboard/TrendChart.vue` 是仪表盘的标准趋势图样板，描述与约定如下：

- **图表形态**：双 Y 轴组合图。左轴"任务数"为柱状图（bar），右轴"样本数"为平滑折线（line, `smooth: true`）；两系列量级差异大，必须分轴（`yAxisIndex: 1`），禁止共用单轴压扁小数值系列。
- **配色**：柱 `--arco-primary`（品牌蓝，圆角 `[4,4,0,0]`，`barMaxWidth: 32`），折线 `--arco-warning`（橙色，线宽 2，圆点 `symbolSize: 6`）。颜色一律经 `cssVar()` 解析后传入（见 §13.2 的 var() 禁令）。
- **布局**：`grid: { left: 12, right: 12, top: 24, bottom: 32, containLabel: true }`；图例置底（`bottom: 0`），10×10 图例标记；双轴名称"任务数/样本数"分别左、右对齐（`align` + 负 `padding` 内收到绘图区上方）。
- **交互**：`tooltip.trigger: 'axis'`；卡片头部右侧提供"柱状 / 面积"图形态切换和"近 7 天 / 近 30 天"时间范围切换。图形态切换使用与 Token "K / M" 相同的胶囊分段按钮：`1px` `--neutral-border` 边框、`999px` 圆角、`--neutral-fill-2` 轨道、`11px` 加粗标签，选中态使用 `--arco-primary` 背景和 `--text-on-primary` 文字；按钮必须提供 `aria-pressed`，并支持 hover、focus-visible、窄屏换行和 `prefers-reduced-motion`。时间范围继续使用 `ghost` 小按钮，选中态 `type="primary"`，切换即重新请求 `GET /stats/trend?days=N`。
- **图形态**：默认显示柱状图：任务数为主色柱状系列，样本数为橙色平滑折线；切换到面积图后，任务数和样本数均使用平滑折线与低透明度面积填充，保留双 Y 轴与同一数据语义，不重新请求接口。
- **状态**：加载用 `NSpin` 包裹；无数据时显示 `EmptyState`（📈 + 引导文案），高度保持 260px 不塌缩。
- **数据来源**：`/stats/trend` 返回 `TrendPoint[]`（`{ date, tasks, samples }`），X 轴为 MM/DD 日期类目轴。

## 14. 实时通信与 WebSocket

项目已有多个 WebSocket 组合式函数（`useAIWebSocket`、`useTerminalWebSocket`、`useSandboxWebSocket`、`useWorkflowMonitorWebSocket`、`useCookieWebSocket`）和流式组合式函数（`useChatStream`、`useAgentChatStream`、`useStudioRunStream`）。

### 14.1 连接生命周期

| 阶段 | 要求 |
| --- | --- |
| 建立 | 在组件 `onMounted` 或用户显式操作后连接；不在模块顶层或路由守卫中建立连接。 |
| 心跳 | 每 30s 发送 ping；服务端 10s 内无 pong 视为断开。 |
| 重连 | 指数退避（1s → 2s → 4s → 8s → 最大 30s），最多重试 5 次；重连期间 UI 显示"连接中…"状态。 |
| 销毁 | 在 `onUnmounted` 或 `onBeforeUnmount` 中关闭；页面切换不得遗留僵尸连接。 |
| 可见性 | `document.visibilitychange` 隐藏时暂停心跳，恢复时立即检测连接状态。 |

### 14.2 UI 状态映射

| 连接状态 | UI 表达 |
| --- | --- |
| `connecting` | 状态点主色 + 脉冲；操作按钮 `disabled` 或 `loading`。 |
| `connected` | 状态点成功色；功能可用。 |
| `reconnecting` | 状态点警告色 + 文字"重新连接中…"；保留已有内容不清空。 |
| `disconnected` | 状态点错误色 + 文字"连接已断开"；提供手动重连按钮。 |

### 14.3 消息处理

- 消息类型使用 `type` 字段区分（如 `output`、`status`、`error`、`done`）；未知类型静默忽略并 `console.warn`。
- 流式文本（AI 对话、终端输出）使用追加渲染，不重建整个 DOM；长输出启用虚拟滚动或限制 DOM 行数（保留最近 5000 行）。
- 二进制消息（文件传输）使用 `ArrayBuffer`，不在 WebSocket 中传输 Base64 编码的大文件。
- 错误消息必须映射为用户可理解的中文提示，不直接展示原始 JSON 或堆栈。

### 14.4 组合式函数契约

新增 WebSocket 组合式函数必须：

- 返回 `{ status, data, error, connect, disconnect }` 基本接口。
- 接受 `url` 或 `urlRef`（响应式）参数。
- 内部处理重连、心跳和清理，调用方不需要关心底层。
- 使用 `shallowRef` 存储高频更新数据（终端输出、流式文本），避免深层响应开销。

## 15. API 层与数据请求

### 15.1 目录与命名

- 所有 API 模块位于 `frontend/src/api/`，按业务域命名（`tools.ts`、`blast.ts`、`phylo.ts`）。
- 管理端 API 放在 `frontend/src/api/admin/` 子目录。
- 每个模块导出具名函数（如 `getBlastResult`、`submitEnrichment`），不导出裸 axios 调用。
- 请求/响应类型定义在 `frontend/src/types/` 对应文件中。

### 15.2 请求规范

- 统一使用 `frontend/src/api/client.ts` 导出的 axios 实例（`baseURL: /api/v1`，超时 30s）。
- 长耗时请求（文件上传、任务提交）可单独设置更长超时，但不超过 5 分钟。
- 请求参数使用 `params`（GET）或 `data`（POST/PUT），不拼接 URL 字符串。
- 需要取消的请求（搜索建议、页面切换）使用 `AbortController`；组件卸载时取消未完成请求。

### 15.3 错误处理

| HTTP 状态 | 前端行为 |
| --- | --- |
| 401 | 由拦截器自动刷新 token；刷新失败跳转登录页并携带 `redirect`。 |
| 403 | 显示权限不足提示（`NAlert` 或 `NResult`），不自动跳转。 |
| 404 | 页面级：显示 `NResult status="404"`；资源级：`useMessage().error()`。 |
| 422 | 表单校验错误：映射到对应字段；非表单场景：`useMessage().error()`。 |
| 429 | 提示"操作过于频繁，请稍后重试"；禁用触发按钮 5s。 |
| 500/502/503 | 提示"服务暂时不可用"；提供重试按钮；不暴露后端堆栈。 |
| 网络错误 | 提示"网络连接失败，请检查网络"；保留已加载数据。 |

- 业务错误（HTTP 200 但 `code !== 0`）由调用方根据 `message` 字段提示用户。
- 全局拦截器只处理 401 刷新；其余错误由调用方决定提示方式，避免重复 toast。

### 15.4 数据加载模式

- 每个页面/组件的数据加载收敛为 `load*` 函数，支持重复调用。
- 首次加载：`NSkeleton` 占位（贴近最终布局）。
- 局部刷新：表格区域 `NSpin` 或按钮 `:loading`，不清空已有数据。
- 分页/排序/筛选：更新查询状态对象后调用 `load*`，不重载路由。
- 并行请求使用 `Promise.allSettled`，部分失败时展示成功部分 + 失败提示。
- 轮询（任务进度）使用 `setInterval` + 组件卸载清理；优先使用 WebSocket 推送替代轮询。

## 16. 状态管理

### 16.1 Pinia Store 使用原则

| 放入 Store | 留在组件本地 |
| --- | --- |
| 跨页面/跨组件共享的状态（用户信息、主题、通知） | 单组件内部的表单值、UI 开关 |
| 需要持久化的状态（token、偏好设置） | 请求加载的列表数据（除非多组件共享） |
| WebSocket 连接状态（终端、AI 对话） | 临时计算结果、图表 option |
| 全局配置（站点配置、权限列表） | 分页、排序等页面级查询状态 |

### 16.2 Store 规范

- 文件位于 `frontend/src/stores/`，命名 `{domain}.ts`，导出 `use{Domain}Store`。
- 使用 Setup Store 语法（`defineStore` + 组合式函数风格），与项目 `<script setup>` 一致。
- Store 内不直接操作 DOM 或调用 `useMessage()`；UI 反馈由组件层处理。
- 异步操作（API 调用）可以在 Store 中发起，但必须处理 loading 和 error 状态。
- 需要持久化的 Store 使用 `pinia-plugin-persistedstate` 或手动 `localStorage`；token 类敏感数据使用 `sessionStorage` 或内存。

### 16.3 组件间通信

- 父子组件：`props` + `emit`，不使用事件总线。
- 兄弟/跨层级：Pinia Store 或 `provide/inject`（限同一页面内）。
- 全局事件（如主题切换、权限变更）：通过 Store 的 `$subscribe` 或 `watch` 响应。

## 17. 文件操作

### 17.1 上传

- 小文件（< 10MB）：`NUpload` + 默认 `multipart/form-data`。
- 大文件（≥ 10MB）：使用 `useChunkUpload` 分片上传；分片大小默认 5MB。
- 上传前必须客户端校验：文件类型（扩展名 + MIME）、大小上限、数量限制。
- 上传中显示进度条（`NProgress`）；支持取消和失败重试。
- 生信文件（FASTQ、BAM、VCF、GFF）额外校验格式魔数或首行格式。
- 拖拽上传区域使用虚线边框 + 图标 + 文字说明；`dragover` 时高亮。

### 17.2 下载

- 小文件直接 `<a download>` 或 `window.open`。
- 大文件使用 `useDownloadProgress` 组合式函数，通过 `fetch` + `ReadableStream` 报告进度。
- 下载按钮显示进度百分比；完成后使用 `useMessage().success()` 反馈。
- 批量下载打包为 zip 由后端处理；前端显示打包进度。

### 17.3 文件预览

- 文本类（FASTA、CSV、日志）：前 100 行预览 + "查看完整文件"。
- 图片（PNG、SVG）：`NImage` 预览。
- 不支持预览的格式：显示文件图标 + 元信息（大小、修改时间）+ 下载按钮。
- 预览不加载完整文件到内存；使用 Range 请求或后端截断。

## 18. AI 对话与流式界面

### 18.1 对话布局

- 消息列表使用 `flex-direction: column`；用户消息右对齐，AI 消息左对齐。
- 消息气泡最大宽度 `720px`；代码块和表格允许占满气泡宽度。
- 长对话启用虚拟滚动或"加载更多历史"分页，不一次性渲染全部消息。
- 新消息自动滚动到底部；用户向上滚动时暂停自动滚动并显示"回到底部"按钮。
- 对话区若叠加装饰背景/光晕（如 `ShaniaChatBackground` 全息层），必须遵守 §31：装饰层保持出流、`pointer-events:none`，内容层按**类名**显式抬升；**禁止**用 `.容器 > *` 通配设置 `position`/`z-index`（该反模式曾把仅 `shania` 渲染的装饰层拉进文档流，导致顶栏塌陷、顶部整块空白）。

### 18.2 流式输出

- 使用 `useChatStream` / `useAgentChatStream` 处理 SSE 或 WebSocket 流。
- 流式文本逐字/逐块追加渲染；使用 `shallowRef` + `requestAnimationFrame` 节流更新（≤ 60fps）。
- 流式过程中显示光标闪烁或"正在输入"指示器。
- 流中断（网络断开、用户取消）：保留已输出内容 + 显示"生成已中断"标记 + 重新生成按钮。
- Markdown 渲染使用流式安全的解析器，避免未闭合代码块导致布局跳动。

### 18.3 输入区

- 多行文本框（`NInput type="textarea"` + `autosize`）；`Enter` 发送，`Shift+Enter` 换行。
- 发送按钮在空内容或生成中时 `disabled`；生成中变为"停止"按钮。
- 支持附件（图片、文件）时，输入区上方显示附件预览条。
- 输入历史：`↑`/`↓` 切换最近发送的消息（可选）。

### 18.4 工具调用与多步结果

- AI 调用工具时，在消息流中插入"工具卡片"：显示工具名、参数摘要、执行状态和结果折叠区。
- 长时间工具执行显示进度或旋转指示器；超时（> 60s）提示用户。
- 错误结果使用 `NAlert type="error"` 内嵌在消息中，不中断对话流。

## 19. 终端与代码沙箱

### 19.1 终端 UI

- 使用等宽字体：`'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace`。
- 背景使用 `--neutral-card` 或专用深色终端背景（深色模式下与页面背景区分）。
- 输出区域限制 DOM 行数（最近 5000 行）；超出时截断顶部并提示"更早输出已截断"。
- 支持文本选择复制；`Ctrl+C` 在无选区时发送 SIGINT，有选区时复制。
- 连接状态指示器放在终端标题栏右侧。

### 19.2 代码沙箱

- 编辑器区域使用项目已集成的代码编辑组件；不额外引入新编辑器库。
- 运行按钮使用 `:loading` 表示执行中；输出面板与编辑器上下或左右分栏。
- Pyodide（客户端 Python）首次加载显示下载进度；后续使用缓存。
- 执行超时默认 30s；超时后终止并提示。
- 沙箱环境隔离：不访问宿主文件系统、不发起网络请求（除 Pyodide 包安装）。

## 20. 代码组织与命名

### 20.1 目录结构

```
frontend/src/
├── api/              # API 请求模块（按业务域）
│   └── admin/        # 管理端 API
├── assets/           # 静态资源（图片、字体）
├── components/       # 共享组件（跨页面复用）
│   └── {domain}/     # 按业务域分子目录（blast/、chat/）
├── composables/      # 组合式函数（use* 命名）
├── config/           # 应用配置常量
├── layouts/          # 布局组件
├── router/           # 路由定义与守卫
├── stores/           # Pinia Store
├── styles/           # 全局样式与令牌
├── types/            # TypeScript 类型定义
├── utils/            # 工具函数与数据处理器
└── views/            # 页面级组件（按功能域分子目录）
    ├── BioTools/     # 生信工具页
    ├── Dashboard/    # 仪表盘
    └── ...
```

### 20.2 命名规则

| 对象 | 规则 | 示例 |
| --- | --- | --- |
| 组件文件 | PascalCase | `BlastHitDetailCard.vue` |
| 组合式函数 | camelCase + `use` 前缀 | `useChunkUpload.ts` |
| Store | camelCase + `use` 前缀导出 | `useThemeStore` |
| API 函数 | camelCase + 动词前缀 | `getTaskList`、`submitBlast` |
| 类型/接口 | PascalCase | `EnrichmentResult` |
| CSS 类 | kebab-case 或 BEM | `.omichub-selectable-card`、`.page-header-main` |
| 路由 name | PascalCase | `BlastSearch`、`PhylogeneticTree` |
| 常量 | UPPER_SNAKE_CASE | `MAX_UPLOAD_SIZE` |

### 20.3 组件拆分原则

- 单文件组件超过 300 行时考虑拆分。
- 可复用（≥ 2 处使用）的 UI 片段提取到 `components/`。
- 页面专用的子组件放在 `views/{Domain}/components/` 子目录。
- 纯逻辑复用提取为 `composables/`；纯数据转换提取为 `utils/*Processor.ts`。

## 21. 性能预算与优化

### 21.1 包体积

| 指标 | 预算 |
| --- | --- |
| 首屏 JS（gzip） | ≤ 300KB |
| 单路由懒加载块（gzip） | ≤ 150KB |
| ECharts 按需引入 | 只注册使用的图表类型和组件 |
| Plotly.js | 仅在需要 Plotly 的路由懒加载 |

- 路由级代码分割：所有 `views/` 使用 `() => import(...)` 懒加载。
- 第三方库按需导入：ECharts 使用 `use()` 注册；Naive UI 保持现有全局注册方式。
- 图片资源使用 WebP/AVIF + `srcset`；图标使用 SVG 组件或图标字体，不用 PNG 图标。

### 21.2 渲染性能

- 列表超过 100 项使用虚拟滚动（`NDataTable virtual-scroll` 或 `vue-virtual-scroller`）。
- 高频更新数据（终端输出、流式文本）使用 `shallowRef` + 批量 DOM 更新。
- 避免在 `v-for` 中使用复杂计算；提取为 `computed` 或预处理。
- 大表格/大图表页面使用 `v-once` 或 `shallowReactive` 减少响应开销。
- 图片懒加载：视口外图片使用 `loading="lazy"` 或 `IntersectionObserver`。

### 21.3 网络优化

- 静态资源使用内容哈希文件名 + 长期缓存。
- API 响应按场景设置缓存策略：配置类（5min）、列表类（不缓存）、详情类（30s）。
- 预加载：用户悬停导航项时预加载对应路由 chunk（`link rel="prefetch"`）。
- 避免瀑布请求：并行无依赖请求使用 `Promise.allSettled`。

## 22. 测试策略

### 22.1 测试金字塔

| 层级 | 工具 | 覆盖目标 |
| --- | --- | --- |
| 单元测试 | Vitest | 工具函数、Processor、Store、组合式函数 |
| 组件测试 | Vitest + @vue/test-utils | 共享组件的交互和状态 |
| E2E 测试 | Playwright | 关键用户路径（登录、提交任务、查看结果） |

### 22.2 测试规则

- `utils/*Processor.ts` 必须有单元测试：覆盖正常数据、空数据、异常数据。
- Store 测试覆盖：初始状态、主要 action、错误处理。
- 组件测试覆盖：渲染、用户交互（点击、输入）、props 变化、emit 事件。
- E2E 覆盖黄金路径：登录 → 选择工具 → 提交任务 → 查看结果 → 登出。
- 测试文件与源文件同目录（`*.test.ts`）或放在 `tests/` 镜像目录。
- CI 中运行 `vitest run` + `playwright test`；测试不通过不合并。

### 22.3 Mock 策略

- API Mock：使用 `msw`（Mock Service Worker）拦截请求，不在组件中条件判断 mock。
- WebSocket Mock：使用 `mock-socket` 模拟服务端消息。
- 开发环境可使用 `frontend/src/mock/` 中的静态数据辅助调试，但测试必须使用 msw。

## 23. 安全规范

### 23.1 XSS 防护

- 模板中不使用 `v-html` 渲染用户输入或后端未转义内容；必须使用时先经过 DOMPurify 过滤。
- AI 输出的 Markdown 渲染使用安全的 Markdown 解析器（如 `markdown-it` + 禁用 `html` 选项）。
- 用户文件名、路径在 UI 展示时使用文本插值 `{{ }}`，不拼接到 HTML 属性中。

### 23.2 认证与令牌

- JWT 存储在 `localStorage`（当前实现）；敏感操作（删除、权限变更）需要二次验证。
- Token 刷新由 axios 拦截器统一处理；组件不直接操作 token。
- 登出时清除所有本地存储的认证信息和用户数据。
- WebSocket 连接在建立时携带 token；token 过期时服务端断开连接，客户端触发刷新重连。

### 23.3 输入校验

- 所有用户输入在提交前进行前端校验（格式、长度、类型）；前端校验不替代后端校验。
- 文件上传校验扩展名 + MIME type + 文件大小；不信任客户端单独校验。
- URL 参数和查询字符串使用 `encodeURIComponent`；路由参数使用 Vue Router 的 `params`/`query` API。

### 23.4 依赖安全

- 不引入未经审计的第三方包；新增依赖需说明用途和替代方案。
- 定期运行 `npm audit`；高危漏洞在下一个迭代修复。
- 锁定 `package-lock.json`；CI 使用 `npm ci` 安装。

## 24. 国际化准备

当前项目为中文单语言，但代码组织应为未来国际化预留空间。

### 24.1 当前规则

- UI 文案统一使用简体中文；标点使用中文标点（句号"。"、逗号"，"）。
- 不在模板中拼接字符串表达复数或条件语句；使用完整的条件渲染。
- 日期时间显示使用 `dayjs` + `zh-cn` locale；数字使用 `toLocaleString('zh-CN')`。
- 错误提示、空状态、按钮文案写在组件内或统一的文案常量文件中，不散落在逻辑代码中。

### 24.2 未来迁移预留

- 新增页面时，将用户可见文案集中到组件顶部的 `const labels = { ... }` 或独立文案文件。
- 不在 JS 逻辑中硬编码含语义的字符串比较（如 `if (status === '成功')`）；使用枚举或常量。
- 布局避免固定宽度容纳中文；英文通常更长，预留弹性空间。

## 25. 浏览器兼容与运行环境

### 25.1 支持矩阵

| 浏览器 | 最低版本 |
| --- | --- |
| Chrome / Edge | 最近 2 个大版本 |
| Firefox | 最近 2 个大版本 |
| Safari | 最近 2 个大版本 |
| 移动端 Safari / Chrome | 最近 2 个大版本 |

- 不支持 IE 11。
- 使用 `caniuse` 确认 API 可用性；需要 polyfill 时在 `vite.config.ts` 中配置。
- CSS 特性（`backdrop-filter`、`container query`）需要 `@supports` 回退。

### 25.2 运行环境假设

- 最小视口宽度：`375px`（iPhone SE）。
- 最小屏幕分辨率：`1280×720`（桌面端）。
- 网络环境：支持弱网（3G）下的基本可用性；超时后提供重试。
- 不假设用户启用了 JavaScript 以外的插件（Flash、Java Applet）。

## 26. 错误边界与全局异常

### 26.1 Vue 错误处理

- `app.config.errorHandler` 捕获未处理的组件错误；记录到控制台并显示用户友好的全局提示。
- 关键页面（仪表盘、任务列表）使用 `onErrorCaptured` 阻止错误冒泡导致整页白屏。
- 路由级错误（chunk 加载失败）：显示"页面加载失败"+ 重试按钮，不白屏。

### 26.2 全局异常 UI

| 场景 | UI 表达 |
| --- | --- |
| 路由 chunk 加载失败 | 全屏 `NResult` + "重新加载"按钮 |
| 未捕获 Promise rejection | `useMessage().error('操作失败，请重试')` |
| WebSocket 全部断开 | 顶部 `NAlert type="warning"` 横幅 + 重连按钮 |
| 后端完全不可达 | 全屏 `NResult status="error"` + 重试 + 联系管理员 |

### 26.3 日志与监控

- 生产环境错误通过 `window.onerror` + `unhandledrejection` 上报（如接入 Sentry）。
- 开发环境错误在控制台输出完整堆栈；生产环境不暴露堆栈给用户。
- 关键操作（任务提交、文件上传、支付）记录操作日志（时间、用户、操作、结果）。

## 27. 路由与权限控制

### 27.1 路由组织

- 路由定义在 `frontend/src/router/index.ts`；按功能域拆分路由数组。
- 所有业务路由使用懒加载：`component: () => import('@/views/...')`。
- 路由 `meta` 字段携带：`title`（页面标题）、`requiresAuth`（是否需要登录）、`roles`（允许角色）。
- 页面标题在 `router.afterEach` 中统一设置为 `{title} - OmicHub`。

### 27.2 导航守卫

- 全局前置守卫：未登录访问 `requiresAuth` 路由 → 重定向 `/login?redirect=...`。
- 角色守卫：无权限 → 显示 403 页面，不重定向（避免循环）。
- 路由切换时取消上一个页面的未完成请求（通过路由级 `AbortController`）。

### 27.3 权限 UI

- 无权限的菜单项：隐藏或 `disabled` + Tooltip 说明原因。
- 无权限的操作按钮：`disabled` + Tooltip"需要管理员权限"。
- 权限变更后（如被移除角色）：下次 API 返回 403 时刷新权限列表并更新 UI。
- 不使用前端路由隐藏作为唯一安全措施；后端必须同步校验。

## 28. 通知与消息系统

### 28.1 消息层级

| 层级 | 工具 | 场景 | 持续时间 |
| --- | --- | --- | --- |
| 轻量反馈 | `useMessage()` | 操作成功/失败、复制完成 | 3s 自动消失 |
| 重要通知 | `useNotification()` | 任务完成、系统公告、权限变更 | 手动关闭 |
| 阻塞确认 | `useDialog()` / `NModal` | 破坏性操作确认、表单未保存离开 | 用户操作后关闭 |
| 持久状态 | `NAlert` / `NResult` | 后端不可达、权限不足、功能降级 | 条件恢复后消失 |

### 28.2 通知中心

- 使用 `useNotificationStore` 管理未读通知；顶栏铃铛图标显示未读数。
- 通知列表按时间倒序；支持标记已读、全部已读、按类型筛选。
- 实时通知通过 WebSocket 推送；离线期间的通知在登录后拉取。
- 通知点击跳转到对应页面/任务详情。

### 28.3 规则

- 同一操作不重复弹出相同消息（去重或节流）。
- 批量操作结果汇总为一条消息（"成功 3 项，失败 1 项"），不逐条弹出。
- 错误消息必须包含可操作的下一步（重试、联系管理员、查看日志），不只说"出错了"。

## 29. 打印与导出

### 29.1 打印样式

- 需要打印的页面（报告、分析结果）提供 `@media print` 样式：隐藏导航、侧栏、操作按钮；卡片去阴影和圆角。
- 图表打印前调用 `chart.getDataURL()` 转为静态图片，避免打印空白 canvas。
- 分页使用 `page-break-inside: avoid` 防止卡片被截断。

### 29.2 数据导出

- 表格数据导出为 CSV/Excel：由后端生成文件，前端触发下载。
- 图表导出为 PNG/SVG：使用 ECharts `getDataURL` 或 Plotly `toImage`。
- 分析报告导出为 PDF：由后端渲染，前端显示生成进度。
- 导出按钮使用 `:loading` 表示生成中；大文件导出提示预计时间。

## 30. 长任务与工作流监控

### 30.1 任务生命周期 UI

| 任务状态 | UI 表达 |
| --- | --- |
| `pending` / `queued` | `NTag type="warning"` + "排队中" + 队列位置（如可知） |
| `running` | `NTag type="info"` + `NProgress`（百分比或不确定态） |
| `success` | `NTag type="success"` + 查看结果按钮 |
| `failed` | `NTag type="error"` + 查看日志 + 重试按钮 |
| `cancelled` | `NTag type="default"` + "已取消" |

### 30.2 进度反馈

- 短任务（< 10s）：按钮 `loading` + 禁用，不跳转。
- 中等任务（10s – 2min）：页面内进度条 + 状态文字。
- 长任务（> 2min）：提交后跳转任务列表或显示"已提交，可在任务中心查看"；通过 WebSocket 推送进度。
- 多步骤工作流：显示步骤列表（`NSteps`），当前步骤高亮，已完成步骤可展开查看日志。

### 30.3 任务操作

- 运行中的任务提供"取消"按钮（`NPopconfirm` 确认）。
- 失败任务提供"重试"（重新提交相同参数）和"查看日志"。
- 任务列表支持按状态筛选、按时间排序、关键词搜索。
- 任务结果页提供"重新运行"（预填参数到表单）和"下载结果"。

## 31. 叠层、装饰覆盖层与定位选择器规范

许多页面/组件会在内容之上或之后叠加**装饰覆盖层**：聊天背景光晕、全息/粒子装饰、点阵网格、水印、渐变光斑等。这类层必须是"出流（out-of-flow）"的纯装饰，**绝不能参与布局**。下列为强制项；违反会直接导致布局塌陷（顶栏被顶到视口中部、出现整块空白、装饰残影错位等）。

### 31.1 装饰覆盖层契约

- 装饰层根元素必须 `position: absolute`（或 `fixed`），并加 `pointer-events: none` 与 `aria-hidden="true"`，赋低 `z-index`（通常 `0`）。
- 其定位锚点（最近的 `position: relative` 祖先）必须是布局容器本身；装饰层**不得**是 flex/grid 容器里"会被排布"的 in-flow 子项。
- 装饰层组件应与 `header`/`body`/`footer` 等内容层**平级**作为容器直接子节点，仅靠定位与 `z-index` 区分层级，**不靠**文档流顺序。

### 31.2 禁止用通配/过宽选择器抬升内容层（核心反模式）

- **禁止**用 `.container > *`、`.container > div`、漏网式 `:not(...)` 等**过宽选择器**统一设置会影响布局或层叠的属性：`position`、`z-index`、`display`、`margin`、`flex` 等。
  - 原因：它会一并命中装饰覆盖层，把 `absolute` 改成 `relative`，将装饰层拉回文档流，撑出空白并把后续内容（如顶栏）顶离原位。
  - **Vue scoped 不能挡住它**：`.parent > *` 会被编译成 `.parent > *[data-v-xxx]`，而子组件根节点会带上**父级** scope id，因此子组件的装饰根节点同样被命中。不要以为 scoped 样式能隔离。
- **正确做法**：只把"真正的内容层"按**类名**显式抬升，让装饰层保留自己的 `absolute + z-index:0`，自然落在内容之下、容器背景之上。

```css
/* 错误：通配命中装饰层，把 absolute 拉成 relative，布局塌陷 */
.agent-sandbox > * { position: relative; z-index: 1; }

/* 正确：逐个列举内容层；新增内容层时同步加入此列表 */
.sandbox-body,
.sandbox-input { position: relative; z-index: 1; }
.sandbox-header { position: sticky; z-index: 10; } /* sticky 顶栏自带更高层级，不必并入通配 */
```

- 抬升内容层时**逐个列举**类名；新增内容层时同步加入该列表，**不要**改用通配"图省事"。

### 31.3 叠层顺序约定

- 容器 `position: relative` 建立定位上下文；其 `::before`/`::after` 装饰（点阵、渐变）与装饰覆盖层组件同处 `z-index: 0` 层。
- 内容层（header / body / footer / 输入区）`z-index: 1`；sticky 顶栏可用 `z-index: 10`。
- 弹层、抽屉、菜单走全局层级（见 §5.6、§28），不在容器局部叠层里争抢。
- 内容层背景应允许装饰透出：消息区/内容区背景保持透明或半透明，使底层装饰可见；顶栏/输入区可用半透明 + `backdrop-filter` 适度遮挡。

### 31.4 案例：傻妞（shania）全息背景导致顶栏塌陷

- **现象**：AI 助手 `@傻妞` 选中该 agent 后，页面顶部出现整块空白，agent 顶栏被挤到视口中部，左上角出现淡色圆角残影。
- **根因**：`AgentSandbox.vue` 曾用 `.agent-sandbox > * { position: relative; z-index: 1; }` 抬升内容层，误伤 `ShaniaChatBackground.vue`（仅 `agent.id === 'shania'` 渲染、本应 `position: absolute` 的右下角全息装饰层），使其变成 in-flow 的 `300×400` 块，撑高顶部并把 header 顶下；淡色残影即被挤到左上角的手机框/光环。
- **修复**：删除通配规则，改为 `.sandbox-body`、`.sandbox-input` 显式 `position: relative; z-index: 1`（header 维持 `sticky + z-index: 10`），装饰层回归绝对定位。
- **教训**：任何"仅某个 agent / 路由 / 开关下才渲染"的**条件装饰层**，最容易在通配选择器下暴露问题；新增此类层时务必确认它不会被父级过宽选择器命中，并在该条件下肉眼/截图验收布局。

### 31.5 样式改动的构建与上线校验

- 组件样式会被 Vite **代码分包**到路由 chunk（如 AI 助手页落在 `AIChatView-<hash>.css`），**不在主 `index-<hash>.css`**。验收时不要只 grep 主包，更不能因主包没变就判定"没生效"。
- 不要以"构建成功"为验收终点：必须在**构建产物或 nginx 实际响应**里 grep 到你改动的选择器/属性，确认改动真的编进去了。
  - 定位 chunk：`grep -rl '<改动类名>' frontend/dist/assets`。
  - 校验服务响应：`curl -s --compressed http://localhost:<port>/assets/<chunk>.css` 后 grep；务必带 `--compressed`（否则拿到 gzip 字节，grep 不到），路径务必带 `/assets/` 前缀（漏写会命中 404/回退页，得到误导性的极短响应）。
- 浏览器侧需**硬刷新**（Ctrl/Cmd + Shift + R）丢弃旧 `index.html` 与旧 chunk 缓存，否则看不到改动。
- 重发前端时优先"构建到临时目录 + `rsync -a --delete tmp/ dist/`"：保留 `dist` 目录 inode，规避 nginx bind mount 失效，且构建失败时不会清空线上产物（运维细节见 nginx bind mount 相关说明）。

## 32. Hero 背景动画系统（OmicBackgroundAnimation）

> 权威实现：`frontend/src/components/OmicBackgroundAnimation.vue`（canvas 容器 + 生命周期）、`frontend/src/utils/animationLibrary.ts`（动画引擎，IIFE 副作用脚本，挂载 `window.initHeroAnimation` / `window.initLoginAnimation`）、`frontend/src/views/HomeView.vue`（hero 区接入点）。Hero 与登录页共用同一引擎，仅 `context` 不同导致密度/速度/不透明度档位不同。本节为该系统的设计基线；新增或调整模式必须同步本文件。

### 32.1 三层叠加架构

Hero 横幅（`HomeView.vue` 的 `<section class="hero">`）背景不是位图，而是自下而上三层叠加：

| 层 | 实现 | 是否持续 | 权威位置 |
| --- | --- | --- | --- |
| ① 渐变底色 | CSS `linear-gradient(135deg, #165DFF → #6B8DD6 → #8E54E9)` | 静态 | `HomeView.vue` `.hero` |
| ② 入场动效 | CSS `@keyframes fadeInUp`，0.5s 一次性淡入上滑 | 否 | `HomeView.vue` `.animate-fade-in-up` + `global.css` |
| ③ Canvas 动画 | JS Canvas 2D + `requestAnimationFrame`，19 模式随机命中其一 + 共享极光氛围层 | 是 | `OmicBackgroundAnimation.vue` → `animationLibrary.ts` |

Canvas 层必须遵守 §31 的装饰覆盖层契约：`position:absolute; inset:0; pointer-events:none; z-index:0`，并 `aria-hidden`，置于 `.hero-content` 之下、渐变底色之上；**严禁**被父级 `.hero > *` 之类通配选择器命中（否则 `absolute` 被拉成 `relative`，撑高 hero 并顶坏布局，见 §31.2 / §31.4）。内容层只允许按**类名**显式抬升 `z-index`。

引擎对外契约不变：组件 `onMounted` 动态 `import('@/utils/animationLibrary')`，按 `context` 取 `window.initHeroAnimation(canvas)`，返回的 cleanup 在 `onUnmounted` 调用；引擎内部监听 `resize` 与 `visibilitychange`（切后台停 rAF、回前台续），cleanup 一并解绑，杜绝句柄/内存泄漏。Hero 档位 `opacity:0.82 / density:5000 / speed:0.8 / glow:true`，登录页档位更淡更慢（`0.3 / 10000 / 0.6`）。渐变太抢眼，动画既要"压得住被看见"，又必须**克制、舒缓**——`speed` 取慢档、`opacity` 留余量，避免频率过高或过亮而喧宾夺主、抢标题与按钮（见 §32.3 频率克制原则）。整体转速另由主循环 **60fps 封顶**兜底（见 §32.3 原则 5），与 `speed` 解耦——保证高刷屏不会比 60Hz 转得更快。

### 32.2 模式目录（19 种，互斥随机命中）

引擎在 `MODES` 数组里登记全部模式，每次加载 `Math.random()` 命中**一种**运行（不叠加），并 `console.log('[Animation:<ctx>] Mode:', ...)` 便于核对。模式分四类语义，命名贴合「星尘 + 基因组学」：

| # | key | 类别 | 视觉描述 |
| --- | --- | --- | --- |
| 1 | `particles` | 粒子 | 漂移圆点 + 邻近连线（星座/神经网络感）+ 呼吸 + 辉光 |
| 2 | `stars` | 粒子 | 上飘星点 + 闪烁 + 大星四向/斜向星芒 |
| 3 | `aura` | 几何环 | 中心光源 + 向外扩散同心环 + 放射射线 |
| 4 | `orbitals` | 几何环 | 倾斜透视椭圆轨道 + 轨道亮点 + 中心恒星 |
| 5 | `meteor` | 流线 | 斜向流星 + 渐变尾迹 + 发光头部 |
| 6 | `ripple` | 几何环 | 多点三层同心回声涟漪 |
| 7 | `firefly` | 粒子 | 暖黄漫游明灭光点（与冷底形成冷暖对比） |
| 8 | `matrix` | 数据 | 0/1 字符列下落 + 头部光点 |
| 9 | `bubbles` | 流线 | 半透明气泡上浮 + 摇摆 + 玻璃高光 |
| 10 | `dna` | 生物语义 | 多列双螺旋：正弦相位驱动核苷酸节点 + 碱基对横档，按深度调亮度制造立体旋转 |
| 11 | `constellation` | 数据 | 慢漂移节点 + 距离阈值动态连线（数据节点网络） |
| 12 | `flowfield` | 流线 | 伪 Perlin 风场驱动微粒描迹，带生命周期淡入淡出 |
| 13 | `shards` | 几何 | 漂浮旋转多边形碎片 + 边缘棱光 shimmer（晶体/棱镜感） |
| 14 | `hexgrid` | 几何 | 六边形蜂窝网格相位呼吸波 + 高相位点辉光（测序芯片感） |
| 15 | `waves` | 信号 | 多条叠加正弦波带 + 波峰亮点（电泳/信号图谱感） |
| 16 | `gravity` | 轨道 | 中心吸积核 + 开普勒近快远慢椭圆轨道粒子 |
| 17 | `datastream` | 数据 | 上升渐变光柱 + 柱顶光点（上传/测序产出均衡器感） |
| 18 | `aurora` | 氛围 | 水平漂移多层极光彩带（`lighter` 合成） |
| 19 | `nebula` | 氛围 | 漂移柔光星云团（`lighter` 合成）+ 深空闪烁星尘 |

新增模式必须：① 实现 `init<Mode>()` 返回纯数据 state 与 `draw<Mode>(state)` 每帧绘制两函数；② 在 `MODES` 数组、`initForMode`、`drawForMode` 三处分派登记（漏任一处会落到 `default` 即 `particles`）；③ 颜色沿用软蓝白/品牌冷色族（暖色仅 `firefly` 作冷暖点缀），强度乘以 `CONFIG.opacity`、速度乘以 `CONFIG.speed`，发光受 `CONFIG.glow` 门控，保证 Hero/登录两档都成立；④ 每帧先 `ctx.clearRect`，合成模式（`lighter` 等）必须 `ctx.save()/restore()` 包裹，避免污染后续绘制的描边/文字。

### 32.3 观感强化设计（"更强的观感"如何落地）

v5 在 19 模式之上统一引入三件强化手段，使背景从"平淡描边圆"升级为"有体积、有呼吸、有光源"的活背景，且不依赖任何第三方粒子库、SVG 或视频：

1. **共享极光氛围层 `drawAtmosphere`**：2~3 团品牌色（蓝/靛/紫/青）大半径径向渐变，`globalCompositeOperation='lighter'` 叠加、缓慢漂移 + 正弦呼吸，置于每个模式绘制**之下**。这是"渐变底色会呼吸"的来源，也是观感提升的最大单一杠杆。Hero 峰值不透明度（约 `0.072`）高于登录页（约 `0.03`）但整体偏淡，漂移/呼吸取慢速，避免登录页过噪、也避免 Hero 背景抢戏。
2. **多停径向辉光 `glowDot`**：所有发光点统一改用它（内核亮、0.35 处衰减、外圈归零的三停径向渐变），替代旧版单色实心圆 + 单层光晕，粒子更通透、有体积；`CONFIG.glow` 为真时才放大辉光半径。
3. **中心光源/旧模式增强**：`aura`/`gravity` 增加中心辉光核作为"光源"；`stars` 大星补斜向星芒；`ripple` 改三层同心回声；`meteor`/`orbitals`/`matrix` 头部改用 `glowDot` 更亮。

调参守则：观感强弱优先调 `CONFIG` 档位与 `drawAtmosphere` 峰值，而非把单个模式的不透明度写死到刺眼；任何"更亮/更快"的改动都必须在蓝紫渐变上肉眼核对——目标是"压得住、看得见、不抢标题"，不是喧宾夺主。Hero 文案与按钮（见 §5.7）的对比度优先级永远高于背景动效。

4. **频率克制（与亮度同等重要）**：所有"会动"的自增（旋转、漂移、相位、呼吸、闪烁、风场推进等）必须乘以 `CONFIG.speed`，**禁止**写死与档位脱钩的常量自增——否则改 `speed` 调不出整体节奏，且容易出现个别模式过快、喧宾夺主。默认 Hero `speed:0.8` 是"舒缓环境动效"档：背景应像缓慢呼吸的星尘，而非抢眼的频闪。新增模式若引入相位/旋转/推进自增，一律 `* CONFIG.speed` 并以"慢一档"为起点核对。
5. **帧率归一（高刷屏不加速，与频率克制同等重要）**：所有 per-frame 自增都按 **60Hz** 调参，主循环用累加器把绘制**封顶在 ~60fps**（`frameAcc += dt; if (frameAcc < 1000/60) return; frameAcc %= 1000/60`，余量进位、长期不漂移）。这是必须的：若不限速，120/144Hz 屏上 rAF 回调翻倍，旋转/漂移/闪烁会比设计值快 2–2.4 倍，肉眼即「转太快、频闪」，而 60Hz 开发机上却完全看不出来——这是 Hero「旋转太快」投诉的典型根因。**禁止**用「调小 `CONFIG.speed`」去补偿高刷屏：那会让 60Hz 屏过慢，帧率问题只能在主循环解决。带整体自旋/轨道的模式（如 `orbitals`、`gravity`），旋转/角速度常量本身也要取舒缓档，与封顶叠加才得到「星尘缓缓流转」而非「转动的风车」；历史上曾有 `spiral` 三旋臂模式，因即使取舒缓档体感仍偏快，已整体移除。

### 32.4 可访问性与性能

- **`prefers-reduced-motion: reduce`**：引擎在初始化时读取该媒体查询；命中则**只绘制一帧静态画面**（氛围层 + 当前模式各一帧），**不启动 `requestAnimationFrame` 循环**，亦不响应 `visibilitychange` 续播。落实 §6.3「装饰循环在减少动态下停止」与 §1 原则 6。新增模式不得在 reduce 路径下引入持续动画。
- **性能**：单模式 + 单氛围层，粒子数由 `面积 / density` 约束，连线类（`particles`/`constellation`）有最大连接数/双重循环上限；切后台 `cancelAnimationFrame`，组件卸载 cleanup 解绑 `resize`/`visibilitychange`。禁止为观感引入逐帧 `filter: blur` 或超大阴影等昂贵操作——辉光一律用径向渐变模拟。
- **帧率封顶**：主循环以累加器把绘制封顶在 ~60fps（见 §32.3 原则 5），高刷屏不加倍转速与功耗，且与 60Hz 体感一致；切后台 `cancelAnimationFrame`、回前台续播时大 `dt` 只补一帧、不突进。
- **DPR**：`resize` 按 `devicePixelRatio` 设置画布物理尺寸并 `setTransform` 归一，保证高分屏清晰；改 `setTransform` 参数时务必保留五/六参形式正确。

### 32.5 验收清单（在 §10 通用清单之上补充）

- [ ] `animationLibrary.ts` 的 `MODES` 长度与 `initForMode`/`drawForMode` 分支数一致（当前 19），无遗漏导致静默回退到 `particles`。
- [ ] 新增/调整模式在 Hero 与登录两档（不透明度/速度差异）下均可见且不刺眼，蓝紫底上肉眼核对。
- [ ] 所有发光点走 `glowDot`；使用 `lighter` 等合成模式的绘制已用 `save()/restore()` 隔离。
- [ ] `prefers-reduced-motion: reduce` 下背景为静态单帧、无持续运动（可临时在系统设置或 DevTools 模拟验证）。
- [ ] Canvas 装饰层仍满足 §31：`absolute + pointer-events:none + aria-hidden + z-index:0`，未被任何通配选择器命中；hero 布局未因装饰层塌陷。
- [ ] `npm run type-check` 与 `npm run build` 通过；按 §31.5 在构建产物/响应中核对，硬刷新多刷几次以覆盖随机模式。
- [ ] 在 ≥120Hz 屏（或 DevTools 模拟高刷新率）下核对 Hero 旋转/漂移速度与 60Hz 一致，无「转太快」；主循环仍为单一 rAF 链、切后台停、回前台不突进。

### 32.6 实现方式与代码模板（how-to）

> §32.1–32.5 讲"是什么/为什么"，本节讲"怎么写"。下列片段摘自权威实现，可直接照抄扩展；改引擎时以 `animationLibrary.ts` 实际代码为准，本节目的是让任何人无需通读 800 行也能安全新增/调整一个模式。

**① 容器组件：副作用引擎 + 生命周期。** 引擎是 IIFE 副作用脚本，`import` 即挂载 `window` 方法；组件只管拿 canvas、按 `context` 选入口、卸载时 cleanup。`context="hero"` 走 `initHeroAnimation`，登录页走 `initLoginAnimation`，二者共用同一引擎、仅档位不同。

```vue
<!-- OmicBackgroundAnimation.vue -->
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
const props = defineProps<{ context: 'hero' | 'login' }>()
const canvasRef = ref<HTMLCanvasElement | null>(null)
let cleanup: (() => void) | null = null

onMounted(async () => {
  await import('@/utils/animationLibrary')          // 副作用脚本，执行即挂 window.*
  if (!canvasRef.value) return
  const fn = props.context === 'hero'
    ? (window as any).initHeroAnimation
    : (window as any).initLoginAnimation
  const destroy = fn?.(canvasRef.value)
  if (destroy) cleanup = destroy
})
onUnmounted(() => cleanup?.())
</script>

<template>
  <canvas ref="canvasRef" class="omic-canvas" aria-hidden="true" />
</template>

<style scoped>
/* §31 装饰层契约：出流 + 不挡点击 + 低层级，绝不可被父级通配选择器命中 */
.omic-canvas { position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 0; }
</style>
```

接入点（`HomeView.vue`）：`<section class="hero animate-fade-in-up">` 设 `position:relative; overflow:hidden` 与渐变底色，首子节点放 `<OmicBackgroundAnimation context="hero" />`，`.hero-content` 用**类名**显式 `position:relative; z-index:2` 抬到 canvas 之上。

**② 引擎骨架：档位 / DPR / 减少动效 / 随机命中 / 主循环。** `CONFIG` 决定 Hero 与登录两套强度；`resize` 按 `devicePixelRatio` 设物理尺寸并 `setTransform` 归一（**必须 6 参**，传 5 参 vue-tsc 报 TS2575）；`reduceMotion` 命中只画一帧、不启 rAF。

```ts
export {}
;(function () {
  ;(window as any).initHeroAnimation = (c: HTMLCanvasElement) => initAnimation(c, 'hero')
  ;(window as any).initLoginAnimation = (c: HTMLCanvasElement) => initAnimation(c, 'login')

  function initAnimation(canvas: HTMLCanvasElement, context: 'hero' | 'login') {
    const ctx = canvas.getContext('2d')
    if (!ctx) return () => {}
    let w = 0, h = 0, dpr = 1, animationId: number | null = null

    const CONFIG = {
      hero:  { opacity: 0.82, density: 5000, speed: 0.8, glow: true }, // 压得住但克制：慢档+留余量，不喧宾夺主
      login: { opacity: 0.3, density: 10000, speed: 0.6, glow: true },
    }[context]

    function resize() {
      const rect = canvas.parentElement?.getBoundingClientRect()
      if (!rect) return
      dpr = window.devicePixelRatio || 1
      canvas.width = rect.width * dpr; canvas.height = rect.height * dpr
      w = rect.width; h = rect.height
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)        // 6 参，勿省末参
    }
    resize(); window.addEventListener('resize', resize)

    const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches
    const MODES = ['particles', /* …共 19 个 key… */ 'nebula']
    const currentMode = MODES[Math.floor(Math.random() * MODES.length)]  // 互斥随机命中

    let state: any = null
    const tick = () => { state ||= initForMode(); drawAtmosphere(); drawForMode(state) }
    // 主循环封顶 ~60fps：per-frame 增量按 60Hz 调参，高刷屏不限速会快 2–2.4 倍（见 §32.3 原则 5）
    let lastTs = 0, frameAcc = 0
    const FRAME_MS = 1000 / 60
    const animate = (ts: number = performance.now()) => {
      animationId = requestAnimationFrame(animate)
      if (!lastTs) lastTs = ts
      frameAcc += ts - lastTs; lastTs = ts
      if (frameAcc < FRAME_MS) return
      frameAcc %= FRAME_MS        // 余量进位；切回前台的大 dt 只补一帧、不突进
      tick()
    }

    if (reduceMotion) { state = initForMode(); drawAtmosphere(); drawForMode(state) } // 静态单帧
    else animate()

    const onVis = () => { if (reduceMotion) return
      document.hidden ? (animationId && cancelAnimationFrame(animationId)) : animate() }
    document.addEventListener('visibilitychange', onVis)

    return () => { animationId && cancelAnimationFrame(animationId)       // cleanup
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', onVis) }
  }
})()
```

**③ 新增一个模式的最小模板。** 每个模式 = `initX()` 返回**纯数据 state** + `drawX(state)` 每帧绘制；强度乘 `CONFIG.opacity`、速度乘 `CONFIG.speed`、发光受 `CONFIG.glow` 门控，保证两档都成立；每帧先 `clearRect`。登记**三处缺一不可**：`MODES` 数组、`initForMode` 的 switch、`drawForMode` 的 switch（漏任一处静默回退 `particles`）。

```ts
// —— 模式实现：以 flowfield（风场微粒描迹）为例 ——
function initFlowfield() {
  const pts: any[] = []
  const count = Math.floor((w * h) / (CONFIG.density * 0.9))   // 粒子数受面积/密度约束
  const spawn = () => ({ x: Math.random() * w, y: Math.random() * h,
    life: 0, maxLife: 80 + Math.random() * 120, px: 0, py: 0 })
  for (let i = 0; i < count; i++) { const p = spawn(); p.px = p.x; p.py = p.y; pts.push(p) }
  return { pts, t: 0 }
}
function drawFlowfield(state: any) {
  ctx.clearRect(0, 0, w, h)                                    // 每帧清空
  state.t += 0.0008 * CONFIG.speed                             // 速度乘档位（舒缓）
  const scale = 0.0042
  state.pts.forEach((p: any) => {
    const ang = Math.sin(p.x * scale + state.t * 60) * 1.8
              + Math.cos(p.y * scale - state.t * 40) * 1.8     // 伪 Perlin 风场
    p.px = p.x; p.py = p.y
    p.x += Math.cos(ang) * 1.1 * CONFIG.speed
    p.y += Math.sin(ang) * 1.1 * CONFIG.speed
    if (++p.life > p.maxLife || p.x < 0 || p.x > w || p.y < 0 || p.y > h)
      Object.assign(p, { x: Math.random() * w, y: Math.random() * h, life: 0 })
    const fade = Math.sin((p.life / p.maxLife) * Math.PI)
    ctx.strokeStyle = `rgba(195,210,255,${fade * 0.28 * CONFIG.opacity})`  // 强度乘 opacity
    ctx.lineWidth = 0.8; ctx.beginPath(); ctx.moveTo(p.px, p.py); ctx.lineTo(p.x, p.y); ctx.stroke()
    glowDot(p.x, p.y, 1.6, fade * 0.5 * CONFIG.opacity)
  })
}
// —— 登记三处 ——
// MODES:  [... , 'flowfield']
// initForMode:  case 'flowfield': return initFlowfield()
// drawForMode:  case 'flowfield': return drawFlowfield(s)
```

**④ 观感两助手（直接复用，勿另造）。** `glowDot` 用三停径向渐变画"有体积"的发光点，替代单色实心圆；`drawAtmosphere` 在每个模式之下铺一层品牌色漂移辉光（`lighter` 合成，`save/restore` 隔离），是"背景会呼吸"的来源。合成模式（`lighter` 等）**必须** `save()/restore()` 包裹，否则污染后续描边/文字。

```ts
function glowDot(x: number, y: number, r: number, a: number,
  core = '225,230,255', halo = '170,185,255') {                 // 多停径向辉光
  if (a <= 0.001 || r <= 0) return
  const g = ctx.createRadialGradient(x, y, 0, x, y, r)
  g.addColorStop(0, `rgba(${core},${Math.min(1, a * 1.15)})`)
  g.addColorStop(0.35, `rgba(${core},${a * 0.55})`)
  g.addColorStop(1, `rgba(${halo},0)`)
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill()
}
function drawAtmosphere() {                                     // 共享氛围层，置于模式之下
  ctx.save(); ctx.globalCompositeOperation = 'lighter'
  /* 2~3 团品牌色大半径径向渐变：缓慢漂移 + sin 呼吸，峰值 hero 0.072 / login 0.03，乘 CONFIG.opacity（偏淡，避免抢戏） */
  ctx.restore()
}
```

**⑤ 调色与强度守则。** 颜色沿用软蓝白/品牌冷色族（`rgba(200,210,255,α)` 系），暖色仅 `firefly` 作冷暖点缀；所有 alpha 一律 `* CONFIG.opacity`，禁止写死刺眼值。观感强弱优先调 `CONFIG` 档位与 `drawAtmosphere` 峰值，而不是把单模式不透明度拉满——目标是"压得住、看得见、不抢标题"，Hero 文案与按钮对比度（§5.7）永远优先于背景动效。**频率同样要克制**：任何旋转/漂移/相位/呼吸/闪烁自增都必须 `* CONFIG.speed`，勿写死常量自增（否则个别模式会过快、喧宾夺主，且 `speed` 调不出整体节奏）；新增模式以"慢一档"为起点核对。禁止用逐帧 `filter: blur` 或大阴影堆观感，辉光一律径向渐变模拟。

**⑥ 调试与验收。** 随机命中使单刷难覆盖全部模式，临时在 `initAnimation` 内把 `currentMode` 改成读 `new URLSearchParams(location.search).get('bgmode') || 随机` 即可用 `?bgmode=dna` 逐一目检（**调试用，勿提交**，或加 `import.meta.env.DEV` 守卫）。验收：`cd frontend && npm run type-check && npm run build`；按 §31.5 grep 产物——新模式 **key 字符串**会保留可核对，但 `drawAtmosphere`/`glowDot` 等**局部函数名会被压缩混淆、grep 不到属正常**，勿误判"没生效"；上线硬刷新多次，并注意 nginx bind mount 的 dist inode（重发勿 `rm -rf dist`）。

## 33. 设计质感基线：做出"被设计过"而非"被生成出来"的界面

> 本节是质量上限（ceiling）规则，与 §1 的"平静、清晰、克制"下限（floor）规则**叠加生效，不互相取消**。克制指"不为装饰而装饰、不为炫技而加动效"；质感指"每一处留白、字号、圆角、节奏都像是有意为之，而非框架/模型默认值"。一个界面可以同时是克制的与精致的——单调、对称、毫无特征的"白卡片 + 灰文字"不是克制，而是**没设计**。新增或改版任何页面/组件时，先对照 §33.1 自查是否落入"AI 默认"，再按 §33.2 落实数据表格/卡片的具体样式契约。

### 33.1 规避"AI 默认"清单（设计哲学）

把每个交付物当作作品集产物：用户会截图、会对比、会注意到细节。下列是模型/脚手架最容易产出的"通用模板味"，**应主动规避**，用本仓库已有的设计系统去反制：

1. **纯白、无氛围的背景** → 用 §3.2 令牌的分层表面（`--neutral-bg` 页面 / `--neutral-card` 卡片 / 玻璃导航），并在 Hero、登录等场景接入 §32 的活的画布氛围层；让背景有"被设计过"的层次而非一张白纸。
2. **三列等宽 hero / 卡片网格** → 用主次分明的非对称布局、`grid-template-columns` 的混合轨道（如仪表盘 `320px 1fr`），让视觉重心明确。
3. **处处相同的间距** → 严格走 §3.3 的间距阶梯，但**用节奏而非均分**：组内紧、组间松，区块用 24/32px、卡片内用 8/12/16px，制造信息分组。
4. **统一的圆角** → 按 §3.3 圆角层级区分控件 / 卡片 / 面板 / 胶囊，不要全场一个值。
5. **通用无衬线、无层级** → 用 §3.3 字体栈与文本层级（字号 + 字重 + 行高 + 色阶共同建立层级，大标题负字距）；避免"全是 14px 灰字"。
6. **对称、空旷、无特征的留白** → 留白要服务于分组与呼吸，配合 §3.2 的辅助色阶、§5.2 的可选卡片状态线、§5.7 的浮起按钮，让空白处也有意图。

**与克制原则的调和（重要）**：§33.1 不是鼓励堆砌装饰或加 gratuitous 动效。"丰富"必须**成系统、有目的**——氛围层、状态线、玻璃材质都已在 §31/§32/§5 中受 `prefers-reduced-motion` / `prefers-reduced-transparency` 约束、受对比度与可访问性约束。判定标准：去掉某处装饰/层次后，界面是否变得更"通用、更默认"？是，则它是有价值的设计；否，则它是噪声，删掉。可读性、对比度、键盘可达性永远优先于氛围与装饰。

### 33.2 数据表格与卡片：具体样式契约（dashboard 样板）

> 权威实现：`frontend/src/views/DashboardView.vue`（最近任务 / 最近 BLAST 任务两表与卡片）、`frontend/src/components/task/TaskTable.vue`（任务中心整表）、`frontend/src/components/dashboard/*`（仪表盘各面板）。下列为反复踩坑后沉淀的硬规则，新增/修改任何 `NDataTable` 或仪表盘卡片时遵守。

**① 进度条百分比不换行（`NProgress` line，indicator 在外侧）。** "100 %" 折成两行的**根因不是指示器文字换行**，而是条容器 `.n-progress-graph` 为 `flex:1` 且默认 `min-width:auto` 不肯收缩，把 `white-space:nowrap` 的指示器整块挤到第二行。只给指示器加 `nowrap` 无效。正确修复（scoped 深穿透）：

```css
/* 让进度条可在 flex 行内收缩，使百分比与条同行；指示器 nowrap 兜底 */
.recent-table :deep(.n-progress-graph) { min-width: 0; }
.recent-table :deep(.n-progress-graph-line-indicator) { white-space: nowrap; }
```

注意 naive-ui 真实类名是 `n-progress-graph` / `n-progress-graph-line-indicator`，**不是** `n-progress__indicator`（写错选择器会静默不生效，按 §31.5 在产物里 grep 确认）。

**② 进度尺度归一化（后端尺度可能不统一，前端必须容错）。** 进度字段在后端**尺度并不统一**：分析任务的下载路径写 0–1（`task.progress = 1.0`、`progress / 100.0`），富集 / arq 路径写 0–100（实测已完成任务库内即 `100.0`）；BLAST 的 progress 是 `int` 0–100。直接 `Math.round(progress * 100)` 会把已完成的 `100.0` 渲染成 **1000%**；直接当百分比又会让 0–1 的下载任务显示成 1%。统一用归一化函数渲染，分析与 BLAST 进度列都用它：

```ts
// >1 视为已是百分比，否则按 0–1 折算；两种尺度都对，且不依赖单一写死约定
function pct(value: number | null | undefined): number {
  const n = Number(value) || 0
  return Math.round(n > 1 ? n : n * 100)
}
```

彻底修复应在后端统一写入尺度（任选 0–1 或 0–100 其一）并刷历史数据；在此之前前端归一化是必须的兜底，**不要**移除。

**③ 列宽：全部固定 `width`，禁止"弹性列"吞宽度。** `NDataTable` 中带 `minWidth` 或无 `width` 的列是**弹性列**，会吸收容器全部剩余宽度。把任务名称 / 查询标题设成 `minWidth` 时，该列会 ballooning 到 ~900px，反过来把分析流程 / 状态 / 进度等挤窄、自身文字换行——这正是"其它列被压缩"的根因。规则：

- **每一列都给固定 `width`，不留弹性列**；长文本列（名称 / 标题）给一个克制的固定宽 + `ellipsis: { tooltip: true }` 兜底长内容。
- 把 `scroll-x` 设成**各列固定宽之和**（≈ 容器宽，如分析表 `970`、BLAST 表 `1020`）。这样表格按比例铺满整行，没有任何一列 ballooning，也没有列被挤压；列宽之和大于容器时退化为水平滚动，符合 §7.1。
- **短值/离散列居中**：所属用户、分析流程、数据库、Program、状态、操作等用列级 `align: 'center'`（naive-ui 会**同时居中对齐表头与表体**，不必再单独写表头 CSS）。
- **进度列不要居中**：进度条 + 百分比是从左到右的组合单元，居中会在条左侧留下随宽度变化的空白，显得错位；进度列保持左对齐，只靠 ① 解决换行。

**④ 真实数据，不展示裸 UUID/假数据。** 任何带"所属用户"列的表格，必须由后端回填真实 `username`，而非在前端展示 `user_id`（UUID）或用写死的 mock 行占位：

- 分析 `GET /api/v1/tasks` 的 `TaskResponse.username` 由 `TaskService.list_tasks` 经用户仓储按 `user_id` 回填（去重后查询，单用户列表只查一次）。
- BLAST 列表 `BlastTaskListItemDTO.user_id` / `username`：`list_user_tasks` 用 `outerjoin UserModel` 取 username，`list_all_tasks` 复用其既有 `UserModel` join（不要丢弃已 select 的 username）。
- 前端 `row.username || row.user_id` 仅作最后降级，**不是**设计预期。仪表板"最近任务"在迭代期曾用 mock 预览多用户混合，接口就绪后必须切回真实接口（按当前用户视角），空数据走 `NEmpty` 真实空态，不用假行填充。
- 操作列同理：查看/删除接真实接口（查看跳详情、删除走 `DELETE` 并局部刷新），后端未上线的能力（如"重新运行"）按终态 `disabled` + Tooltip"即将上线"诚实表达，**不要**用 `message.info('对接中')` 之类的假 toast 冒充可用。

**⑤ 卡片垂直节奏统一为 24px。** 仪表盘各区块（概览网格 / 快速开始 / 监控面板 / 最近任务 / 最近 BLAST）每个根 section 自带 `margin-bottom: 24px`，构成统一的 24px 垂直节奏。新增卡片 section 必须同样带 `margin-bottom: 24px`，**不要**让相邻卡片间距塌缩为 0（只写 `overflow:hidden` 而漏掉外边距是常见错误，会导致两张卡片贴在一起、与其它卡片间距不一致）。

### 33.3 验收清单（在 §10 通用清单之上补充）

- [ ] 进度/百分比/计数等派生数值是否经归一化或确定性公式渲染，在 0–1 与 0–100 两种数据尺度下都正确（无 1000% / 无 1% 误显）？
- [ ] `NProgress` 百分比是否单行显示（产物中 grep 到 `.n-progress-graph{min-width:0}` 与指示器 `nowrap`，类名拼写正确）？
- [ ] 数据表格是否**所有列固定 `width`、无弹性列**，且 `scroll-x` 等于列宽之和；长文本列有 `ellipsis` + Tooltip？
- [ ] 短值/离散列是否 `align:'center'`（表头+表体一致），进度列是否保持左对齐？
- [ ] 带"所属用户"的表格是否展示真实 `username`（后端回填），而非 UUID 或 mock；空数据是否走真实 `NEmpty`？
- [ ] 操作列是否接真实接口；未上线能力是否诚实 `disabled` + Tooltip，无假 toast？
- [ ] 仪表盘卡片 section 是否都带 `margin-bottom: 24px`，相邻卡片间距与其它卡片一致？
- [ ] 设计是否规避 §33.1 的"AI 默认"清单，在不破坏 §1 克制与可访问性的前提下具备品牌层次与辨识度？
