# PrimerForge 引物设计模块架构说明

> 状态：现阶段前端本地引物设计工作台已接入工具箱；后端 Primer3 / BLAST / 邮件发送能力预留接口，尚未落地为服务端依赖。

## 1. 模块定位

PrimerForge 是 OmicHub 生信工具箱中的引物设计模块，入口为：

- 工具箱卡片：`/tools`
- 工具页面：`/tools/primer-forge`
- 工具 key：`primer-forge`

当前目标是先提供可用的本地引物设计体验，覆盖常规 PCR、qPCR 和 TaqMan 探针的候选筛选、序列定位、结果表格、报告导出与合成订单草稿生成。后续再把计算核心替换或增强为后端 Primer3 引擎。

## 2. 当前文件布局

```text
tool_configs/
├── tools_setting.yaml                # 工具箱卡片注册，包含 primer-forge
└── primer/
    └── README.md                     # 当前架构说明

frontend/src/
├── router/index.ts                   # 注册 /tools/primer-forge 路由
├── views/BioTools/
│   ├── ToolsHubView.vue              # GitNetworkOutline 图标映射
│   └── PrimerForgeView.vue           # 引物设计工具页面
└── utils/
    └── primerForgeProcessor.ts       # 本地引物设计核心、报告与订单生成
```

## 3. 前端架构

### 3.1 页面层

`frontend/src/views/BioTools/PrimerForgeView.vue` 负责 UI 与交互编排：

- 工具栏：返回工具箱、示例数据、参数重置。
- 左侧参数面板：序列输入、任务类型、引物参数、热力学参数、高级约束、TaqMan 探针参数。
- 中间工作区：线性序列位置图、局部碱基窗口、候选引物表格。
- 右侧辅助栏：候选统计、诊断提示、快捷操作、选中引物详情。
- 抽屉：合成公司选择、合成参数、订单邮件草稿生成与复制。

页面遵循 `tool_configs/tools_design.md` 的三栏紧凑布局规范，技术栈为 Vue 3 `<script setup lang="ts">` + Naive UI + Vue Router。

### 3.2 处理器层

`frontend/src/utils/primerForgeProcessor.ts` 是无 Vue 依赖的纯函数层，当前负责：

- FASTA / DNA 序列解析与清洗。
- 序列统计：长度、GC%、N 数量。
- 任务默认参数：PCR / qPCR / sequencing / cloning。
- 候选正向引物与反向引物枚举。
- Tm、GC%、Poly-X、自互补、3' 互补、末端稳定性粗略计算。
- 引物对组合、产物长度过滤、目标区域覆盖、排除区域避让。
- qPCR 探针候选筛选。
- 综合评分、预警信息与诊断信息生成。
- Excel 可打开的 HTML 报告导出。
- 合成订单邮件草稿生成。

该层后续可以作为前端 fallback，也可以逐步切换为只负责展示格式化，把核心设计请求交给后端 Primer3 API。

## 4. 当前数据流

```text
用户输入 FASTA / DNA
        │
        ▼
PrimerForgeView.vue
  - 收集任务类型与参数
  - 解析目标区域 / 排除区域
        │
        ▼
primerForgeProcessor.ts
  - cleanDnaSequence / parseFastaInput
  - enumerateCandidates
  - evaluatePrimer
  - pair scoring
  - optional probe finding
        │
        ▼
PrimerDesignResult
        │
        ├── 序列位置图
        ├── 结果表格
        ├── 右侧统计与详情
        ├── 本地历史 localStorage
        ├── Excel 报告导出
        └── 合成订单草稿
```

## 5. 核心数据模型

当前前端核心类型定义在 `primerForgeProcessor.ts`：

- `PrimerTaskType`：任务类型，包含 `PCR`、`qPCR`、`sequencing`、`cloning`。
- `PrimerDesignInput`：页面传入处理器的完整设计请求。
- `PrimerParameters`：引物长度、Tm、GC、产物长度、返回数量等参数。
- `ThermodynamicParameters`：盐浓度、dNTP、DNA 浓度、Poly-X 等参数。
- `AdvancedParameters`：自身互补、引物对互补与评分权重。
- `ProbeParameters`：TaqMan 探针长度、Tm、GC、荧光/淬灭标记。
- `PrimerInfo`：单条引物或探针的序列、位置、Tm、GC、互补性与预警。
- `PrimerPair`：正反引物、可选探针、产物位置、评分与预警。
- `PrimerDesignResult`：页面渲染所需的完整结果对象。

字段命名使用前端 TypeScript camelCase；若后端 Primer3 API 落地，可在 API 层做 snake_case / camelCase 映射。

## 6. 工具箱接入点

### 6.1 注册表

`tool_configs/tools_setting.yaml` 中新增：

```yaml
- key: "primer-forge"
  title: "PrimerForge 引物锻造工坊"
  icon: "GitNetworkOutline"
  route: "/tools/primer-forge"
  enabled: true
  order: 62
  config_dir: ""
```

当前 `config_dir` 为空，表示没有后端 YAML 功能配置。若后续加入服务端配置，可改为：

```yaml
config_dir: "tool_configs/primer"
```

### 6.2 路由

`frontend/src/router/index.ts` 中注册：

```ts
{
  path: 'tools/primer-forge',
  name: 'tools-primer-forge',
  component: () => import('@/views/BioTools/PrimerForgeView.vue'),
  meta: { title: 'PrimerForge 引物锻造工坊', requiresAuth: true }
}
```

### 6.3 图标

`frontend/src/views/BioTools/ToolsHubView.vue` 中登记 `GitNetworkOutline`，使 YAML 字符串 icon 能映射为 Vue 图标组件。

## 7. 现阶段能力边界

当前版本是前端启发式设计器，不等价于 Primer3：

- Tm 计算使用 Wallace / 简化 SantaLucia 近似公式。
- 自互补与 3' 互补为连续互补片段粗筛。
- 发夹结构、二聚体热力学、错配库、物种特异性验证尚未接入。
- Excel 导出采用 HTML table 生成 `.xls`，可由 Excel 打开，不依赖后端 `openpyxl`。
- 合成助手当前生成本地邮件草稿，不直接调用 AI Provider，也不发送 SMTP 邮件。

这些限制是有意保留的第一阶段边界，避免在当前依赖中引入 `primer3-py`、BLAST+、邮件配置和 AI 调用链。

## 8. 后端演进方案

后续若要落地 Primer3 后端，建议新增：

```text
src/omichub/tools/primer/
├── __init__.py
├── api.py                         # prefix = "/primer"
├── schema.py                      # Pydantic DTO
├── service.py                     # Primer3 调用、结果转换
├── export.py                      # openpyxl 报告
├── order.py                       # AI 订单生成
└── config.py                      # 合成公司 / SMTP / BLAST 配置加载
```

建议 API：

```text
POST /api/v1/primer/design         # Primer3 引物设计
POST /api/v1/primer/validate       # 单条引物验证
POST /api/v1/primer/blast          # 特异性验证
POST /api/v1/primer/export/excel   # 后端 Excel 报告
POST /api/v1/primer/ai-order       # AI 订单文案
POST /api/v1/primer/mail/send      # SMTP 邮件发送
GET  /api/v1/primer/history        # 历史记录
POST /api/v1/primer/history        # 保存历史
```

后端工具路由会被 `omichub.tools.register_tool_routers` 自动发现，只要 `src/omichub/tools/primer/api.py` 暴露 `router`、`prefix`、`tags` 即可，无需修改 `src/omichub/api/v1/router.py`。

## 9. 建议分阶段路线

1. 保留当前前端本地设计器作为 fallback。
2. 新增 `/api/v1/primer/design`，安装并封装 `primer3-py>=2.0.3`。
3. 前端 `runDesign()` 优先调用后端，失败时回退到 `designPrimers()`。
4. 增加 `tool_configs/primer/primer_config.yaml`，集中维护任务默认参数和合成公司配置。
5. 增加后端 `openpyxl` 导出，替换前端 HTML `.xls`。
6. 接入 BLAST 特异性验证，优先支持本地 BLAST+ 数据库，远程 NCBI 作为低频补充。
7. 接入 AI 订单生成与 SMTP 发送，发送前必须要求用户确认。

## 10. 验证状态

当前前端构建已通过：

```bash
cd frontend
npm run build
```

构建结果证明新增页面、路由、图标映射和 TypeScript 类型当前可编译。
