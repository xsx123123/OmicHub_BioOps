/**
 * 湿实验计算器核心算法（纯函数，无 Vue 依赖）。
 *
 * 覆盖 12 个子计算器（四大类）：
 * PCR / 克隆：
 *   1. 母液稀释 C1V1 = C2V2
 *   2. qPCR 相对表达 2^-ΔΔCt
 *   3. PCR 体系与 Master Mix 批量配制
 *   4. 载体/片段连接反应摩尔比 (Ligation)
 *   5. DNA / RNA 绝对拷贝数
 * NGS 建库：
 *   6. NGS 文库等摩尔 Pooling
 *   7. 磁珠纯化与选段比例 (AMPure XP)
 * 序列处理：
 *   8. 引物 Tm / 反向互补 / GC%
 * 溶液 / 缓冲液：
 *   9. 摩尔浓度 / 质量 / 体积换算
 *  10. 核酸浓度 ng/µL ↔ nM 换算
 *  11. 离心机转速 RPM ↔ 相对离心力 RCF
 *  12. 常用缓冲液配方生成器
 */

// ---------------------------------------------------------------------------
// 通用格式化
// ---------------------------------------------------------------------------

/**
 * 数值格式化：普通范围保留 significantDigits 位有效数字；
 * 过大 / 过小（>=1e6 或 <1e-3）用科学计数法。非法值返回 '—'。
 */
export function formatNum(n: number | null | undefined, significantDigits = 4): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—'
  if (n === 0) return '0'
  const abs = Math.abs(n)
  if (abs >= 1e6 || abs < 1e-3) {
    return n.toExponential(3)
  }
  return String(+n.toPrecision(significantDigits))
}

/** 解析用户输入为有限正数；非法返回 null。 */
export function parsePositive(raw: string | number | null | undefined, allowZero = false): number | null {
  if (raw === null || raw === undefined || raw === '') return null
  const v = typeof raw === 'number' ? raw : Number(String(raw).trim())
  if (!Number.isFinite(v)) return null
  if (allowZero ? v < 0 : v <= 0) return null
  return v
}

// ---------------------------------------------------------------------------
// 子计算器 1：母液稀释 C1V1 = C2V2
// ---------------------------------------------------------------------------

/** 浓度单位（统一折算为 µM；ng/µL 按 1 µg/mL ≈ 与 nM 无关，仅做同单位换算） */
export const DIL_CONC_UNITS = ['µM', 'nM', 'ng/µL'] as const
export type DilConcUnit = (typeof DIL_CONC_UNITS)[number]

/** 体积单位（统一折算为 µL） */
export const DIL_VOL_UNITS = ['µL', 'mL'] as const
export type DilVolUnit = (typeof DIL_VOL_UNITS)[number]

function concToMicroM(v: number, unit: DilConcUnit): number {
  if (unit === 'nM') return v / 1000
  return v // µM 与 ng/µL 视作“同单位”基准，仅同单位间计算
}

function volToMicroL(v: number, unit: DilVolUnit): number {
  return unit === 'mL' ? v * 1000 : v
}

export interface DilutionInput {
  c1: number | null
  c2: number | null
  v2: number | null
  concUnit: DilConcUnit
  volUnit: DilVolUnit
}

export interface DilutionResult {
  valid: boolean
  error: string | null
  /** 需取母液体积（µL） */
  v1uL: number
  /** 需加溶剂体积（µL） */
  solventuL: number
  /** 母液占终体积比例 % */
  ratio: number
}

/** C1V1 = C2V2 求解：V1 = C2·V2 / C1，加水量 = V2 - V1。 */
export function solveDilution(input: DilutionInput): DilutionResult {
  const empty: DilutionResult = { valid: false, error: null, v1uL: 0, solventuL: 0, ratio: 0 }
  const { c1, c2, v2, concUnit, volUnit } = input
  if (c1 === null || c2 === null || v2 === null) return empty
  if (c1 <= 0 || c2 <= 0 || v2 <= 0) return { ...empty, error: '所有数值必须为正数' }
  if (concToMicroM(c2, concUnit) > concToMicroM(c1, concUnit)) {
    return { ...empty, error: '目标浓度 C2 不能大于母液浓度 C1' }
  }
  const v2uL = volToMicroL(v2, volUnit)
  const v1uL = (concToMicroM(c2, concUnit) * v2uL) / concToMicroM(c1, concUnit)
  return {
    valid: true,
    error: null,
    v1uL,
    solventuL: v2uL - v1uL,
    ratio: (v1uL / v2uL) * 100,
  }
}

// ---------------------------------------------------------------------------
// 子计算器 2：qPCR 相对表达 2^-ΔΔCt
// ---------------------------------------------------------------------------

/** 原始 Ct 行：样本名 | 分组 | 目的基因 Ct | 内参基因 Ct（Tab 分隔，支持 Excel 粘贴） */
export interface CtRawRow {
  sample: string
  group: string
  targetCt: number
  refCt: number
}

export interface CtParseResult {
  rows: CtRawRow[]
  /** 被跳过的行号（1-based，含表头/格式错误行） */
  skipped: number[]
  groups: string[]
}

/**
 * 解析 Ct 表格文本（Tab 分隔，兼容逗号/多空格；自动跳过表头行）。
 */
export function parseCtTable(text: string): CtParseResult {
  const rows: CtRawRow[] = []
  const skipped: number[] = []
  const lines = text.split('\n')
  lines.forEach((line, idx) => {
    const trimmed = line.trim()
    if (!trimmed) return
    const cols = trimmed.includes('\t') ? trimmed.split('\t') : trimmed.split(/[,;]|\s{2,}/)
    if (cols.length < 4) {
      skipped.push(idx + 1)
      return
    }
    const target = Number(cols[2].trim())
    const ref = Number(cols[3].trim())
    if (!Number.isFinite(target) || !Number.isFinite(ref)) {
      skipped.push(idx + 1) // 表头或非数值行
      return
    }
    rows.push({
      sample: cols[0].trim() || `样本${rows.length + 1}`,
      group: cols[1].trim() || '未分组',
      targetCt: target,
      refCt: ref,
    })
  })
  return { rows, skipped, groups: [...new Set(rows.map((r) => r.group))] }
}

export interface QpcrDetailRow extends CtRawRow {
  key: string
  dCt: number
  ddCt: number
  /** 2^-ΔΔCt 相对表达量 */
  relExp: number
}

export interface QpcrGroupStat {
  group: string
  n: number
  mean: number
  sd: number
  sem: number
}

export interface QpcrResult {
  details: QpcrDetailRow[]
  groupStats: QpcrGroupStat[]
  controlGroup: string
  controlMeanDCt: number
}

/**
 * 2^-ΔΔCt 计算：
 * ΔCt = 目的基因 Ct - 内参 Ct（同一行）
 * 对照组 ΔCt 均值 → ΔΔCt = ΔCt - 对照均值 → 相对表达 = 2^-ΔΔCt
 */
export function computeQpcr(rows: CtRawRow[], controlGroup: string): QpcrResult | { error: string } {
  const controlRows = rows.filter((r) => r.group === controlGroup)
  if (!rows.length) return { error: '没有有效数据行' }
  if (!controlRows.length) return { error: `对照组「${controlGroup}」不存在` }
  const controlMeanDCt =
    controlRows.reduce((s, r) => s + (r.targetCt - r.refCt), 0) / controlRows.length

  const details: QpcrDetailRow[] = rows.map((r, i) => {
    const dCt = r.targetCt - r.refCt
    const ddCt = dCt - controlMeanDCt
    return {
      ...r,
      key: `${r.sample}-${i}`,
      dCt,
      ddCt,
      relExp: Math.pow(2, -ddCt),
    }
  })

  const byGroup = new Map<string, number[]>()
  details.forEach((d) => {
    const arr = byGroup.get(d.group) ?? []
    arr.push(d.relExp)
    byGroup.set(d.group, arr)
  })
  const groupStats: QpcrGroupStat[] = [...byGroup.entries()].map(([group, vals]) => {
    const n = vals.length
    const mean = vals.reduce((s, v) => s + v, 0) / n
    const sd =
      n > 1 ? Math.sqrt(vals.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1)) : 0
    return { group, n, mean, sd, sem: n > 1 ? sd / Math.sqrt(n) : 0 }
  })
  // 对照组排最前
  groupStats.sort((a, b) => (a.group === controlGroup ? -1 : b.group === controlGroup ? 1 : 0))
  return { details, groupStats, controlGroup, controlMeanDCt }
}

/** qPCR 示例数据（3 样本 × 2 组，内参 ACTB，含技术重复）。 */
export function genSampleCtData(): string {
  return [
    '样本名\t分组\t目的基因Ct\t内参Ct',
    'Ctrl-1\t对照组\t22.35\t17.12',
    'Ctrl-2\t对照组\t22.48\t17.25',
    'Ctrl-3\t对照组\t22.19\t17.08',
    'Treat-1\t处理组\t19.82\t17.31',
    'Treat-2\t处理组\t20.05\t17.44',
    'Treat-3\t处理组\t19.67\t17.19',
  ].join('\n')
}

// ---------------------------------------------------------------------------
// 子计算器 3：摩尔浓度 / 质量 / 体积换算
// ---------------------------------------------------------------------------

export type MolarTarget = 'mass' | 'volume' | 'conc' | 'mw'

/** 质量单位折算到 g */
export const MASS_FACTORS: Record<string, number> = { g: 1, mg: 1e-3, 'µg': 1e-6 }
/** 体积单位折算到 L */
export const VOL_FACTORS: Record<string, number> = { L: 1, mL: 1e-3, 'µL': 1e-6 }
/** 浓度单位折算到 mol/L */
export const CONC_FACTORS: Record<string, number> = { M: 1, mM: 1e-3, 'µM': 1e-6, nM: 1e-9 }

export interface MolarInput {
  target: MolarTarget
  /** 分子量 g/mol */
  mw: number | null
  mwUnit?: string
  /** 质量（单位见 massUnit） */
  mass: number | null
  massUnit: string
  /** 体积 */
  volume: number | null
  volUnit: string
  /** 浓度 */
  conc: number | null
  concUnit: string
}

export interface MolarResult {
  valid: boolean
  error: string | null
  /** 求解结果（SI 基准：g / L / mol/L / g/mol） */
  value: number
  label: string
  unit: string
}

/**
 * 四项换算：n = m/MW，c = n/V。
 * 用户单选求解目标，其余三项为输入。
 */
export function solveMolar(input: MolarInput): MolarResult {
  const { target, massUnit, volUnit, concUnit } = input
  const massG = input.mass === null ? null : input.mass * (MASS_FACTORS[massUnit] ?? 1)
  const volL = input.volume === null ? null : input.volume * (VOL_FACTORS[volUnit] ?? 1)
  const concM = input.conc === null ? null : input.conc * (CONC_FACTORS[concUnit] ?? 1)
  const mw = input.mw

  const need = (v: number | null, name: string): string | null =>
    v === null ? `请输入${name}` : v <= 0 ? `${name}必须为正数` : null

  let err: string | null = null
  let value = NaN
  let label = ''
  let unit = ''

  if (target === 'mass') {
    err = need(mw, '分子量') ?? need(volL, '体积') ?? need(concM, '浓度')
    if (!err) {
      value = concM! * volL! * mw! // g
      label = '所需质量'
      unit = 'g'
    }
  } else if (target === 'volume') {
    err = need(mw, '分子量') ?? need(massG, '质量') ?? need(concM, '浓度')
    if (!err) {
      value = massG! / mw! / concM! // L
      label = '所需体积'
      unit = 'L'
    }
  } else if (target === 'conc') {
    err = need(mw, '分子量') ?? need(massG, '质量') ?? need(volL, '体积')
    if (!err) {
      value = massG! / mw! / volL! // mol/L
      label = '浓度'
      unit = 'mol/L'
    }
  } else {
    err = need(massG, '质量') ?? need(volL, '体积') ?? need(concM, '浓度')
    if (!err) {
      value = massG! / (concM! * volL!) // g/mol
      label = '分子量'
      unit = 'g/mol'
    }
  }
  return { valid: err === null, error: err, value, label, unit }
}

/** 把 SI 结果换算成友好单位（质量 g/mg/µg，体积 L/mL/µL，浓度 M/mM/µM/nM）。 */
export function friendlySI(value: number, kind: 'mass' | 'volume' | 'conc' | 'mw'): string {
  if (!Number.isFinite(value)) return '—'
  if (kind === 'mw') return `${formatNum(value)} g/mol`
  if (kind === 'mass') {
    if (value >= 1) return `${formatNum(value)} g`
    if (value >= 1e-3) return `${formatNum(value * 1e3)} mg`
    return `${formatNum(value * 1e6)} µg`
  }
  if (kind === 'volume') {
    if (value >= 1) return `${formatNum(value)} L`
    if (value >= 1e-3) return `${formatNum(value * 1e3)} mL`
    return `${formatNum(value * 1e6)} µL`
  }
  if (value >= 1) return `${formatNum(value)} M`
  if (value >= 1e-3) return `${formatNum(value * 1e3)} mM`
  if (value >= 1e-6) return `${formatNum(value * 1e6)} µM`
  return `${formatNum(value * 1e9)} nM`
}

// ---------------------------------------------------------------------------
// 子计算器 4：核酸浓度 ng/µL ↔ nM
// ---------------------------------------------------------------------------

export type NucleicType = 'dsDNA' | 'ssDNA' | 'ssRNA'

/** 每 bp/nt 平均分子量（g/mol） */
export const NUC_MW_PER_NT: Record<NucleicType, number> = {
  dsDNA: 660,
  ssDNA: 330,
  ssRNA: 340,
}

export interface NucleicResult {
  valid: boolean
  error: string | null
  ngPerUl: number
  nM: number
  /** 分子量 g/mol */
  mw: number
}

/** ng/µL → nM。 */
export function ngUlToNm(ngPerUl: number, length: number, type: NucleicType): NucleicResult {
  if (ngPerUl <= 0 || length <= 0) {
    return { valid: false, error: '浓度与长度必须为正数', ngPerUl: 0, nM: 0, mw: 0 }
  }
  const mw = length * NUC_MW_PER_NT[type]
  // ng/µL = g/m³ = 1e-3 g/L；nM = (g/L) / MW * 1e9
  const nM = ((ngPerUl * 1e-3) / mw) * 1e9
  return { valid: true, error: null, ngPerUl, nM, mw }
}

/** nM → ng/µL。 */
export function nmToNgUl(nM: number, length: number, type: NucleicType): NucleicResult {
  if (nM <= 0 || length <= 0) {
    return { valid: false, error: '浓度与长度必须为正数', ngPerUl: 0, nM: 0, mw: 0 }
  }
  const mw = length * NUC_MW_PER_NT[type]
  const ngPerUl = ((nM * 1e-9) * mw) / 1e-3
  return { valid: true, error: null, ngPerUl, nM, mw }
}

// ---------------------------------------------------------------------------
// 子计算器 5：PCR 体系与 Master Mix 批量配制
// ---------------------------------------------------------------------------

export interface MasterMixComponent {
  name: string
  /** 单孔用量（µL） */
  perReaction: number
  /** 是否模板（不计入预混液、不加损耗余量） */
  isTemplate: boolean
}

export interface MasterMixInput {
  components: MasterMixComponent[]
  reactionCount: number
  extraPercent: number
}

export interface MasterMixRow {
  name: string
  perReaction: number
  total: number
  isTemplate: boolean
}

export interface MasterMixResult {
  valid: boolean
  error: string | null
  rows: MasterMixRow[]
  /** 预混液每孔合计（不含模板）µL */
  mixPerReaction: number
  /** 预混液总配制量（含损耗余量、不含模板）µL */
  mixTotal: number
  /** 单反应体系总体积（含模板）µL */
  totalReactionVolume: number
}

export function computeMasterMix(input: MasterMixInput): MasterMixResult {
  const factor = 1 + (input.extraPercent || 0) / 100
  const rows: MasterMixRow[] = []
  let mixPerReaction = 0
  let mixTotal = 0
  let totalReactionVolume = 0
  for (const c of input.components) {
    if (!c.name.trim() || !(c.perReaction > 0)) continue
    totalReactionVolume += c.perReaction
    if (c.isTemplate) {
      rows.push({ name: c.name.trim(), perReaction: c.perReaction, total: c.perReaction * input.reactionCount, isTemplate: true })
    } else {
      mixPerReaction += c.perReaction
      const total = c.perReaction * input.reactionCount * factor
      mixTotal += total
      rows.push({ name: c.name.trim(), perReaction: c.perReaction, total, isTemplate: false })
    }
  }
  if (!rows.length) {
    return { valid: false, error: '请至少填写一个组分（名称 + 单孔用量）', rows, mixPerReaction, mixTotal, totalReactionVolume }
  }
  if (!(input.reactionCount > 0)) {
    return { valid: false, error: '反应样品数必须为正数', rows, mixPerReaction, mixTotal, totalReactionVolume }
  }
  return { valid: true, error: null, rows, mixPerReaction, mixTotal, totalReactionVolume }
}

export function genSampleMasterMix(): { components: MasterMixComponent[]; reactionCount: number; extraPercent: number } {
  return {
    components: [
      { name: '2× Master Mix', perReaction: 10, isTemplate: false },
      { name: '正向引物 F (10 µM)', perReaction: 0.8, isTemplate: false },
      { name: '反向引物 R (10 µM)', perReaction: 0.8, isTemplate: false },
      { name: '无核酸酶水', perReaction: 7.4, isTemplate: false },
      { name: '模板 DNA', perReaction: 1, isTemplate: true },
    ],
    reactionCount: 96,
    extraPercent: 10,
  }
}

// ---------------------------------------------------------------------------
// 子计算器 6：载体/片段连接反应摩尔比 (Ligation)
// ---------------------------------------------------------------------------

export interface LigationInput {
  vectorLength: number
  vectorMass: number
  insertLength: number
  /** 插入片段:载体 摩尔比（如 3 表示 1:3） */
  molarRatio: number
  /** 插入片段浓度（ng/µL），可选，用于换算吸取体积 */
  insertConc: number | null
}

export interface LigationResult {
  valid: boolean
  error: string | null
  insertMass: number
  insertVolume: number | null
}

export function computeLigation(input: LigationInput): LigationResult {
  const { vectorLength, vectorMass, insertLength, molarRatio, insertConc } = input
  if (!(vectorLength > 0) || !(vectorMass > 0) || !(insertLength > 0) || !(molarRatio > 0)) {
    return { valid: false, error: '载体/片段长度、载体用量与摩尔比均需为正数', insertMass: 0, insertVolume: null }
  }
  const insertMass = vectorMass * (insertLength / vectorLength) * molarRatio
  const insertVolume = insertConc && insertConc > 0 ? insertMass / insertConc : null
  return { valid: true, error: null, insertMass, insertVolume }
}

// ---------------------------------------------------------------------------
// 子计算器 7：DNA / RNA 绝对拷贝数
// ---------------------------------------------------------------------------

export interface CopyNumberResult {
  valid: boolean
  error: string | null
  copiesPerUl: number
  mw: number
}

/** 拷贝数/µL = C(ng/µL) × 6.022e23 / (长度 × 1e9 × 每 bp/nt 平均分子量) */
export function computeCopyNumber(concNgUl: number, length: number, type: NucleicType): CopyNumberResult {
  if (!(concNgUl > 0) || !(length > 0)) {
    return { valid: false, error: '浓度与长度必须为正数', copiesPerUl: 0, mw: 0 }
  }
  const perNt = NUC_MW_PER_NT[type]
  const mw = length * perNt
  const copiesPerUl = (concNgUl * 6.022e23) / (length * 1e9 * perNt)
  return { valid: true, error: null, copiesPerUl, mw }
}

// ---------------------------------------------------------------------------
// 子计算器 8：NGS 文库等摩尔 Pooling
// ---------------------------------------------------------------------------

export interface PoolLibrary {
  name: string
  massConc: number
  avgSize: number
}

export interface PoolInput {
  libraries: PoolLibrary[]
  /** 目标总摩尔浓度（nM） */
  targetConc: number
  /** 目标总体积（µL） */
  targetVolume: number
}

export interface PoolRow {
  name: string
  /** 该文库摩尔浓度（nM） */
  molarConc: number
  /** 需吸取体积（µL） */
  volume: number
}

export interface PoolResult {
  valid: boolean
  error: string | null
  rows: PoolRow[]
  diluentVolume: number
}

export function computePooling(input: PoolInput): PoolResult {
  const libs = input.libraries.filter((l) => l.name.trim() && l.massConc > 0 && l.avgSize > 0)
  if (libs.length === 0) {
    return { valid: false, error: '请至少填写一个有效文库（名称 + 质量浓度 + 平均片段大小）', rows: [], diluentVolume: 0 }
  }
  if (!(input.targetConc > 0) || !(input.targetVolume > 0)) {
    return { valid: false, error: '目标摩尔浓度与目标总体积必须为正数', rows: [], diluentVolume: 0 }
  }
  const totalFmol = input.targetConc * input.targetVolume
  const fmolEach = totalFmol / libs.length
  const rows: PoolRow[] = libs.map((l) => {
    const molarConc = (l.massConc * 1e6) / (l.avgSize * 660)
    return { name: l.name.trim(), molarConc, volume: fmolEach / molarConc }
  })
  const usedVolume = rows.reduce((sum, r) => sum + r.volume, 0)
  const diluentVolume = Math.max(input.targetVolume - usedVolume, 0)
  return { valid: true, error: null, rows, diluentVolume }
}

export function genSamplePooling(): { libraries: PoolLibrary[]; targetConc: number; targetVolume: number } {
  return {
    libraries: [
      { name: 'Lib-A', massConc: 4.2, avgSize: 450 },
      { name: 'Lib-B', massConc: 3.1, avgSize: 380 },
      { name: 'Lib-C', massConc: 5.6, avgSize: 520 },
      { name: 'Lib-D', massConc: 2.8, avgSize: 410 },
    ],
    targetConc: 4,
    targetVolume: 20,
  }
}

// ---------------------------------------------------------------------------
// 子计算器 9：磁珠纯化与选段比例 (AMPure XP)
// ---------------------------------------------------------------------------

export type BeadsMode = 'single' | 'double'

export interface BeadsInput {
  mode: BeadsMode
  sampleVolume: number
  /** 单向比例，或双向第一步比例（如 0.6×） */
  ratio1: number
  /** 双向目标总比例（如 0.8×，须 > ratio1） */
  ratio2: number
}

export interface BeadsResult {
  valid: boolean
  error: string | null
  beads1: number
  supernatant: number
  beads2: number | null
  elutionHint: string
}

export function computeBeads(input: BeadsInput): BeadsResult {
  const { mode, sampleVolume, ratio1, ratio2 } = input
  if (!(sampleVolume > 0) || !(ratio1 > 0)) {
    return { valid: false, error: '样品体积与磁珠比例必须为正数', beads1: 0, supernatant: 0, beads2: null, elutionHint: '' }
  }
  const beads1 = sampleVolume * ratio1
  if (mode === 'single') {
    return {
      valid: true, error: null, beads1, supernatant: 0, beads2: null,
      elutionHint: '结合后磁吸去上清，70% 乙醇洗涤两次，晾干后按需用低盐缓冲液/水洗脱。',
    }
  }
  if (!(ratio2 > ratio1)) {
    return { valid: false, error: '双向选段的目标总比例须大于第一步比例', beads1, supernatant: 0, beads2: null, elutionHint: '' }
  }
  const supernatant = sampleVolume + beads1
  const beads2 = sampleVolume * (ratio2 - ratio1)
  return {
    valid: true, error: null, beads1, supernatant, beads2,
    elutionHint: '第一步磁吸后转移全部上清（含目标及小片段），补加第二步磁珠结合目标片段，洗涤后洗脱。',
  }
}

// ---------------------------------------------------------------------------
// 子计算器 10：引物 Tm / 反向互补 / GC%
// ---------------------------------------------------------------------------

const COMPLEMENT_MAP: Record<string, string> = {
  A: 'T', T: 'A', G: 'C', C: 'G', N: 'N',
  R: 'Y', Y: 'R', S: 'S', W: 'W', K: 'M', M: 'K',
  B: 'V', V: 'B', D: 'H', H: 'D',
}

/** 清洗序列：去除空格、数字与非碱基字符，统一大写。 */
export function cleanSequence(text: string): string {
  return (text || '').toUpperCase().replace(/[^ATGCRYWSKMBDHVN]/g, '')
}

export function complementSeq(seq: string): string {
  return seq.split('').map((c) => COMPLEMENT_MAP[c] ?? 'N').join('')
}

export function reverseComplementSeq(seq: string): string {
  return complementSeq(seq).split('').reverse().join('')
}

export interface PrimerAnalysis {
  valid: boolean
  error: string | null
  length: number
  gcPercent: number
  tmWallace: number
  tmSalt: number
  reverse: string
  complement: string
  reverseComplement: string
  counts: { A: number; T: number; G: number; C: number; other: number }
}

/**
 * Tm 估算：
 * - Wallace 法则（短引物）：Tm = 2(A+T) + 4(G+C)
 * - 盐校正经验式（≥14 nt）：Tm = 81.5 + 16.6·log10([Na+]) + 0.41·GC% − 675/L
 */
export function analyzePrimer(text: string, sodiumMolar = 0.05): PrimerAnalysis {
  const seq = cleanSequence(text)
  const empty: PrimerAnalysis = {
    valid: false, error: '请输入有效 DNA 序列', length: 0, gcPercent: 0,
    tmWallace: 0, tmSalt: 0, reverse: '', complement: '', reverseComplement: '',
    counts: { A: 0, T: 0, G: 0, C: 0, other: 0 },
  }
  if (!seq.length) return empty
  const counts = { A: 0, T: 0, G: 0, C: 0, other: 0 }
  for (const c of seq) {
    if (c === 'A') counts.A += 1
    else if (c === 'T') counts.T += 1
    else if (c === 'G') counts.G += 1
    else if (c === 'C') counts.C += 1
    else counts.other += 1
  }
  const gc = counts.G + counts.C
  const at = counts.A + counts.T
  const gcPercent = (gc / seq.length) * 100
  const tmWallace = 2 * at + 4 * gc
  const tmSalt = 81.5 + 16.6 * Math.log10(sodiumMolar) + 0.41 * gcPercent - 675 / seq.length
  return {
    valid: true, error: null, length: seq.length, gcPercent,
    tmWallace, tmSalt,
    reverse: seq.split('').reverse().join(''),
    complement: complementSeq(seq),
    reverseComplement: reverseComplementSeq(seq),
    counts,
  }
}

// ---------------------------------------------------------------------------
// 子计算器 11：离心机转速 RPM ↔ 相对离心力 RCF
// ---------------------------------------------------------------------------

export type RcfDirection = 'rpm2rcf' | 'rcf2rpm'

/** RCF = 1.118e-5 × r(cm) × RPM² */
export function rpmToRcf(rpm: number, radiusCm: number): number {
  return 1.118e-5 * radiusCm * rpm * rpm
}

/** RPM = √(RCF / (1.118e-5 × r)) */
export function rcfToRpm(rcf: number, radiusCm: number): number {
  return Math.sqrt(rcf / (1.118e-5 * radiusCm))
}

// ---------------------------------------------------------------------------
// 子计算器 12：常用缓冲液配方生成器
// ---------------------------------------------------------------------------

export interface BufferComponent {
  name: string
  /** 每 1 L 用量 */
  perLiter: number
  unit: 'g' | 'mL'
}

export interface BufferRecipe {
  key: string
  label: string
  note: string
  components: BufferComponent[]
}

export const BUFFER_RECIPES: BufferRecipe[] = [
  {
    key: 'tae50x',
    label: '50× TAE',
    note: '用去离子水定容，无需调 pH；工作液为 1× TAE。',
    components: [
      { name: 'Tris 碱', perLiter: 242, unit: 'g' },
      { name: '冰乙酸', perLiter: 57.1, unit: 'mL' },
      { name: '0.5 M EDTA (pH 8.0)', perLiter: 100, unit: 'mL' },
    ],
  },
  {
    key: 'tbe10x',
    label: '10× TBE',
    note: '用去离子水定容，无需调 pH；工作液为 0.5× 或 1× TBE。',
    components: [
      { name: 'Tris 碱', perLiter: 108, unit: 'g' },
      { name: '硼酸', perLiter: 55, unit: 'g' },
      { name: '0.5 M EDTA (pH 8.0)', perLiter: 40, unit: 'mL' },
    ],
  },
  {
    key: 'tris1m',
    label: '1 M Tris-HCl (pH 8.0)',
    note: '溶解后用浓 HCl 调 pH 至 8.0（冷却至室温再定容，pH 随温度变化）。',
    components: [{ name: 'Tris 碱', perLiter: 121.14, unit: 'g' }],
  },
  {
    key: 'edta05m',
    label: '0.5 M EDTA (pH 8.0)',
    note: 'EDTA 二钠盐需接近 pH 8.0 才完全溶解，边加 NaOH 边搅拌后定容。',
    components: [{ name: 'EDTA 二钠盐 (EDTA·2Na)', perLiter: 186.1, unit: 'g' }],
  },
  {
    key: 'pbs10x',
    label: '10× PBS',
    note: '溶解后用 HCl 调 pH 至 7.4，定容后高压灭菌；工作液为 1× PBS。',
    components: [
      { name: 'NaCl', perLiter: 80, unit: 'g' },
      { name: 'KCl', perLiter: 2, unit: 'g' },
      { name: 'Na₂HPO₄', perLiter: 14.4, unit: 'g' },
      { name: 'KH₂PO₄', perLiter: 2.4, unit: 'g' },
    ],
  },
  {
    key: 'te1x',
    label: 'TE 缓冲液 (1×, pH 8.0)',
    note: '由 1 M Tris-HCl (pH 8.0) 与 0.5 M EDTA (pH 8.0) 稀释而成，终浓度 10 mM Tris / 1 mM EDTA。',
    components: [
      { name: '1 M Tris-HCl (pH 8.0)', perLiter: 10, unit: 'mL' },
      { name: '0.5 M EDTA (pH 8.0)', perLiter: 2, unit: 'mL' },
    ],
  },
]

export interface BufferResultRow {
  name: string
  amount: number
  unit: 'g' | 'mL'
}

export interface BufferResult {
  valid: boolean
  error: string | null
  label: string
  note: string
  rows: BufferResultRow[]
}

export function generateBufferRecipe(key: string, volumeMl: number): BufferResult {
  const recipe = BUFFER_RECIPES.find((r) => r.key === key)
  if (!recipe) {
    return { valid: false, error: '请选择缓冲液类型', label: '', note: '', rows: [] }
  }
  if (!(volumeMl > 0)) {
    return { valid: false, error: '目标体积必须为正数', label: recipe.label, note: recipe.note, rows: [] }
  }
  const scale = volumeMl / 1000
  const rows: BufferResultRow[] = recipe.components.map((c) => ({
    name: c.name, amount: c.perLiter * scale, unit: c.unit,
  }))
  return { valid: true, error: null, label: recipe.label, note: recipe.note, rows }
}

// ---------------------------------------------------------------------------
// CSV 导出辅助
// ---------------------------------------------------------------------------

/** 明细行数组 → CSV 文本（带 BOM，Excel 友好）。 */
export function toCsv(headers: string[], rows: (string | number)[][]): string {
  const esc = (v: string | number) => {
    const s = String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  return '﻿' + [headers, ...rows].map((r) => r.map(esc).join(',')).join('\n')
}
