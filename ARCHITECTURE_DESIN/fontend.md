# CygnusX 前端设计系统与实现规范

> **用途**：这是 CygnusX 的前端视觉、交互和实现基线。新增页面、组件及样式改动必须以此文档和现有设计令牌为准。它同时可作为其它科学计算、数据平台或工作台类 Vue 项目的迁移参考。
>
> **使用方式**：先阅读“技术边界”和“页面配方”，再按“实施流程”和“验收清单”完成实现。业务组件只消费语义令牌与共享模式；新增全局规则时，必须同步更新本文件及相应源文件。

## 1. 设计目标与非协商原则

CygnusX 是面向生物信息学任务、数据资产与 AI 工作流的科学工作台。界面应传达**平静、清晰、可靠、可控**，而非追求装饰性。

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

### 3.3 Dark Mode Surface System

CygnusX 深色工作台使用五级 Surface 空间层级，替代“页面背景 + 卡片”的二级结构。所有深色页面、Dashboard、对话区域和浮层优先消费这些语义令牌，不在业务组件中重复写 hex 或 rgba 颜色。

#### 3.3.1 五级 Surface

| 层级 | 令牌 | 深色值 | 使用场景 | 约束 |
| --- | --- | --- | --- | --- |
| Surface Base | `--surface-base` | `#080B12` | `body`、页面背景、Dashboard 空白区域、主容器 | 禁止使用 `#000000` 作为页面底色。 |
| Surface Card | `--surface-card` | `#121824` | 普通信息卡、快捷入口、统计卡、图表主体 | 使用低存在感边框，不添加明显阴影。 |
| Surface Elevated | `--surface-elevated` | `#182033` | 系统状态、当前任务、AI 输出、图表标题区、重要信息 | 相比普通卡片更亮，可使用 `--border-default`。 |
| Surface Highlight | `--surface-highlight` | `#202A40` | `hover`、`active`、`selected` 等短时交互状态 | 不用于大面积常驻背景。选中态优先使用 `--border-focus`。 |
| Surface Glass | `--surface-glass` | `rgba(255,255,255,0.06)` | Header、Hero、Modal 等特殊结构区 | 搭配 `backdrop-filter: blur(16px)`；减少透明度时必须退化为不透明 Surface。 |

#### 3.3.2 Border 与文字层级

- `--border-subtle`（`rgba(255,255,255,0.06)`）用于普通卡片、分隔线和 Header 底边。
- `--border-default`（`rgba(255,255,255,0.10)`）用于 hover 或高优先级卡片边界。
- `--border-focus`（`rgba(108,99,255,0.45)`）用于焦点、选中和品牌交互状态。
- 深色文字使用 `--text-primary: #F5F7FF`、`--text-secondary: #A7B0C3`、`--text-tertiary: #68738A`；不得让所有文字都使用纯白。
- 滚动条使用 `--scrollbar-thumb`、`--scrollbar-thumb-hover`、`--scrollbar-thumb-active`，宽度固定为 `6px`，避免使用高对比亮色滚动条。

#### 3.3.3 卡片 Elevation 与 Glow

- 普通卡片消费 `--surface-card`，边框使用 `--border-subtle`，默认不使用明显阴影。
- 重点卡片消费 `--surface-elevated`，边框可使用 `--border-default`；Dashboard 系统状态卡属于此类。
- 卡片 hover 仅做 `translateY(-2px)` 与 Surface Highlight 提升，过渡时间使用 `220ms`，并在 `prefers-reduced-motion: reduce` 下关闭位移。
- `--brand-glow: 0 0 40px rgba(99,102,241,0.15)` 仅允许用于 Hero、活动导航和主按钮等品牌关键区域。
- 禁止给所有卡片统一添加 Glow；Glow 不能替代 Surface、Border 或文本状态表达。

#### 3.3.4 Header、Dashboard 与浮层

- Header 使用 `--surface-glass`、`backdrop-filter: blur(16px)` 和 `--border-subtle` 底边，保持轻量玻璃层，不堆叠重阴影。
- Dashboard 页面背景使用 `--surface-base`；普通图表主体使用 `--surface-card`，图表标题区使用 `--surface-elevated`，系统运行状态卡使用 `--surface-elevated`。
- Modal、Popover、Drawer 等浮层优先使用 `--surface-elevated`；普通卡片不能通过透明度“看穿”页面背景。
- Surface 只改变色彩、边框、阴影和材质，不改变页面布局、导航结构、组件功能、文案或业务逻辑。

#### 3.3.5 AI 对话输入区

- AI 助手与 AI 工作台复用同一个 `KimiChatInput` 输入组件，外层、文本编辑区和 Naive UI `NInput` 内部背景必须使用同一组语义变量：`--chat-input-bg: var(--neutral-card)`、`--chat-input-border: var(--neutral-border)`。
- 深色模式下禁止在业务页面为输入区写死黑色背景（例如 `#1a1a1a`）或白色半透明背景；输入区各层保持同色，避免出现“外框深蓝、内部黑色”的割裂效果。
- 工作台页面如果不在 `.kimi-layout` 作用域内，必须在页面根容器补齐上述两个变量，再消费 `KimiChatInput` 的默认样式；按钮激活态使用 `--arco-primary` 与 `--arco-primary-light`。
- 输入区的边框、圆角和阴影遵循组件默认值；页面级覆盖只能用于布局尺寸，不得重新引入独立的表面色和阴影体系。

### 3.4 间距、圆角、阴影与排版

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
- 复用全局 `.cygnusx-segmented-toggle`：`1px` `--neutral-border` 边框、`999px` 圆角、`--neutral-fill-2` 轨道、`11px` 加粗标签；选中态使用 `--arco-primary` 背景和 `--text-on-primary` 文字。
- 容器使用 `role="group"` 和可读 `aria-label`；按钮使用 `aria-pressed`，并提供 hover、focus-visible、键盘操作和 `prefers-reduced-motion` 适配。
- 窄屏保持紧凑但不得裁切标签；图表卡片工具栏在 `640px` 以下允许换行。

### 5.2 卡片

- 使用 `NCard` 或已有 `.arco-card` / `.cygnusx-card` 外观模式；新卡片优先复用 `NCard`。
- 卡片标题使用 `16px / 24px / 500`；卡片内信息按 `8px`、`12px`、`16px` 阶梯分组。
- 可点击卡片应有 hover、active、focus-visible 和 selected 状态；悬停位移不超过 `2px`。
- 只要卡片本身可点击，就不要在内部塞满冲突的次级点击区域；必要时使用显式操作菜单。

#### 可选择卡片协议

- 所有会保留选择结果的卡片使用 `.cygnusx-selectable-card`；已选项同时使用 `.is-selected`，或以 `aria-selected="true"`、`aria-checked="true"`、`data-selected="true"` 表达状态。
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
- **用户文件路径不得暴露平台存储根目录**：面向普通用户展示、通知、复制的任务工作目录、结果目录、产物目录等路径，统一通过 `frontend/src/utils/userPathDisplay.ts` 的 `formatUserPath()` 格式化。它仅移除当前用户 Home 前缀 `/data/cygnusx/users/<user-id>`，保留其后以 `/` 开始的工作台相对路径；例如 `/data/cygnusx/users/cb79a200-b2ca-441f-9a42-d3417fbfa89d/raw_data/raw-data/PRJNA1478012` 显示为 `/raw_data/raw-data/PRJNA1478012`。日志、错误详情、提示等自由文本使用同文件的 `redactUserHomePaths()` 移除其中每个用户 Home 前缀。不可在业务组件内用 `replace()` 重复实现；原始绝对路径仅用于后端/API 请求，平台共享资源、管理员诊断路径和无法确认属于当前用户 Home 的路径保持原样。
- 任务状态使用 `NTag`，进度使用 `NProgress`；颜色必须来自语义令牌，轨道使用 `var(--neutral-border)`。
- 加载采用 `NSpin` 或 `NSkeleton`；无数据采用 `NEmpty`，并给出下一步按钮或解释。
- 成功、警告、错误消息使用 `useMessage()`；长期或富内容反馈使用 Notification / Result，不要把所有信息塞进 toast。
- 远程表格将页码、页大小、排序、筛选和关键词收敛为单一查询状态，由可重复调用的 `load*` 函数请求数据；切页、排序和筛选只更新该状态并局部刷新，不重载路由或丢失用户上下文。
- 表格行必须提供稳定唯一的 `row-key`。选择、展开和筛选若需要跨局部刷新保留，使用受控状态；数据更新后应明确移除已不存在行的选择，不能静默指向错误记录。
- 工作台内的任务表格与承载卡片左右边缘对齐：表格使用 `width: 100%`，**不得**用 `max-width` 在宽屏截断后留下右侧空白。列宽之和超过可用空间时，仅由表格包装层提供横向滚动，不能以缩窄表格或将空白留在操作列之后作为降级方式。
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
- 折叠侧栏保持 `64px` 宽，内部左右留白为 `8px`；图标选中面必须占满可用的 `48px` 宽度并使用 `44px` 高圆角胶囊。选中态同时提供低强调主色底、连续内描边和左缘短状态条，避免只留下窄竖线或小面积底色。状态条使用 `3px` 宽、距左侧 `4px`，展开态高 `26px`、折叠态高 `30px`，始终以 `top: 50% + translateY(-50%)` 相对行内容垂直居中；不得使用 `top/bottom` 撑满整项。
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
2. **选定单一组件库**：CygnusX 使用 Naive UI；新 Vue 平台可选择 Arco Design Vue，但不得混用。
3. **配置应用层主题**：在入口注册组件库、全局语言、主题和图标；将主色、圆角、背景与表面映射到令牌。
4. **建立壳层**：先完成顶部栏、侧边栏、移动端抽屉和统一页头，再开发业务页面。
5. **沉淀页面配方**：实现仪表盘、列表/表格、详情、表单、空状态和错误状态的标准模板。
6. **最后接入业务接口**：加载、重试、部分失败和权限状态必须按本规范呈现。

### 8.1 Naive UI 与 Arco Design Vue 对照

| 场景 | CygnusX（Naive UI） | 新平台如选择 Arco Design Vue |
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
- [ ] 所有可选择卡片是否使用 `.cygnusx-selectable-card`，并提供连续选中描边、左缘状态线、文本或图标提示与键盘选择？
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
- [ ] 涉及流式/连接类组合式函数（`useChatStream`、`useAgentChatStream`、WebSocket 等）改动时：`isStreaming`/`status` 等入口守卫标志位是否在 `try/finally` 中对**所有**退出路径复位（§18.2 流式状态机纪律）？是否有"同一实例连续第二次调用"的回归测试？diff 中删除 `finally` 一律打回。

### 10.1 Dark Mode Checklist

- [ ] 页面是否存在明确的 `Surface Base → Card → Elevated → Highlight → Glass` 层级？
- [ ] 普通卡片与重点卡片是否分别使用 `--surface-card` 与 `--surface-elevated`，并具有可感知但克制的视觉区别？
- [ ] 是否避免使用纯黑背景 `#000000`？
- [ ] 是否避免大面积 Glow，并只在 Hero、活动导航和主按钮等品牌关键区域使用 `--brand-glow`？
- [ ] Header 是否使用轻微玻璃层、低存在感底边和减少透明度回退？
- [ ] Border 是否按 `subtle / default / focus` 语义分级，而不是在业务组件中重复硬编码？
- [ ] 滚动条是否为 `6px`，并使用低对比度 Surface 令牌？
- [ ] Primary、Secondary、Tertiary 文本是否分别满足深色对比层级，且没有全部使用纯白？

## 11. 可复用 Skill 入口

本规范对应本机 Codex 技能 `$cygnusx-frontend-design`。技能入口保持简洁，完整参考保存在本文件；当令牌、共享组件或工作流变化时，先更新本文件，再同步技能引用副本。

建议的调用方式：

```text
使用 $cygnusx-frontend-design 优化此 Vue 工作台页面；沿用项目已有组件库和主题，先检查设计令牌、页面状态、响应式与可访问性，再实施并验证构建。
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

#### 18.1.1 内联状态卡与路由卡宽度规范（强制）

AI 消息区内嵌的状态提示、路由转交、协作决策等卡片（如 `RouteTransitionCard`、`CollaborationRouteNotice` 及后续同类组件）必须**与消息内容区等宽**，不能因为文案短就收缩成内容宽度，导致上下卡片左右边缘不齐。

- **统一尺寸**：`width: 100%`、`max-width: 1120px`、`margin: 0 0 var(--space-md, 12px)`、`box-sizing: border-box`。
- **内部排列**：标题/标签与说明文字在同一行自然左对齐排列（用 `gap` 连接），**禁止**使用 `justify-content: space-between` 把说明文字推到最右侧；说明文字过长时以省略号截断。
- **权威实现**：`frontend/src/components/ai-chat/RouteTransitionCard.vue`、`frontend/src/components/ai-chat/CollaborationRouteNotice.vue`。
- **新增组件**：凡是在 AI 消息流中水平排列、非浮动/非模态的内联信息卡，默认复用上述尺寸与排列规则；需要特殊宽度时必须在前端设计文档中说明理由。

#### 18.1.2 Plan 分析计划卡片规范（强制）

Plan 分析计划卡片（`PlanCard`）是 Plan 模式下展示任务步骤与执行进度的**输入框附着面板**，不是普通 AI 消息气泡。它必须与底部输入框形成视觉整体，同时保持独立容器与独立生命周期。

**权威实现**：`frontend/src/components/studio/StudioPlanTimeline.vue`；工作台挂载位置为 `frontend/src/views/StudioView.vue` 的输入区上方。相关视觉基线见 `docs/info/26.8.22/前端组件规范-Plan分析计划卡片.md`。

##### 结构与布局

- 卡片由标题行、进度 chip、折叠 chevron 和纵向步骤时间线组成；标题行整行可点击。
- 卡片左右边界必须与同一页面的 `KimiChatInput` 输入框完全对齐。优先复用同一 wrapper；若卡片与输入框是兄弟节点，使用相同的水平 padding 与 `box-sizing: border-box`，不得单独套用消息气泡宽度。
- 卡片与输入框保持 `8px` 间距；卡片使用独立容器，不得叠入、遮挡或改变输入框组件的生命周期。
- 容器使用 `12px` 圆角、`1px` 语义边框、`var(--chat-ai-card)` 或等价 Surface 背景，以及 `var(--chat-shadow-sm)` / `var(--shadow-card)` 柔和阴影。
- 桌面与移动端均须保持输入框边界对齐，移动端不得出现横向滚动；步骤标题过长使用省略号，不允许撑破卡片。

##### 尺寸与视觉层级

| 元素 | 规范 |
| --- | --- |
| 标题 | `14px`、字重 `600` |
| 步骤文字 | `13px`～`14px`；进行中步骤 `500`，其余 `400` |
| 步骤行 | `padding: 8px 12px`；状态标签与步骤文字同行右对齐 |
| 连接线 | `2px`，使用 `--chat-border` / `--neutral-border` 等语义令牌 |
| 时间线节点 | 与步骤文字首行基线对齐；进行中节点显示主色外环 |
| 进度 chip | 文案为 `X/N`，`12px`，圆角 `999px`，水平 padding `8px` |
| 折叠按钮 | 可点击区域不小于 `24×24px`；hover 使用 Surface Hover，不新造颜色 |

颜色必须来自 `--chat-*`、`--neutral-*`、`--arco-primary` 或现有成功/错误语义变量。待执行文字不能使用低对比度浅灰；浅色和深色主题均须满足 WCAG AA，正文对比度不低于 `4.5:1`。禁止在组件样式中新增孤立的 hex 色值。

##### 状态与数据契约

- 计划步骤数据结构与状态流转由业务层维护；卡片只消费步骤列表，不在视觉组件内重写轮询、流式更新或状态机。
- 三种状态必须同时体现为文字、节点视觉和必要的颜色语义：`in_progress`（进行中）、`pending`（待执行）、`done`（已完成）。
- 步骤状态从进行中推进到已完成时，卡片应实时更新节点、状态标签和 `X/N` 进度，不得因折叠动画或组件重渲染丢失数据。
- `done` 步骤可使用实心主色节点与“已完成”标签；`in_progress` 使用主色节点、当前步骤字重 `500` 和低频脉冲；`pending` 使用空心弱化节点，但文字仍需达到可读对比度。

##### 折叠与摘要

- 默认展示步骤列表；折叠后只保留一行摘要和 chevron。
- 执行中摘要格式：`分析计划 · 已完成 X/N · 当前：{当前步骤标题}`。
- 全部完成摘要格式：`分析计划 · N/N 已完成 ✓`。
- 当前步骤优先取 `in_progress`，没有进行中步骤时取下一条 `pending`；没有可执行步骤时显示“等待执行”。标题过长必须省略截断。
- 折叠/展开使用 `grid-template-rows: 0fr ↔ 1fr` 或等价高度过渡，默认 `250ms ease-out`；不支持时降级为可控的 `max-height`，不得用突兀的 `display: none` 代替动画。
- 计划全部完成后只自动折叠一次。用户手动展开后，后续状态更新不得再次自动收起；折叠状态保持在组件会话生命周期内即可，不要求持久化。
- 折叠控制必须提供 `aria-expanded` 与 `aria-controls`；摘要文字应在折叠态对屏幕阅读器可感知。

##### 动效、响应式与验收

- chevron 使用 `transform` 旋转约 `180°`，过渡 `200ms`～`250ms`。
- 进行中节点呼吸效果只允许使用 `opacity`，周期 `1.2s`、`ease-in-out`；禁止使用会引起布局抖动的宽高或 margin 动画。
- 所有过渡控制在 `200ms`～`300ms`；必须提供 `@media (prefers-reduced-motion: reduce)`，关闭循环动画并让折叠直接切换。
- 新增或修改 Plan 卡片时，至少验证：桌面与窄屏边界对齐、折叠摘要、全部完成自动折叠、手动展开后不再自动收起、深浅主题对比度、状态实时推进和无横向滚动。
- 组件测试应覆盖标题行折叠/展开、`X/N` 进度更新和自动折叠护栏；不得只验证静态文案。

### 18.2 流式输出

- 使用 `useChatStream` / `useAgentChatStream` 处理 SSE 或 WebSocket 流。
- 流式文本逐字/逐块追加渲染；使用 `shallowRef` + `requestAnimationFrame` 节流更新（≤ 60fps）。
- 流式过程中显示光标闪烁或"正在输入"指示器。
- 流中断（网络断开、用户取消）：保留已输出内容 + 显示"生成已中断"标记 + 重新生成按钮。
- Markdown 渲染使用流式安全的解析器，避免未闭合代码块导致布局跳动。

#### 流式状态机纪律（强制，违反会让"第二条消息"凭空消失）

流式组合式函数（`useChatStream` / `useAgentChatStream` / `useStudioRunStream` 及今后新增者）内部都有 `isStreaming` 这类**入口守卫标志位**（`if (isStreaming.value) return`）。它们是"闸门"，一旦卡在 `true`，后续所有发送都会被**静默吞掉**——请求根本没发到后端，但调用方的兜底逻辑会把空消息渲染成错误卡片，用户看到的是一条"假的后端错误"。必须遵守：

1. **标志位复位只许放在 `try/finally`**：`isStreaming.value = true` 之后的所有退出路径（`done`、流事件 `error`、HTTP 非 2xx、重试耗尽、用户取消 `AbortError`、抛异常）都必须经 `finally { isStreaming.value = false; abortController.value = null }` 复位。重构（如加重试循环、加提前 `return`）时第一件事就是确认 `finally` 还在、且覆盖所有新旧 `return`。**禁止**只在"正常结束"的某一条 `return` 前手动复位——新增任何提前返回路径时必然漏。
2. **守卫静默 `return` 必须与调用方语义配对**：`streamChat` 因守卫直接返回时不发请求、不触发任何回调；store 层（`agentHub.ts`）的"流结束但内容为空 → 渲染错误卡片"兜底会把它误判为模型空响应。改动守卫条件或兜底逻辑时，必须同时检查另一侧的假设。
3. **回归测试必须覆盖"连续第二次调用"**：任何流式组合式函数的测试里，至少要有一条"第一次流正常 `done` 结束后，用**同一实例**再发一次，断言 `fetch` 被调用了第二次且 `isStreaming` 已复位"的用例（参考 `frontend/src/composables/__tests__/stream-retry.test.ts` 的「正常结束后复位 isStreaming，同一实例可再次发送」）。只测单次调用永远抓不到标志位残留。
4. **排查"模型响应为空/假错误"先看后端有没有收到请求**：遇到"星尘信号受到了干扰 / 当前模型响应为空"这类秒出的错误，先查后端访问日志与 `chat_messages` 表。若请求根本没到后端，优先怀疑前端守卫吞请求，而不是模型或网络。

#### 案例：isStreaming 未复位导致同会话第二条消息被静默吞掉（2026-08-09）

- **现象**：AI 助手新会话第一条消息正常（欢迎语流出），第二条消息发送后秒出错误卡片"星尘信号受到了干扰 / 当前模型响应为空，请重新发送"，重试仍失败，只有切换会话或刷新页面能恢复。
- **根因**：`ece09cc`（26.8.8-2）给 `useAgentChatStream.streamChat` 加自动重试 while 循环时，删掉了原来的 `finally { isStreaming.value = false; abortController.value = null }`，且没有在任何正常结束路径补回复位。第一条流正常 `done` 后 `isStreaming` 永远停在 `true`；第二条消息在入口守卫 `if (isStreaming.value) return` 处直接返回，**fetch 从未发出**（后端日志与 `chat_messages` 表均无该消息记录），store 兜底把空占位消息渲染成错误卡片。
- **修复**：在重试循环外包 `try/finally` 复位 `isStreaming` 与 `abortController`（刻意不动 `isPaused`，保持暂停功能语义），并补"同一实例第二次调用"回归测试。
- **教训**：① 带入口守卫的状态标志位，复位逻辑必须钉死在 `finally`，重构前先列全所有退出路径；② "重试/循环/提前 return"类重构是高危动作，diff 里出现删 `finally` 一律打回；③ 秒出的"模型空响应"错误先怀疑前端没发请求，排查顺序：后端访问日志 → 数据库消息表 → 前端守卫/状态机。

### 18.3 输入区

- 多行文本框（`NInput type="textarea"` + `autosize`）；`Enter` 发送，`Shift+Enter` 换行。
- 发送按钮在空内容或生成中时 `disabled`；生成中变为"停止"按钮。
- 支持附件（图片、文件）时，输入区上方显示附件预览条。
- **拖拽上传**：输入区整体响应 `dragenter/dragover/dragleave/drop`，仅当拖拽内容包含文件（`dataTransfer.types` 含 `Files`）时显示高亮覆盖层与释放提示；释放后调用与点击上传同一套 `chat-upload` 接口，并追加到附件列表。生成中/禁用时拒绝拖拽。
- 输入历史：`↑`/`↓` 切换最近发送的消息（可选）。

### 18.4 工具调用与多步结果

- AI 调用工具时，在消息流中插入"工具卡片"：显示工具名、参数摘要、执行状态和结果折叠区。
- 长时间工具执行显示进度或旋转指示器；超时（> 60s）提示用户。
- 错误结果使用 `NAlert type="error"` 内嵌在消息中，不中断对话流。

#### 18.4.1 工具卡片折叠与长结果高度护栏（强制）

工具结果长度不可控（文件列表、表格 dump、检索命中等动辄几十上百行），**任何**工具结果渲染区都必须有高度上限，不能把整条消息流撑开。

- 权威实现：`frontend/src/components/ai-chat/McpToolCallCard.vue`。
- **默认折叠**：卡片只显示工具图标 + 工具名 + MCP server 标签 + 状态标签 + 旋转箭头，单行点击展开。
- **折叠态预览**：`list_workspace_files` / `search_workspace_files` 等清单类工具可显示首行结论（如"工作区根目录 下共 66 项"），但必须用 `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` 截成**单行**，完整清单只在展开后可见。
- **展开态也要限高**：结果/摘要区即使展开也不允许无限撑高——`workspace-summary` 用 `max-height: 220px; overflow-y:auto`，原始 JSON 的 `.tool-pre` 用 `max-height: 200px`。需要看全量内容的用户在区域内滚动，而不是滚整条对话。
- 给工具加"折叠态摘要"时，用 `computed` 从 `tool.result.summary` 等结构化字段取**结论行**，不要把整段结果塞进预览。

#### 18.4.2 ask_user 澄清卡片必须提供可点选选项（强制）

澄清工具 `ask_user` 以可交互卡片收集回答（`frontend/src/components/ai-chat/AskUserCard.vue`），不是纯文本提问。

- **有选项时**：渲染分页问题向导，每题显示 `options` 可点选项 + "其他"自由输入 + "跳过（Esc）" + "下一步/提交"。含"（推荐）"标注的选项用稳定排序排到首位（`sortedOptions`）。
- **无选项时**：自动退化为自由输入框（`showOther` 默认 true），并在已回答态把空答案显示为"无偏好，由你决定"。退化形态是**兜底**，不是常态。
- 前端契约类型：`AskRequest { questions: AskQuestion[] }`，`AskQuestion { question: string; options?: string[] }`；同时兼容后端平铺的 `question` / `options`（见 `useAgentChatStream.ts` 的 ask_request 归一化）。
- **已回答态**折叠成工具卡样式（"询问工具 | 已收集信息"），展开可回看问答，不重新展示可点选项。

> 跨层约束：模型偶尔把 `questions` 数组序列化成 JSON **字符串**（甚至双重编码、尾部带多余引号/换行）传来。后端 `_normalize_ask_questions` 必须用宽松解析（先 `json.loads`，失败用 `json.JSONDecoder().raw_decode` 取首个完整 JSON 值，双重编码再解一次），解析失败才降级为空问题自由输入。**只认数组会让弹窗变成"请补充需求细节 / 无偏好"的空壳**——卡片本身没坏，是选项没被解析出来。新增结构化数组参数的工具，后端入参归一化同样要容忍字符串形态。

#### 18.4.3 历史重载契约：工具卡片与产物必须能重建（强制）

会话重新打开后，工具调用卡片、工作区摘要、Plotly 图表等必须和实时流式时一致地渲染出来。这是一条**跨前后端的持久化契约**，前端只负责把后端落库的数据 hydrate 回 `ToolCall`。

- 权威 hydrate 实现：`frontend/src/stores/agentHub.ts` 的 `loadSessionMessages()`——从 `metadata_json.tool_invocations` 重建 `msg.toolCalls`，从 `metadata_json.timeline` 重建正文/工具交错顺序。
- **`tool_invocations`**：每次工具调用一条，字段 `tool_call_id / tool_name / arguments / success / result / ui_payload / mcp_server`。前端凭 `arguments + ui_payload + result` 渲染卡片。**Plotly 火山图等图表数据在 `ui_payload.plotly_figure` 里**（见 `KimiMessageItem.vue` 的 `extractPlotlyFigure`），这个字段不落库，重开后图就永久消失。
- **`timeline`**：`{ kind: 'text'|'tool', text?, tool_call_id?, tool_name? }` 段数组，保证重载后仍是"正文→工具→正文"的交错布局，而不是正文堆上面、工具全堆下面。
- 落库载荷经 `_cap_tool_invocation_payload`（200KB 护栏）截断；前端遇到 `{ _cygnusx_payload_truncated: true }` 按"无载荷"降级渲染，不能崩。
- 前端 hydrate 时：`mcp_server` 旧数据缺失回退 `'studio'`；`update_plan` 的 steps 要恢复到右侧待办面板；`ui_payload.stdout/stderr` 拼到 `tool.output`。

> **后端双执行路径陷阱**：`ChatService` 有两套并行的 Agent 执行路径——legacy 手写 `for _round` 循环和 LangGraph 引擎（`_stream_agent_chat_langgraph`，普通 `mode=chat` 会话默认走它）。工具调用落库、`timeline`、`ask_request`、handoff 等副作用在两条路径里**各自独立实现**。任何"工具结果要持久化/要随消息返回"的改动，**必须同时改两条路径**；只改 legacy 会让普通 chat 会话重开后卡片与图全部丢失（此问题真实发生过：LangGraph 路径只把 tool_call/tool_result yield 透传，从未写 `tool_invocations`）。
>
> 已经丢失的历史消息无法事后恢复（数据当时没落库）；修复只对新产生的消息生效。

## 19. 终端与代码沙箱

### 19.1 终端 UI

- 使用等宽字体：`'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace`。
- 背景使用 `--neutral-card` 或专用深色终端背景（深色模式下与页面背景区分）。
- 输出区域限制 DOM 行数（最近 5000 行）；超出时截断顶部并提示"更早输出已截断"。
- 支持文本选择复制；`Ctrl+C` 在无选区时发送 SIGINT，有选区时复制。
- 连接状态指示器放在终端标题栏右侧。

### 19.2 云端沙盒终端删除守护

沙盒容器挂载用户持久化的 workspace / raw_data / temp 目录，容器内删除即平台数据删除且不可恢复。终端输入链路必须提供删除操作二次确认：

- 权威实现：`frontend/src/utils/terminalDeleteGuard.ts`（`isDangerousDeleteCommand()` 启发式匹配 + `TerminalLineBuffer` 行缓冲状态机）、`frontend/src/components/terminal/XTerminal.vue`（`onData` 拦截回车并弹 `dialog.warning`）。
- 命中 `rm / rmdir / unlink / shred / find -delete / git rm / git clean` 等删除类命令时，拦截回车、弹出确认（`确认执行` 为 `type="error"` 按钮，`maskClosable/closeOnEsc` 关闭）；确认后才发送回车，取消发送 `Ctrl+U` 清除 shell 行。
- 弹窗打开期间吞掉终端输入，避免破坏 shell 行状态；方向键 / Tab 补全 / 历史搜索等带外改行场景标记 uncertain 并跳过本次检测，宁可漏报不打扰。
- 该守护是"提示"而非安全边界，不替代后端权限与容器隔离。
- 面向用户不得暴露容器内路径（如 `/home/cygnusx/workspace`）：启动配置预览的挂载目录显示"我的 workspace"，容器 zshrc MOTD 使用 `~/workspace` 表述并附数据警示（`tool_configs/terminal/docker/zshrc`，改动需重建镜像生效）。

### 19.3 代码沙箱

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
| CSS 类 | kebab-case 或 BEM | `.cygnusx-selectable-card`、`.page-header-main` |
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
- 页面标题在 `router.afterEach` 中统一设置为 `{title} - CygnusX`。

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
- **表格元素必须 `width: 100%` 与卡片左右边界对齐铺满，禁止给表格本身设 `max-width`**（如 `1440px` 封顶）——封顶会让宽屏下表格左对齐、右侧露出一条空白，2026-08-03 任务中心表格即此问题。需要限制阅读宽度时收容器（页面壳层），不收表格。
- **短值/离散列居中**：所属用户、分析流程、数据库、Program、状态、操作等用列级 `align: 'center'`（naive-ui 会**同时居中对齐表头与表体**，不必再单独写表头 CSS）。
- **进度列不要居中**：进度条 + 百分比是从左到右的组合单元，居中会在条左侧留下随宽度变化的空白，显得错位；进度列保持左对齐，只靠 ① 解决换行。

**④ 用户展示名：昵称优先，用户名兜底；不展示裸 UUID/假数据。** 所有平台中表示用户的列表列、表格单元格、卡片标题、图表标签和导出内容，统一使用“昵称（`nickname`）优先；昵称为空、空白或未设置时使用用户名（`username`）”的规则。前端必须调用 `frontend/src/utils/displayName.ts` 的 `displayName({ nickname, username })`，不得在各页面复制 `nickname || username` 判断；`user_id`（UUID）仅可作为 API 缺失用户资料时的最后技术降级，不能作为设计预期或主展示文本。

- **接口契约**：凡返回用户归属的 DTO 必须同时提供 `username` 与可空 `nickname`，包括分析任务、BLAST、工作流监控、终端会话、AgentTeams Case、饼干账户与交易流水等；后端按 `user_id` / `requester_ref` 批量或去重回填，不能要求前端额外以 UUID 反查用户资料。
- **展示与审计分离**：用户列第一行、导出“用户”字段、当前用户名称等均用展示名；需要排查或执行管理操作时，用户名 / UUID 可作为明确标注的辅助信息或内部操作参数，不应拼接进主展示名。
- **前端类型**：上述记录类型应保留 `username?: string | null` 与 `nickname?: string | null`，让共享工具在昵称为空白时稳定回退。无用户资料时的占位使用 `未知用户` / `-`，而不是 UUID。

任何带"所属用户"列的表格，必须由后端回填真实用户资料，而非在前端展示 `user_id`（UUID）或用写死的 mock 行占位：

- 分析 `GET /api/v1/tasks` 的 `TaskResponse.username` / `nickname` 由 `TaskService.list_tasks` 经用户仓储按 `user_id` 回填（去重后查询，单用户列表只查一次）。
- BLAST 列表 `BlastTaskListItemDTO.user_id` / `username` / `nickname`：`list_user_tasks` 用 `outerjoin UserModel` 取两项资料，`list_all_tasks` 复用其既有 `UserModel` join（不要丢弃已 select 的昵称）。
- 前端 `displayName(row) || row.user_id` 仅作最后技术降级，**不是**设计预期。仪表板"最近任务"在迭代期曾用 mock 预览多用户混合，接口就绪后必须切回真实接口（按当前用户视角），空数据走 `NEmpty` 真实空态，不用假行填充。
- 操作列同理：查看/删除接真实接口（查看跳详情、删除走 `DELETE` 并局部刷新），后端未上线的能力（如"重新运行"）按终态 `disabled` + Tooltip"即将上线"诚实表达，**不要**用 `message.info('对接中')` 之类的假 toast 冒充可用。

**⑤ 卡片垂直节奏统一为 24px。** 仪表盘各区块（概览网格 / 快速开始 / 监控面板 / 最近任务 / 最近 BLAST）每个根 section 自带 `margin-bottom: 24px`，构成统一的 24px 垂直节奏。新增卡片 section 必须同样带 `margin-bottom: 24px`，**不要**让相邻卡片间距塌缩为 0（只写 `overflow:hidden` 而漏掉外边距是常见错误，会导致两张卡片贴在一起、与其它卡片间距不一致）。

**⑥ 表格任务卡片的表面、选中态与进度单元格。** 仪表盘的“最近任务”和“最近 BLAST 任务”是同一类任务表格卡片；两者必须使用相同的表面和进度布局契约。当前权威实现位于 `frontend/src/views/DashboardView.vue`。

- 两张 `NDataTable` 均保留基础类 `.recent-table`，并附加 `.recent-table-surface`。后者负责不透明分层：表格容器与单元格使用 `var(--neutral-card)`，表头使用 `var(--neutral-bg)`；不得在表格区域使用 `rgba()`、`opacity` 或半透明白色叠加。浅色主题下分别对应白色表面和浅灰表头，深色主题自动跟随令牌。
- 可选卡片使用共享选中态类（例如 `.is-selected`、`.card--selected` 或 `aria-selected="true"`）。任务卡片选中时必须保留全局 `4px` 左侧状态条，并使用 `color-mix()` 生成约 `4%` 主题色的极浅底、约 `40%` 主题色的描边和内描边；未选中卡片继续使用既有 `--neutral-card`，不得改变默认中性外观。
- 表头与表体沿用 `.recent-table` 的字号、文字颜色和 `--neutral-border` 分隔线；行悬停仅使用 `var(--neutral-hover)`，不能覆盖卡片选中态的边框和状态条。
- 所有列必须给出固定 `width`，`scroll-x` 等于列宽总和。当前分析任务表为 `970`，BLAST 任务表为 `1020`；窄屏在现有表格滚动容器内滚动，不为适配窄屏压缩列、折行百分比或在页面根部新增横向滚动。
- 短值和离散列通过 Naive UI 列配置 `align: 'center'` 同时对齐表头与表体。任务名称、查询标题和时间等在当前仪表盘任务表中也保持居中；进度列例外，保持左对齐，避免进度条组合在居中列中产生随列宽变化的空白。
- 进度单元格统一由 `renderTaskProgress()` 生成：外层 `.recent-task-progress` 使用 `display: flex`、`align-items: center`、`min-width: 0` 和 `white-space: nowrap`；内部 `.n-progress` 使用 `flex: 1 1 auto` 和 `min-width: 60px`；百分比 `.recent-task-progress__value` 使用 `flex: 0 0 44px`、右对齐、`white-space: nowrap` 与 `font-variant-numeric: tabular-nums`。`NProgress` 关闭内置指示器，百分比由固定宽度文本单独渲染，保证 `0%`、`45%`、`100%` 均不折行。
- 操作列使用列级居中；多图标操作组通过 `NSpace` 的 `justify: 'center'` 和 `size: 12` 布局。图标按钮仍必须保留 `NTooltip`，删除操作仍通过 `NPopconfirm` 确认；本规范只约束样式与布局，不改变刷新、查看、重试或删除逻辑。

**⑦ 平台通用卡片表格基线。** 除仪表盘任务表的专属进度规则外，所有嵌入 `NCard`、`.arco-card`、`.cygnusx-card`、`.table-card`、`.work-card`、`.result-card`、`.bottom-table`、`.table-wrap` 或 `.resource-tab` 的 `NDataTable` 都由 `frontend/src/styles/global.css` 的“卡片内数据表格”规则统一提供不透明 `--neutral-card` 表面、`--neutral-bg` 表头、`--neutral-border` 分隔线、`--neutral-hover` 行悬停色以及 `max-width: 100%` 容器约束。因此，任务/结果表、管理表和实验计算器结果表不得在局部样式中重新引入半透明表格底色或硬编码白色；业务页面只需按数据密度配置列宽、`scroll-x`、省略与对齐策略。

带内置分页的卡片表格还必须把 `.n-data-table__pagination` 作为独立 footer：使用实体 `--neutral-card` 背景、顶部 `--neutral-border` 分隔线，以及足够的左右和底部内边距。分页存在时，末行单元格的底边应透明，由 footer 顶边承担唯一分隔，避免暗色模式下末行横线与分页器重叠；最右侧翻页按钮不得贴住卡片边缘或被圆角裁切。该规则统一维护在 `frontend/src/styles/global.css`，页面不得逐个复制分页补丁。

参考结构：

```ts
const columns: DataTableColumns<Task> = [
  { title: '任务名称', key: 'name', width: 220, align: 'center', ellipsis: { tooltip: true } },
  { title: '进度', key: 'progress', width: 170, render: (row) => renderTaskProgress(row.progress) },
  { title: '操作', key: 'actions', width: 110, align: 'center', render: renderActions },
]
```

**⑧ 主标识列与用户列：双行单元格（标题/名称在上，等宽 ID 在下）。** 列表的主标识列（Case、会话、资源名）和用户列统一采用"双行单元格"结构，权威实现：`frontend/src/views/AdminSessionLogsView.vue`（会话排查列表）、`frontend/src/components/task/AgentTeamsCasesPanel.vue`（任务中心 AgentTeams 协作 tab）。

- **结构**：单元格为纵向 flex（`gap: 2–3px`）；第一行是主文本（标题/名称/用户名），第二行是等宽字体（`var(--font-mono, ui-monospace, …)`）的辅助 ID（UUID / session_id / case_id），颜色 `--neutral-text-3`、字号 `12px`。
- **主文本层级**：可跳转的主标识列第一行用 `14px / 600 / --neutral-text-1`，整格作为链接但**不渲染成整行蓝色链接**——保持正文色，hover 才变 `--arco-primary`；用户列第一行用 `13px / 500 / --neutral-text-1`，并展示 `displayName({ nickname, username })` 的结果。
- **溢出**：两行都必须 `text-overflow: ellipsis + white-space: nowrap`，ID 行带 `title` 悬浮查看完整值；需要复制 ID 时按 AdminSessionLogsView 的做法附加 quaternary 小按钮。
- **用户列数据契约**：后端必须按 `user_id` / `requester_ref` 回填真实 `username` 与 `nickname`（如 `TaskService._attach_user_display_info`、`/api/v1/agent-teams/cases` 的 `_attach_requester_user_display_info`，去重后逐查询）；前端 `displayName({ nickname, username }) || '未知用户'` 仅作展示降级，不得把裸 UUID 当作设计预期（与 ④ 同一纪律）。
- 双行单元格仍遵守 ③：该列给一个克制的固定 `width`，不计入弹性列。

### 33.3 验收清单（在 §10 通用清单之上补充）

- [ ] 进度/百分比/计数等派生数值是否经归一化或确定性公式渲染，在 0–1 与 0–100 两种数据尺度下都正确（无 1000% / 无 1% 误显）？
- [ ] `renderTaskProgress()` 是否关闭 `NProgress` 内置指示器，并由 `.recent-task-progress`、`.n-progress` 与 `.recent-task-progress__value` 的 flex/固定宽度组合保证百分比单行显示？
- [ ] 数据表格是否**所有列固定 `width`、无弹性列**，且 `scroll-x` 等于列宽之和；长文本列有 `ellipsis` + Tooltip？
- [ ] 短值/离散列是否 `align:'center'`（表头+表体一致），进度列是否保持左对齐？
- [ ] 带"所属用户"的表格、图表标签和导出是否经 `displayName()` 展示昵称优先、用户名兜底的真实用户资料（后端回填 `username` + `nickname`），而非 UUID 或 mock；空数据是否走真实 `NEmpty`？
- [ ] 操作列是否接真实接口；未上线能力是否诚实 `disabled` + Tooltip，无假 toast？
- [ ] 仪表盘卡片 section 是否都带 `margin-bottom: 24px`，相邻卡片间距与其它卡片一致？
- [ ] “最近任务”与“最近 BLAST 任务”是否都附加 `.recent-table-surface`，在选中和未选中状态下均保持不透明表格表面与清晰边界？
- [ ] 卡片内 `NDataTable` 是否依赖全局“卡片内数据表格”规则获得主题表面，而没有通过局部 `rgba()`、`opacity` 或硬编码白色破坏明暗主题？
- [ ] 主标识列 / 用户列是否采用 §33.2 ⑧ 的双行单元格（标题 + 等宽 ID；展示名 + UUID），且用户资料由后端回填真实 `username` + `nickname`？
- [ ] 设计是否规避 §33.1 的"AI 默认"清单，在不破坏 §1 克制与可访问性的前提下具备品牌层次与辨识度？

## 34. 知识库阅读页三要素冻结规范（卡片 / 侧栏 / 大纲）

> **状态：冻结（2026-07-28）**。本节规定知识库阅读页（快速入门等）的星尘引言卡片、文档树侧栏、右侧大纲三要素的样式与实现方式。**冻结期内不得修改其结构、样式与交互**；确需调整必须先修订本节并明确告知，再改代码。权威实现：
> - `frontend/src/components/knowledge/DocReader.vue`（阅读布局 + 大纲）
> - `frontend/src/components/knowledge/KnowledgeStardustQuote.vue`（星尘引言卡片）
> - `frontend/src/components/knowledge/DocTree.vue`（文档树侧栏）

### 34.1 星尘引言卡片（KnowledgeStardustQuote）

**使用契约**：仅快速入门（`doc.id === 'getting-started'`）使用。`DocReader` 用正则 `OPENING_STARDUST_QUOTE` 匹配正文开头的萨根引言 blockquote，命中则**从 Markdown 中剥离**并以组件渲染；未命中则保留原文，不渲染组件。文档正文的开头引言段不得随意改写，否则卡片静默失效（2026-07-28 事故的教训：任何改动必须同步检查正则）。

**样式契约**：
- 容器：圆角卡片（`--radius-card`），`1px` 品牌浅边框（`--stardust-border-soft`），背景 = 双层 radial 星尘光晕 + `--neutral-card` 基底，`--stardust-card-shadow` 浅阴影；顶部 kicker `FROM STARDUST, TO DISCOVERY`（11px / 700 / 0.16em 字距 / `--stardust-blue`）。
- 引文：英文主句用 Georgia 衬线斜体 `clamp(22px, 2.2vw, 30px)`，中文段落 15px / 1.9 行高 / `--neutral-text-2`；左侧 2px 渐变竖轨 + 大号 `“` 装饰引号；署名右对齐。
- 装饰：两个描边圆环（缓慢漂移）+ 三颗闪烁星点（`box-shadow` 光晕），纯 CSS，`pointer-events: none`。
- 动效：光束扫过 14s、竖轨呼吸 4.8s、圆环漂移 18/22s、星点闪烁 3.8s；`prefers-reduced-motion` 全停，`prefers-reduced-transparency` 退化为纯色卡片，`forced-colors` 有兜底。
- 响应式：`≤680px` 缩小 padding/字号，隐藏第二圆环与第二星点。
- 主题：全部经 `--stardust-*` / `--neutral-*` 令牌（`tokens.css` 亮暗双定义），禁止硬编码色值。

### 34.2 文档树侧栏（DocTree）

- 组件：naive-ui `NTree`，`block-line` + `block-node` + `expand-on-click`；展开态受控（`expandedKeys` / `update:expandedKeys`），选中态 `:selected-keys="['doc:'+activeId]"`。
- 节点：图标（分类 `FolderOutline` / 文档 `DocumentTextOutline`，15px）+ 标签文本（`NTooltip` 悬浮显示全名，长名省略）+ 状态点（`NBadge` dot，仅对有权限用户显示审核状态）。
- 样式：节点内容区 `padding: 3px 4px`、`--radius-sm` 圆角；hover `--neutral-hover`；选中 `--arco-primary-light` 背景；字号 `--font-body-size`，颜色 `--neutral-text-2`；过渡 `--motion-quick`。
- 交互：`expand-on-click` 点击即展开并触发选择；选择经 `findNode` 回溯 `doc:` 前缀 key 后 emit `select`。

### 34.3 右侧大纲（reader-toc）

**实现方式（冻结）**：不用 md-editor-v3 的 `MdCatalog`（其内部事件总线曾导致大纲不渲染）。大纲从 `resolvedContent` 源码自行解析——跳过围栏代码块与引用块内的井号行，提取 `#{1,6}` 标题并剥离内联标记（图片/链接/强调/HTML）；活动项经滚动容器（`.content-body`）`scroll` 监听 + 标题 DOM `getBoundingClientRect` 校准；点击大纲项按矩形差值 `scrollTo` 平滑定位。文档切换时重置活动项并 `nextTick` 校准。

**布局**：`reader-layout` flex 双栏 = 预览 `0 0 80%` + 大纲 `0 0 20%`，均 `min-width: 0` 防长串吹爆；大纲 `position: sticky; top: 16px`，`max-height: calc(100vh - 180px)` 自滚动，左缘 `1px --neutral-border` 分隔线。`≤1024px` 转单列，大纲移至文末（`position: static`，`max-height: 240px`，改上缘分隔线）。

**样式**：标题 `大纲`（caption 字号 / 600 / 0.06em 字距 / 大写 / `--neutral-text-3`）；条目 5px 10px padding、`--radius-sm`、hover `--neutral-hover`；**活动条目** = `--arco-primary` 文字 + `--arco-primary-light` 背景 + 左缘 3px×14px 品牌状态线（呼应平台侧栏选中态）；`focus-visible` 2px 主色 outline；大纲区自有细滚动条（亮 `rgba(29,33,41,.15)` / 暗 `rgba(255,255,255,.16)`，6px 圆角 thumb）。

### 34.4 变更纪律

1. 三要素的结构/样式/交互改动一律先改本节规范再改代码，禁止"先改后补"。
2. 任何涉及 `getting-started` 正文开头、引言正则、`resolvedContent` 的改动，必须回归验证：卡片渲染、大纲非空、锚点定位、活动项跟随四项全绿。
3. 构建后抽查 dist 产物含 `knowledge-stardust-quote` 与 `暂无大纲` 特征串（防"改了没进包"）。


## 35. AI 助手主入口设计与优化规范

> **适用范围**：CygnusX 星尘 AI 主入口、空会话欢迎页、对话页、工作台模式和智能体能力入口。
>
> **设计目标**：AI 主入口不是营销落地页，而是面向生物信息学任务的高频工作界面。页面应让用户在进入后快速完成“理解当前助手 → 选择常见任务或引用数据 → 输入需求 → 查看执行过程与结果”的完整路径。
>
> **核心原则**：输入优先、任务优先、上下文连续、状态真实、空态可行动。

### 35.1 页面问题诊断基线

优化 AI 主入口前，先检查以下问题：

1. 空会话页是否存在大面积无功能留白。
2. 欢迎横幅是否比输入区更抢夺注意力。
3. 输入区是否远离欢迎信息和快捷任务，导致操作路径断裂。
4. 模型、运行模式、工作台模式和能力入口是否同时使用高强调样式。
5. 快捷任务是否只靠不同颜色区分，而没有语义图标和明确动词。
6. 左侧是否同时存在全局导航、AI 导航和会话导航，造成横向空间浪费。
7. 空会话和已有会话是否使用完全相同的输入区定位，忽略场景差异。
8. AI 生成、工具调用、网络断开和部分失败是否具备完整状态。
9. 浅色、深色、窄屏、减少动态和键盘操作是否均可正常使用。
10. 装饰背景是否符合 §31，未参与页面布局或拦截点击。

AI 主入口优化不得只调整颜色、阴影和圆角。必须同时评估信息架构、首屏操作路径、输入状态、会话状态和响应式行为。

### 35.2 页面信息架构

AI 主入口按以下优先级组织：

1. 助手上下文：助手名称、简短能力说明、连接或可用状态。
2. 输入区：文本输入、文件引用、技能或工具选择、发送按钮。
3. 快捷任务：当前助手最常用的 4 至 6 个操作。
4. 最近上下文：最近会话、最近文件或最近任务中的一种。
5. 高级设置：模型选择、推理模式、联网、工作台模式和能力详情。
6. 系统说明：免责声明、配额、权限、连接异常等辅助信息。

首屏只能有一个最强操作中心。默认情况下，该中心是 AI 输入区及发送按钮。

模型选择、工作台模式和能力查看是辅助操作，不得与发送按钮竞争主操作层级。

### 35.3 空会话与活跃会话双布局

AI 主入口必须区分空会话和已有消息的会话。

#### 35.3.1 空会话状态

空会话采用居中但偏上的连续任务流：

```text
助手名称与简短说明
输入需求
快捷任务
最近会话或最近文件
```

实现要求：

- 主内容容器宽度使用 `width: min(100%, 1120px)`。
- 主内容区域与顶部工具栏之间使用 `32px` 或 `40px` 间距。
- 输入区紧邻助手说明，间距为 `20px` 或 `24px`。
- 快捷任务与输入区间距为 `20px`。
- 最近上下文与快捷任务间距为 `32px`。
- 不使用固定高度制造垂直居中。
- 不在输入区和欢迎区之间保留无功能的大面积空白。
- 页面高度不足时允许自然滚动，不裁剪快捷任务或输入区。
- 空会话输入区不得固定在视口底部。

建议结构：

```vue
<main class="ai-entry">
  <section class="ai-entry__intro" aria-labelledby="ai-entry-title">
    <!-- 助手名称、说明和状态 -->
  </section>

  <section class="ai-entry__composer" aria-label="向星尘 AI 提问">
    <!-- 输入区 -->
  </section>

  <section class="ai-entry__suggestions" aria-labelledby="suggestion-title">
    <!-- 快捷任务 -->
  </section>

  <section class="ai-entry__recent" aria-labelledby="recent-title">
    <!-- 最近会话或文件 -->
  </section>
</main>
```

#### 35.3.2 活跃会话状态

存在一条或多条消息后切换为标准对话布局：

```text
助手工具栏
可滚动消息区
底部吸附输入区
```

实现要求：

- 消息区独立滚动，输入区保持可见。
- 输入区使用 `position: sticky; bottom: 0` 或现有可靠布局，不优先使用脱离上下文的 `fixed`。
- 输入区上方使用实体或低透明度表面，避免消息透过后影响可读性。
- 输入区宽度与消息内容主列一致。
- 消息内容主列建议最大宽度 `960px`，单个文本气泡最大宽度遵循 §18.1 的 `720px`。
- 用户向上滚动后暂停自动跟随，并显示“回到底部”按钮。
- 从空会话进入活跃会话时，输入区移动应使用 `opacity` 和 `transform` 短过渡，不动画 `top`、`bottom` 或高度。
- `prefers-reduced-motion: reduce` 下直接切换布局，不执行位移动画。

### 35.4 助手欢迎区域

欢迎区域用于建立助手身份和任务语境，不得设计成营销 Hero。

#### 35.4.1 推荐样式

- 高度由内容决定，建议不超过 `180px`。
- 使用 `--neutral-card`、品牌浅色表面或克制的品牌渐变。
- 圆角使用 `--radius-card`，不得超过平台大型面板规范。
- 内边距桌面端 `24px` 或 `32px`，窄屏 `20px`。
- 标题使用页面标题或 Display 层级，不使用超大营销字体。
- 描述控制在两行内，说明用户可以完成什么，而非重复品牌口号。
- 装饰图形必须 `aria-hidden="true"`、`pointer-events:none` 并符合 §31。
- 欢迎区域不使用无语义关闭按钮。只有可恢复的临时公告才允许关闭。

#### 35.4.2 文案规范

推荐：

```text
星尘 AI
描述分析目标，或引用工作区文件开始任务。
```

避免：

```text
你好！我是智能助手，直接描述你的需求即可，我会自动转接给最合适的专家为你解答。
```

原因：

- 文案过长且偏系统宣传。
- “自动转接”属于系统行为，应在实际发生时反馈。
- 首屏文案应引导当前动作，而不是解释全部产品能力。

如果平台确实存在智能体路由，应在路由发生时展示：

```text
正在为你匹配差异表达分析助手……
```

完成后展示：

```text
已切换到差异表达分析助手
```

不得在路由尚未发生时用静态欢迎文案暗示已经完成匹配。

### 35.5 输入区设计契约

输入区是 AI 主入口的核心组件，应优先沉淀为共享组件，例如：

```text
frontend/src/components/ai/AIComposer.vue
```

页面不得分别实现多套外观和键盘规则不同的输入框。

#### 35.5.1 结构分区

输入区分为三层：

1. 附件预览层：仅存在附件、引用文件或已选择上下文时显示。
2. 文本输入层：多行文本框和生成状态。
3. 工具栏：附件、引用、联网、工具、推理模式、清空和发送。

推荐布局：

```text
[附件 / 引用文件预览]
[多行输入框                                      ]
[附件][引用] [联网][工具][深度思考]       [清空][发送]
```

实现要求：

- 使用 `NInput type="textarea"` 和 `autosize`。
- 默认最小输入高度约 `72px`，最大高度约 `200px`，超出后内部滚动。
- `Enter` 发送，`Shift+Enter` 换行；输入法组合期间不得误发送。
- 空内容且无附件时发送按钮禁用。
- 生成中发送按钮切换为停止按钮，而不是简单禁用。
- 停止按钮具有明确 Tooltip 和 `aria-label="停止生成"`。
- 附件预览使用稳定高度或响应式约束，避免添加附件后工具栏跳动。
- 输入区聚焦使用平台 `focus-ring`，不得叠加厚重外发光。
- 免责声明放在输入框外部下方，使用说明文字层级。
- 空会话时隐藏无意义的清空按钮。
- 删除或清空已有草稿、附件时，根据后果使用直接操作或确认。
- 长工具名称进入菜单或弹出层，避免在紧凑工具栏中放置长文本按钮。

#### 35.5.2 工具状态

联网、深度思考、终端或技能属于模式状态，应使用：

- 图标切换按钮；
- 紧凑分段控制；
- 复选框或 Switch；
- 可展开的工具菜单。

不得把所有模式都实现成高强调文字按钮。

每个模式必须提供：

- 默认状态；
- hover；
- active；
- focus-visible；
- selected；
- disabled；
- 不可用原因 Tooltip；
- 必要的状态说明。

选中状态除颜色外，还需通过 `aria-pressed="true"`、图标变化、勾选标记或文本表达。

#### 35.5.3 文件引用

- `@` 引用文件时显示可搜索的工作区文件选择层。
- 用户路径必须通过 `formatUserPath()` 格式化。
- 搜索请求使用 `AbortController`，避免旧响应覆盖新关键词。
- 文件类型、大小和权限异常就地展示。
- 已引用文件以可移除项目展示，文件名长时省略并提供 Tooltip。
- 不向普通用户展示平台存储根目录。
- 引用失效或权限变化时，在发送前阻止请求并说明具体文件。

### 35.6 快捷任务卡片

快捷任务不是静态宣传卡片，而是预填输入、选择工具或直接进入流程的操作入口。

#### 35.6.1 内容要求

每张卡片包含：

- 与任务语义一致的图标；
- 动词开头的任务名称；
- 一行结果导向说明；
- 可选的文件或权限要求；
- 明确的触发行为。

示例：

| 任务 | 图标语义 | 说明 | 行为 |
| --- | --- | --- | --- |
| 浏览工作区文件 | 文件夹 | 查看可用于分析的数据 | 打开文件选择层 |
| 进行差异表达分析 | 分析图/烧瓶 | 比较样本分组并识别关键变化 | 预填提示词或打开配置流程 |
| 绘制相关性热图 | 网格/热图 | 检查样本间整体关系 | 预填提示词并请求选择数据 |
| 生成分析报告 | 文档 | 汇总过程、参数和主要结果 | 选择已有任务或结果 |

#### 35.6.2 样式要求

- 桌面端默认两列，`1024px` 以下根据空间降为一列。
- 卡片高度建议 `80px` 至 `96px`，使用稳定的 `min-height`。
- 图标容器使用 `40px` 或 `48px` 固定尺寸。
- 卡片间距使用 `12px` 或 `16px`。
- 使用语义图标，不以不同渐变色方块作为唯一辨识方式。
- hover 位移不超过 `2px`。
- focus-visible 使用平台焦点环。
- 整张卡片可点击时使用 `button` 或正确的可操作语义。
- 卡片内部不得再放置与主点击行为冲突的按钮。
- 不允许只有 hover 才显示关键说明或状态。

快捷任务触发方式必须明确选择以下一种：

1. 直接预填输入框，由用户确认发送。
2. 打开参数配置面板。
3. 直接进入已有工作流。
4. 打开文件或资源选择器。

不得点击后只弹出“功能开发中”之类的假反馈。未上线功能应禁用并提供 Tooltip。

### 35.7 最近上下文区域

为减少重复工作，空会话页可展示以下一种主内容：

- 最近会话；
- 最近使用文件；
- 最近分析任务；
- 推荐智能体。

默认优先级：

```text
最近会话 > 最近分析任务 > 最近文件 > 推荐智能体
```

最近会话每项至少展示：

- 会话标题；
- 助手或任务类型；
- 最后更新时间；
- 运行中、失败或完成状态；
- 打开行为；
- 更多操作菜单。

要求：

- 默认展示 3 至 5 项，不将空会话页变成完整历史列表。
- 标题长时省略并提供 Tooltip。
- 时间使用相对时间或统一的 `dayjs` 格式。
- 空状态提供“开始新对话”或选择快捷任务的入口。
- 加载失败时保留欢迎区和输入区，只在本区域显示重试。
- 删除会话使用 `NPopconfirm`，删除成功后局部刷新。
- 不使用假会话或 mock 数据填充视觉空白。

### 35.8 顶部助手工具栏

顶部栏建议分为三组：

```text
[返回] [助手头像、名称、状态]
                    [模型与推理设置] [视图和能力操作]
```

#### 35.8.1 助手上下文组

- 返回按钮使用图标按钮、Tooltip 和 `aria-label`。
- 助手名称使用 `16px / 24px / 600`。
- 说明使用 `12px` 或 `13px` 辅助文字。
- 连接状态、路由状态或权限状态使用文字加状态图标。
- 不把所有助手描述长期放在顶部栏中，避免占用垂直空间。

#### 35.8.2 模型设置组

模型选择、推理模式和超频模式视为同一组设置：

- 模型使用 Select 或菜单。
- 推理强度适合菜单或紧凑分段控制。
- 二元模式使用 Switch。
- 模型不可用时保留当前上下文并说明原因。
- 切换模型影响当前会话时，应提示上下文、计费或能力差异。
- 模型名称过长时省略，完整名称通过 Tooltip 展示。

#### 35.8.3 页面操作组

- “工作台模式”属于视图切换，使用分段控制或图标按钮。
- “查看智能体能力”使用次要按钮、抽屉或 Popover。
- 页面级操作不超过 3 个直接显示项，低频项进入更多菜单。
- 同一工具栏通常不出现多个实心品牌色按钮。
- `1024px` 以下将低频操作收进更多菜单。
- `640px` 以下只保留助手上下文和必要操作。

### 35.9 多层导航优化

AI 页面可能同时处于：

1. 平台顶部导航；
2. 全局侧栏；
3. AI 会话或工具侧栏。

必须明确三层职责：

| 层级 | 职责 |
| --- | --- |
| 平台顶部导航 | 产品域切换、账号、通知和帮助 |
| 全局侧栏 | 平台核心模块导航 |
| AI 侧栏 | 新建会话、历史会话、收藏和 AI 专属工具 |

实现要求：

- 全局折叠侧栏遵循 §5.6 的 `64px` 契约。
- AI 侧栏允许折叠，不应只保留无法理解的重复图标。
- 折叠后图标必须有 Tooltip。
- 会话列表展开宽度建议 `240px` 至 `280px`。
- AI 侧栏的折叠状态可持久化为用户偏好。
- 通知、帮助、设置和用户信息统一位于稳定区域。
- 同一图标不得代表多个不同模块。
- 导航图标优先使用 `@vicons/*` 中现有图标。
- 当前项选中态遵循平台连续描边和左缘状态线协议。
- 窄屏时 AI 侧栏改为 Drawer，不长期占据横向空间。
- 移动端 Drawer 关闭后焦点返回触发按钮。

### 35.10 AI 执行状态与工具调用

AI 主入口必须真实表达以下状态：

| 状态 | UI 表达 | 可用操作 |
| --- | --- | --- |
| 等待输入 | 空态输入区和快捷任务 | 输入、引用文件、选择任务 |
| 正在路由助手 | 状态文本和轻量加载 | 取消 |
| 正在生成 | 流式文本和停止按钮 | 停止 |
| 正在调用工具 | 工具卡片、参数摘要、进度 | 展开详情、取消（如支持） |
| 工具成功 | 成功状态、结果摘要 | 查看结果、下载或继续提问 |
| 工具失败 | 错误说明和失败步骤 | 重试、修改参数、查看日志 |
| 网络重连 | 保留内容并显示“重新连接中…” | 手动重连 |
| 生成中断 | 保留已生成内容和中断标记 | 重新生成 |
| 权限不足 | 明确权限要求 | 请求权限或选择其它资源 |
| 配额不足 | 剩余量和影响说明 | 查看配额或更换模式 |

工具卡片必须遵循 §18.4：

- 工具名；
- 参数摘要；
- 执行状态；
- 时间或耗时；
- 可折叠日志；
- 输出文件；
- 错误及重试路径。

不得只显示无限旋转图标而不说明当前执行步骤。

### 35.11 视觉层级与品牌使用

AI 主入口使用平台品牌色建立识别，但不得形成蓝紫色单一主题。

推荐语义：

- 品牌蓝：主要操作、焦点和助手身份。
- 紫色：深度思考、复杂推理等 AI 特征。
- 青色：数据探索或分析工具。
- 成功绿：任务完成和连接正常。
- 警告橙：排队、重连和可恢复异常。
- 错误红：失败、断开和破坏性操作。

要求：

- 页面背景使用 `--neutral-bg`。
- 输入区和任务卡片使用 `--neutral-card`。
- 边框使用 `--neutral-border`。
- 正文至少使用 `--neutral-text-2`，关键内容使用 `--neutral-text-1`。
- 不用辅助文本色承载重要任务说明。
- 阴影只用于输入聚焦、浮层和可点击卡片 hover。
- 不叠加多层外发光。
- 背景点阵、圆环和星点只保留一种装饰语言。
- 普通 AI 工作台不直接复用 §32 的完整 Hero 动画系统。
- 如使用静态 AI 氛围背景，必须保持低对比度并符合 §31。

### 35.12 响应式行为

#### 宽屏：`≥ 1200px`

- 保留全局侧栏和可选 AI 侧栏。
- 主内容最大宽度 `1120px` 或根据现有壳层调整。
- 快捷任务两列。
- 顶部工具栏完整展示主要设置。

#### 中等屏幕：`768px–1199px`

- AI 会话侧栏默认折叠或按用户偏好。
- 快捷任务可保持两列；内容不足时降为一列。
- 顶部低频操作进入更多菜单。
- 输入区保持全宽，不被侧栏挤压到不可用。

#### 窄屏：`< 768px`

- 页面内边距 `16px`。
- AI 侧栏转为 Drawer。
- 快捷任务单列。
- 欢迎区域取消复杂装饰。
- 模型和高级设置进入底部面板或菜单。
- 输入工具栏允许换行或使用横向操作菜单。
- 输入区工具栏必须避免文字按钮挤压。
- 触控目标不小于约 `40px`。
- 避免使用 `100vh`，优先使用 `100dvh` 并处理软键盘。
- 输入框聚焦后，发送按钮和文本输入仍保持可见。

#### 最低桌面高度：`720px`

必须验证：

- 欢迎区、输入区和至少一行快捷任务可在首屏操作。
- 不因固定高度导致输入区与欢迎区之间出现大面积空白。
- 浏览器缩放至 `125%` 时主要操作仍可见。

### 35.13 可访问性

- 页面只有一个 `h1`，通常为当前助手名称。
- 快捷任务区使用 `section` 和 `h2`。
- 可点击任务卡片优先使用 `button`。
- 纯图标按钮提供 Tooltip 和 `aria-label`。
- 模式切换使用 `aria-pressed`。
- 助手路由、生成和连接状态使用 `aria-live="polite"`。
- 流式输出避免每个 token 都触发屏幕阅读器朗读；只对状态摘要使用 live region。
- 停止生成按钮必须可通过键盘到达。
- 消息列表、附件条和弹出菜单具备合理焦点顺序。
- 弹层关闭后焦点返回触发按钮。
- 高对比度模式下保留输入区、卡片和选中状态边界。
- 减少透明度模式下输入区和顶部栏使用实体表面。
- 减少动态模式下停止光标之外的装饰循环和大位移转场。

### 35.14 数据与状态管理建议

AI 主入口的状态建议按以下边界拆分：

| 状态 | 建议位置 |
| --- | --- |
| 当前会话 ID、消息、流式连接状态 | AI 对话 Store 或现有流式 composable |
| 输入草稿、展开菜单、局部 hover | 组件本地 |
| 当前模型、推理偏好 | Store 或用户偏好 |
| 快捷任务定义 | 配置文件或助手能力接口 |
| 最近会话 | 页面请求状态 |
| 引用文件和附件 | Composer 受控状态 |
| 工作台模式 | 路由 query、Store 或页面状态，按是否需跨页面保留决定 |

要求：

- 会话创建、消息发送、停止生成和重新生成使用明确的 action。
- 切换会话前保存或确认未发送草稿。
- 发送请求防止重复提交。
- SSE/WebSocket 断开后保留已有消息。
- 组件卸载时取消请求、流和事件监听。
- 最近会话局部失败不得阻塞输入区。
- 多个独立请求使用 `Promise.allSettled`。

### 35.15 建议组件边界

优先复用现有实现；确有重复时，可按以下方式拆分：

```text
frontend/src/components/ai/
├── AIAssistantHeader.vue
├── AIComposer.vue
├── AIComposerToolbar.vue
├── AIAttachmentStrip.vue
├── AIQuickActions.vue
├── AIRecentSessions.vue
├── AIMessageList.vue
├── AIToolCallCard.vue
└── AIConnectionStatus.vue
```

拆分纪律：

- 不为单次样式调整创建大量无复用价值的包装组件。
- `AIComposer` 负责布局和交互契约，不直接发起业务 API。
- 页面负责组合数据和调用现有 Store/composable。
- 快捷任务通过结构化配置传入，不在模板中复制四套卡片。
- 消息渲染和工具卡片与输入区解耦。
- 组件事件使用明确名称，例如 `send`、`stop`、`attach`、`select-action`。
- 不使用事件总线。

建议类型：

```ts
export interface AIQuickAction {
  id: string
  title: string
  description: string
  icon: Component
  behavior: 'prefill' | 'configure' | 'navigate' | 'select-file'
  prompt?: string
  route?: RouteLocationRaw
  disabled?: boolean
  disabledReason?: string
}
```

### 35.16 分阶段实施计划

#### 第一阶段：首屏任务路径

目标：解决输入区远离欢迎区和大面积空白问题。

工作项：

- 识别空会话和活跃会话状态。
- 空会话输入区移动到欢迎区下方。
- 活跃会话保持底部吸附输入区。
- 统一欢迎区、输入区和快捷任务的内容边界。
- 压缩欢迎横幅高度和冗余文案。
- 移除无语义关闭按钮。
- 删除空会话无效的清空控件。
- 完成桌面端和 `720px` 高度验证。

验收标准：

- 用户进入页面后无需移动视线到底部即可开始输入。
- 空会话首屏至少可看到输入区和一组快捷任务。
- 开始对话后输入区保持稳定可用。
- 布局切换不丢失草稿和附件。

#### 第二阶段：快捷任务和输入工具栏

目标：提升任务辨识度并降低控制密度。

工作项：

- 快捷卡片改为语义图标和动词文案。
- 快捷任务改为配置驱动。
- 为每个快捷任务定义真实行为。
- 输入工具栏按附件、模式和发送操作分组。
- 将低频长文字操作移入更多菜单。
- 为模式按钮补充 selected、disabled、Tooltip 和 ARIA。
- 整理免责声明位置。

验收标准：

- 每张快捷卡片点击后均有真实、可预测行为。
- 键盘可以完成快捷任务选择和消息发送。
- 工具栏在 `375px` 下不发生文字裁切和按钮重叠。
- 空内容、生成中和断网状态下发送/停止行为正确。

#### 第三阶段：导航与最近上下文

目标：降低多层导航认知成本，提高任务续接效率。

工作项：

- 明确全局导航和 AI 侧栏职责。
- AI 侧栏支持折叠和移动端 Drawer。
- 补充图标 Tooltip。
- 处理重复图标和低频入口。
- 空会话增加最近会话或最近任务。
- 实现加载、空、失败和删除状态。

验收标准：

- 折叠状态下所有图标都可理解。
- 最近会话失败不影响发起新对话。
- 移动端 Drawer 具备焦点管理。
- 页面切换不残留 WebSocket 和请求。

#### 第四阶段：流式状态与工具卡片

目标：让复杂 AI 任务过程可理解、可停止、可恢复。

工作项：

- 完善路由助手、生成、停止和中断状态。
- 统一工具调用卡片。
- 接入进度、日志、结果和重试。
- 处理 WebSocket/SSE 重连。
- 用户上滚时暂停自动滚动。
- 提供回到底部按钮。
- 长会话引入分页或虚拟滚动。

验收标准：

- 网络中断后已生成内容不会丢失。
- 每个长任务至少显示当前步骤或不确定进度。
- 工具失败提供明确重试路径。
- 流式更新不会导致整页频繁重渲染。

#### 第五阶段：主题、可访问性与性能

目标：完成平台级交付质量。

工作项：

- 浅色和深色主题核对。
- `375px`、`768px`、`1024px`、`1280px` 和宽屏核对。
- `1280×720` 与浏览器 `125%` 缩放核对。
- 键盘和屏幕阅读器语义检查。
- 减少动态、减少透明度和高对比度检查。
- 检查路由 chunk 体积和首屏请求。
- 完成组件测试和关键 E2E。

### 35.17 AI 主入口专项验收清单

- [ ] 空会话输入区是否位于欢迎说明附近，而非固定在视口最底部？
- [ ] 活跃会话输入区是否稳定吸附并与消息主列对齐？
- [ ] 页面是否只有一个主要视觉动作，且通常为发送？
- [ ] 欢迎区是否不超过必要高度，并移除了无语义关闭按钮？
- [ ] 快捷任务是否使用语义图标、动词文案和真实行为？
- [ ] 快捷任务是否可通过键盘操作，并具有 focus-visible？
- [ ] 输入工具栏是否按附件、模式和发送操作分组？
- [ ] 空输入、生成中、停止中、断网和重连状态是否正确？
- [ ] 输入法组合期间按 Enter 是否不会误发送？
- [ ] 引用文件是否经过 `formatUserPath()` 处理？
- [ ] 最近会话加载失败是否不会阻塞新对话？
- [ ] AI 侧栏是否可折叠，并在移动端转为 Drawer？
- [ ] 所有纯图标是否提供 Tooltip 或 `aria-label`？
- [ ] 工具调用是否展示工具名、参数摘要、状态、结果和错误？
- [ ] 网络中断是否保留已生成内容并提供重试？
- [ ] 用户上滚时是否暂停自动滚动并提供“回到底部”？
- [ ] 是否避免蓝紫单色主导，并按语义使用成功、警告和错误色？
- [ ] 装饰背景是否符合 §31，没有参与布局或拦截点击？
- [ ] `375px`、`768px`、`1024px`、`1280×720` 是否无重叠和裁切？
- [ ] 是否验证浅色、深色、减少动态、减少透明度和高对比度？
- [ ] 是否通过 type-check、build、测试和 `git diff --check`？
- [ ] 是否在实际路由 chunk 或 nginx 响应中确认样式已生效？

## 36. AI 助手主入口优化执行提示词

下面建议继续追加到 `fontend.md`。第一份用于完整改造，后面几份用于拆分执行，避免一次修改范围过大。

```md
### 36.1 完整优化提示词

使用 `$cygnusx-frontend-design` 对 CygnusX 的星尘 AI 主入口进行完整优化。

开始前必须先阅读并遵守：

- 仓库中的 `AGENTS.md`；
- `fontend.md`，重点检查 §1、§2、§3、§5、§6、§7、§10、§14、§18、§21、§22、§23、§31、§33、§35；
- `frontend/src/styles/tokens.css`；
- `frontend/src/styles/global.css`；
- `frontend/src/App.vue`；
- `frontend/src/layouts/DefaultLayout.vue`；
- 当前 AI 页面、输入组件、消息组件、AI Store 和流式 composable。

任务目标：

1. 将 AI 空会话页从“欢迎横幅 + 快捷卡片 + 大面积空白 + 底部输入框”调整为连续任务路径：
   - 助手信息；
   - 空会话输入区；
   - 快捷任务；
   - 最近会话或最近任务。
2. 存在消息后切换为标准对话布局：
   - 顶部助手工具栏；
   - 可滚动消息区；
   - 底部吸附输入区。
3. 保持草稿、附件、模型和模式状态在布局切换时不丢失。
4. 压缩欢迎区高度，减少营销式装饰和冗余文案；没有真实关闭语义时移除关闭按钮。
5. 快捷任务改为结构化配置驱动，使用语义图标、动词文案和真实行为。
6. 输入工具栏按附件、引用、模式、清空和发送分组；将低频长文字操作收入更多菜单。
7. 顶部模型、推理和超频设置归为同组；工作台模式与能力查看归为页面操作组。
8. 页面只能有一个最强操作层级，发送按钮优先。
9. AI 侧栏支持折叠；移动端使用 Drawer；所有纯图标提供 Tooltip 和 `aria-label`。
10. 补全 default、hover、active、focus-visible、selected、disabled、loading、empty、error、success、streaming、stopped 和 reconnecting 状态。
11. 保留现有真实 API、Store、路由和流式逻辑，不用 mock 数据替换真实数据。
12. 用户路径统一使用 `formatUserPath()`，不暴露平台存储根目录。
13. 装饰层严格遵守 §31，不使用 `.container > *` 等过宽选择器改变定位或层叠。
14. 不新增依赖，除非先证明现有依赖无法满足需求。
15. 不在业务组件中硬编码浅色主题颜色，不使用大面积 `!important` 或深层穿透覆盖组件库。
16. 不修改 §34 冻结的知识库阅读页三要素。

实现方式：

- 先列出当前 AI 主入口相关文件、状态流和组件边界。
- 说明现状问题与准备修改的文件。
- 优先复用现有组件和样式令牌。
- 只在至少两个位置复用或确实能降低复杂度时提取共享组件。
- 新组件使用 Vue 3、TypeScript、`<script setup lang="ts">` 和 Composition API。
- 输入区使用受控状态，组件不得自行复制会话业务逻辑。
- 快捷任务使用结构化类型，不复制四套模板。
- 所有异步请求支持局部 loading、失败和重试；页面卸载时清理请求、流和监听。
- 流式输出使用现有 `useChatStream` / `useAgentChatStream` 或对应 Store，不另造并行连接机制。
- 样式只使用语义令牌和平台间距阶梯。
- 空会话输入区不固定在视口底部；活跃会话输入区使用可靠的 sticky 或现有布局。
- 使用 `100dvh` 处理移动端软键盘，不使用会裁剪内容的固定 `100vh`。
- 动效只使用 `transform` 和 `opacity`，并适配 `prefers-reduced-motion`。

响应式必须覆盖：

- `375px` 手机；
- `768px` 平板；
- `1024px` 窄桌面；
- `1280×720` 最低桌面环境；
- `1440px` 常规桌面；
- 宽屏；
- 浏览器缩放 `125%`。

验收要求：

1. 运行项目现有的前端类型检查。
2. 运行相关单元测试和组件测试。
3. 运行前端构建。
4. 运行 `git diff --check`。
5. 使用 Playwright 分别截取空会话和活跃会话的桌面、移动端截图。
6. 检查页面无文字裁切、按钮重叠、横向溢出和无功能空白。
7. 检查键盘 Tab 顺序、Enter 发送、Shift+Enter 换行、输入法组合和 Escape 关闭弹层。
8. 检查浅色、深色、减少动态、减少透明度和高对比度。
9. 按 §31.5 在实际构建产物中定位 AI 路由 CSS chunk，并确认关键选择器已编译。
10. 报告修改文件、关键行为、验证命令、截图位置和仍存在的风险。

不要只输出建议或代码片段。完成代码修改、测试、构建和页面检查后再结束任务。
```

### 36.2 第一阶段提示词：首屏与输入区

```text
使用 $cygnusx-frontend-design 优化星尘 AI 主入口的首屏任务路径。

只处理以下范围：
1. 区分空会话与已有消息状态。
2. 空会话时把输入区放到助手说明下方，禁止固定在页面底部。
3. 有消息后输入区切换到底部吸附布局。
4. 统一助手说明、输入区和快捷任务的左右内容边界。
5. 压缩欢迎横幅高度，移除无语义的关闭按钮和冗余英文装饰文案。
6. 保持现有发送、附件、模型、工具、WebSocket/SSE 和会话逻辑不变。
7. 布局切换不得丢失输入草稿或附件。
8. 处理 375px、768px、1024px、1280×720 和 1440px。
9. 适配深色模式、减少动态和减少透明度。
10. 严格遵守 fontend.md §31，不用子元素通配选择器修改 position/z-index。

先阅读当前实现和设计令牌，再直接修改代码。完成后运行 type-check、相关测试、build 和 git diff --check，并用 Playwright 截取空会话与活跃会话的桌面/移动端截图。
```

### 36.3 第二阶段提示词：快捷任务与工具栏

```text
使用 $cygnusx-frontend-design 优化星尘 AI 的快捷任务和输入工具栏。

任务：
1. 将快捷任务改为结构化配置驱动。
2. 每项使用 @vicons 现有语义图标、动词标题、一行结果说明和明确 behavior。
3. behavior 限定为 prefill、configure、navigate、select-file。
4. 所有入口必须接入真实行为；未上线功能使用 disabled + Tooltip，不弹假 toast。
5. 桌面端两列，窄屏单列，卡片高度稳定，无文字裁切。
6. 整卡可点击时使用正确语义，并支持 Enter、Space、focus-visible。
7. 输入工具栏按附件/引用、模式、发送操作分组。
8. 将“转为协作 Case”等低频长文字操作移入更多菜单。
9. 联网、工具、深度思考等模式补齐 aria-pressed、selected、disabled 和不可用原因。
10. 空会话隐藏无效清空按钮；免责声明移到输入框外。
11. 不改动消息流和后端接口契约。

完成 type-check、测试、build、git diff --check 和桌面/移动端截图检查。
```

### 36.4 第三阶段提示词：导航与最近会话

```text
使用 $cygnusx-frontend-design 优化星尘 AI 页面的多层导航和最近上下文。

任务：
1. 梳理平台顶部导航、全局侧栏和 AI 侧栏的职责。
2. 保持 DefaultLayout 的全局侧栏契约，不破坏其它路由。
3. AI 侧栏支持折叠并持久化偏好；移动端改为 Drawer。
4. 折叠后的所有图标提供 Tooltip 和 aria-label。
5. 排查并替换重复或语义不清的图标。
6. 空会话页增加最近会话，默认 3 至 5 项。
7. 每项展示标题、助手/任务类型、更新时间和状态。
8. 实现 loading、empty、error、retry、open 和 delete 状态。
9. 删除使用 NPopconfirm，成功后局部刷新。
10. 最近会话失败不得阻塞输入和快捷任务。
11. 只使用真实 API，不使用 mock 数据填充。
12. Drawer 打开时管理焦点，关闭后焦点返回触发元素。

完成类型检查、测试、构建和响应式/键盘验收。
```

### 36.5 第四阶段提示词：流式输出与工具调用

```text
使用 $cygnusx-frontend-design 完善星尘 AI 的流式输出、连接状态和工具调用卡片。

任务：
1. 复用现有 useChatStream、useAgentChatStream、AI Store 或 WebSocket composable。
2. 明确 waiting、routing、streaming、tool-running、stopped、reconnecting、failed 和 completed 状态。
3. 生成中发送按钮切换为停止按钮。
4. 用户停止或网络中断后保留已输出内容。
5. 提供重新生成和手动重连入口。
6. 工具卡片显示工具名、参数摘要、执行步骤、耗时、结果、输出文件和错误。
7. 长任务显示确定或不确定进度；不能只显示无限 spinner。
8. 工具失败提供重试、修改参数或查看日志的真实路径。
9. 用户向上滚动时暂停自动滚动并显示“回到底部”。
10. 长会话使用历史分页或现有虚拟滚动方案。
11. 高频更新使用 shallowRef 和 requestAnimationFrame 节流。
12. 页面卸载时关闭连接、取消请求并清理监听。
13. 状态摘要使用 aria-live，避免逐 token 朗读。

补充相应单元/组件测试，并完成构建和关键 E2E 验证。
```

### 36.6 只做审查、不修改代码的提示词

```text
使用 $cygnusx-frontend-design 审查 CygnusX 星尘 AI 主入口，但暂不修改代码。

重点检查：
- 空会话与活跃会话布局；
- 输入区优先级和键盘行为；
- 快捷任务真实行为；
- 顶部工具栏操作层级；
- 多层导航职责；
- 流式输出与工具调用状态；
- 深色模式和语义令牌；
- 375px、768px、1024px、1280×720 和宽屏；
- 减少动态、减少透明度、高对比度和键盘可访问性；
- WebSocket/SSE 清理和断线恢复；
- §31 叠层反模式；
- 性能和路由块体积。

输出格式：
1. 按 P0、P1、P2、P3 排序的问题清单。
2. 每个问题给出真实文件和行号。
3. 说明用户影响、技术原因和推荐修复。
4. 给出按依赖关系排序的实施批次。
5. 给出每批次的验收标准和建议测试。
6. 不输出泛化视觉建议，不臆测不存在的接口或组件。
```

另外建议修正文件名：如果当前仓库实际叫 `fontend.md`，最好迁移为正确拼写的 `frontend.md`，并同步 `$cygnusx-frontend-design`、`AGENTS.md` 和其它文档中的引用。如果已有自动化脚本依赖旧文件名，则先保留一个短的兼容入口，避免技能引用失效。
