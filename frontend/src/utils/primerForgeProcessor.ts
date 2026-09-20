export type PrimerTaskType = 'PCR' | 'qPCR' | 'sequencing' | 'cloning'

export interface RegionRange {
  start: number
  length: number
}

export interface PrimerParameters {
  optSize: number
  minSize: number
  maxSize: number
  optTm: number
  minTm: number
  maxTm: number
  maxTmDiff: number
  optGc: number
  minGc: number
  maxGc: number
  gcClamp: boolean
  gcClampLength: number
  productMin: number
  productMax: number
  numReturn: number
}

export interface ThermodynamicParameters {
  saltMonovalent: number
  saltDivalent: number
  dntpConc: number
  dnaConc: number
  maxPolyX: number
}

export interface AdvancedParameters {
  maxSelfAny: number
  maxSelfEnd: number
  maxPairAny: number
  maxPairEnd: number
  tmWeight: number
  gcWeight: number
  lengthWeight: number
  complWeight: number
}

export interface ProbeParameters {
  enabled: boolean
  optSize: number
  minSize: number
  maxSize: number
  optTm: number
  minTm: number
  maxTm: number
  minGc: number
  maxGc: number
  avoidFivePrimeG: boolean
  fluorophore: string
  quencher: string
}

export interface PrimerDesignInput {
  sequenceId: string
  sequenceTemplate: string
  taskType: PrimerTaskType
  targetRegions: RegionRange[]
  excludedRegions: RegionRange[]
  primerParameters: PrimerParameters
  thermodynamicParameters: ThermodynamicParameters
  advanced: AdvancedParameters
  probeParameters: ProbeParameters
}

export interface SequenceStats {
  length: number
  gcPercent: number
  nCount: number
  validBases: number
}

export interface PrimerInfo {
  sequence: string
  position: [number, number]
  bindingStart: number
  bindingEnd: number
  length: number
  tm: number
  gcPercent: number
  selfAny: number
  selfEnd: number
  hairpinTm: number
  endStability: number
  penalty: number
  warnings: string[]
}

export interface PrimerPair {
  rank: number
  pairPenalty: number
  complAny: number
  complEnd: number
  forwardPrimer: PrimerInfo
  reversePrimer: PrimerInfo
  probe?: PrimerInfo
  productSize: number
  productStart: number
  productEnd: number
  qualityScore: number
  warnings: string[]
}

export interface PrimerDesignResult {
  success: boolean
  designId: string
  sequenceId: string
  sequenceTemplate: string
  taskType: PrimerTaskType
  runtimeMs: number
  summary: {
    totalPairsReturned: number
    leftPrimersConsidered: number
    rightPrimersConsidered: number
    pairExplanations: string
  }
  primerPairs: PrimerPair[]
  diagnostics: string[]
}

export interface SynthesisCompany {
  id: string
  name: string
  fullName: string
  email: string
  phone?: string
  website: string
  features: string[]
  deliveryDays: string
  priceHint: string
}

export interface OrderDraftInput {
  pairs: PrimerPair[]
  company: SynthesisCompany
  sequenceId: string
  purification: string
  scale: string
  deliveryForm: string
  fluorophore: string
  quencher: string
  specialRequirements: string
  contactName: string
  labName: string
}

export interface OrderDraft {
  subject: string
  body: string
  recipient: string
}

interface PrimerCandidate extends PrimerInfo {
  direction: 'forward' | 'reverse' | 'probe'
}

export const SYNTHESIS_COMPANIES: SynthesisCompany[] = [
  {
    id: 'sangon',
    name: '生工生物',
    fullName: '生工生物工程(上海)股份有限公司',
    email: 'order@sangon.com',
    phone: '400-821-0008',
    website: 'https://www.sangon.com',
    features: ['普通引物', 'HPLC纯化', '修饰引物'],
    deliveryDays: '2-3',
    priceHint: '普通引物约 1.2 元/bp',
  },
  {
    id: 'tsingke',
    name: '擎科生物',
    fullName: '北京擎科生物科技股份有限公司',
    email: 'order@tsingke.com',
    phone: '400-610-8836',
    website: 'https://www.tsingke.com',
    features: ['普通引物', 'PAGE纯化', '长链引物'],
    deliveryDays: '1-2',
    priceHint: '普通引物约 1.0 元/bp',
  },
  {
    id: 'genscript',
    name: '金斯瑞',
    fullName: '南京金斯瑞生物科技有限公司',
    email: 'order@genscript.com.cn',
    phone: '400-025-8686',
    website: 'https://www.genscript.com.cn',
    features: ['基因合成', '高通量引物板', '特殊修饰'],
    deliveryDays: '2-5',
    priceHint: '普通引物约 1.5 元/bp',
  },
  {
    id: 'novogene',
    name: '诺禾致源',
    fullName: '北京诺禾致源科技股份有限公司',
    email: 'order@novogene.com',
    phone: '400-966-0802',
    website: 'https://www.novogene.com',
    features: ['普通引物', 'NGS相关引物'],
    deliveryDays: '2-3',
    priceHint: '普通引物约 1.3 元/bp',
  },
]

export function defaultPrimerParameters(taskType: PrimerTaskType): PrimerParameters {
  if (taskType === 'qPCR') {
    return {
      optSize: 20,
      minSize: 18,
      maxSize: 24,
      optTm: 60,
      minTm: 58,
      maxTm: 62,
      maxTmDiff: 2,
      optGc: 50,
      minGc: 35,
      maxGc: 65,
      gcClamp: true,
      gcClampLength: 1,
      productMin: 80,
      productMax: 250,
      numReturn: 5,
    }
  }
  if (taskType === 'sequencing') {
    return {
      optSize: 20,
      minSize: 18,
      maxSize: 25,
      optTm: 58,
      minTm: 54,
      maxTm: 62,
      maxTmDiff: 4,
      optGc: 50,
      minGc: 30,
      maxGc: 70,
      gcClamp: false,
      gcClampLength: 0,
      productMin: 350,
      productMax: 1000,
      numReturn: 5,
    }
  }
  return {
    optSize: 20,
    minSize: 18,
    maxSize: 25,
    optTm: 60,
    minTm: 57,
    maxTm: 63,
    maxTmDiff: 3,
    optGc: 50,
    minGc: 30,
    maxGc: 70,
    gcClamp: true,
    gcClampLength: 1,
    productMin: 100,
    productMax: 1000,
    numReturn: 5,
  }
}

export function defaultThermodynamicParameters(): ThermodynamicParameters {
  return {
    saltMonovalent: 50,
    saltDivalent: 0,
    dntpConc: 0,
    dnaConc: 50,
    maxPolyX: 5,
  }
}

export function defaultAdvancedParameters(): AdvancedParameters {
  return {
    maxSelfAny: 8,
    maxSelfEnd: 3,
    maxPairAny: 8,
    maxPairEnd: 3,
    tmWeight: 1,
    gcWeight: 1,
    lengthWeight: 1,
    complWeight: 1,
  }
}

export function defaultProbeParameters(): ProbeParameters {
  return {
    enabled: false,
    optSize: 20,
    minSize: 18,
    maxSize: 27,
    optTm: 70,
    minTm: 67,
    maxTm: 73,
    minGc: 30,
    maxGc: 80,
    avoidFivePrimeG: true,
    fluorophore: 'FAM',
    quencher: 'BHQ1',
  }
}

export function parseFastaInput(text: string): { id: string; sequence: string } {
  const lines = text.split(/\r?\n/)
  const header = lines.find((line) => line.trim().startsWith('>'))?.replace(/^>\s*/, '').trim()
  return {
    id: header?.split(/\s+/)[0] || '',
    sequence: cleanDnaSequence(text),
  }
}

export function cleanDnaSequence(text: string): string {
  return text
    .split(/\r?\n/)
    .filter((line) => !line.trim().startsWith('>'))
    .join('')
    .replace(/[^A-Za-z]/g, '')
    .toUpperCase()
    .replace(/U/g, 'T')
    .replace(/[^ACGTN]/g, 'N')
}

export function getSequenceStats(sequence: string): SequenceStats {
  const seq = cleanDnaSequence(sequence)
  const validBases = (seq.match(/[ACGT]/g) || []).length
  const gc = (seq.match(/[GC]/g) || []).length
  const nCount = (seq.match(/N/g) || []).length
  return {
    length: seq.length,
    gcPercent: validBases ? +(gc / validBases * 100).toFixed(2) : 0,
    nCount,
    validBases,
  }
}

export function reverseComplement(sequence: string): string {
  const map: Record<string, string> = { A: 'T', T: 'A', G: 'C', C: 'G', N: 'N' }
  return sequence
    .toUpperCase()
    .split('')
    .reverse()
    .map((base) => map[base] || 'N')
    .join('')
}

export function calculateGcPercent(sequence: string): number {
  const seq = sequence.toUpperCase()
  if (!seq.length) return 0
  return +(((seq.match(/[GC]/g) || []).length / seq.length) * 100).toFixed(1)
}

export function calculateTm(sequence: string, saltMonovalent = 50): number {
  const seq = sequence.toUpperCase()
  const length = seq.length
  if (!length) return 0
  const a = (seq.match(/A/g) || []).length
  const t = (seq.match(/T/g) || []).length
  const g = (seq.match(/G/g) || []).length
  const c = (seq.match(/C/g) || []).length
  if (length < 14) return +(2 * (a + t) + 4 * (g + c)).toFixed(1)
  const saltAdjustment = 16.6 * Math.log10(Math.max(saltMonovalent, 1) / 50)
  return +(64.9 + 41 * (g + c - 16.4) / length + saltAdjustment).toFixed(1)
}

export function parseRegionRanges(text: string): RegionRange[] {
  return text
    .split(/[;\n]+/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const match = part.match(/(\d+)\s*[,，:-]\s*(\d+)/)
      if (!match) return null
      const start = Math.max(0, Number(match[1]) - 1)
      const second = Number(match[2])
      const length = part.includes('-') || part.includes(':') ? Math.max(1, second - start) : Math.max(1, second)
      return { start, length }
    })
    .filter((range): range is RegionRange => Boolean(range))
}

export function designPrimers(input: PrimerDesignInput): PrimerDesignResult {
  const started = performance.now()
  const sequence = cleanDnaSequence(input.sequenceTemplate)
  const params = input.primerParameters
  const diagnostics = diagnoseSequence(sequence)
  const designId = `primer_${Date.now().toString(36)}`

  if (sequence.length < params.productMin + params.minSize) {
    return {
      success: false,
      designId,
      sequenceId: input.sequenceId || 'sequence',
      sequenceTemplate: sequence,
      taskType: input.taskType,
      runtimeMs: Math.round(performance.now() - started),
      summary: {
        totalPairsReturned: 0,
        leftPrimersConsidered: 0,
        rightPrimersConsidered: 0,
        pairExplanations: '序列短于最小产物长度，无法生成引物对',
      },
      primerPairs: [],
      diagnostics: ['序列长度不足，请降低产物长度下限或提供更长模板。'],
    }
  }

  const forwardCandidates = enumerateCandidates(sequence, 'forward', input)
  const reverseCandidates = enumerateCandidates(sequence, 'reverse', input)
  const rankedForward = forwardCandidates.sort((a, b) => a.penalty - b.penalty).slice(0, 220)
  const rankedReverse = reverseCandidates.sort((a, b) => a.penalty - b.penalty).slice(0, 220)
  const pairs: PrimerPair[] = []

  for (const forward of rankedForward) {
    for (const reverse of rankedReverse) {
      if (reverse.bindingStart <= forward.bindingEnd) continue
      const productStart = forward.bindingStart
      const productEnd = reverse.bindingEnd
      const productSize = productEnd - productStart
      if (productSize < params.productMin || productSize > params.productMax) continue
      if (!coversTargets(productStart, productEnd, input.targetRegions)) continue

      const tmDiff = Math.abs(forward.tm - reverse.tm)
      if (tmDiff > params.maxTmDiff + 1.5) continue

      const complAny = maxComplementarity(forward.sequence, reverse.sequence)
      const complEnd = maxThreePrimeComplementarity(forward.sequence, reverse.sequence)
      if (complAny > input.advanced.maxPairAny || complEnd > input.advanced.maxPairEnd) continue

      const productOpt = (params.productMin + params.productMax) / 2
      const productPenalty = Math.abs(productSize - productOpt) / Math.max(1, params.productMax - params.productMin) * 20
      const pairPenalty = +(
        forward.penalty
        + reverse.penalty
        + tmDiff * 2
        + complAny * input.advanced.complWeight
        + complEnd * input.advanced.complWeight * 2
        + productPenalty
      ).toFixed(2)
      const warnings = collectPairWarnings(forward, reverse, tmDiff, complAny, complEnd, input)
      const pair: PrimerPair = {
        rank: 0,
        pairPenalty,
        complAny,
        complEnd,
        forwardPrimer: forward,
        reversePrimer: reverse,
        productSize,
        productStart,
        productEnd,
        qualityScore: calculatePairScore(pairPenalty, warnings.length),
        warnings,
      }
      if (input.taskType === 'qPCR' && input.probeParameters.enabled) {
        const probe = findProbe(sequence, productStart, productEnd, input)
        if (probe) pair.probe = probe
      }
      pairs.push(pair)
    }
  }

  const primerPairs = pairs
    .sort((a, b) => b.qualityScore - a.qualityScore || a.pairPenalty - b.pairPenalty)
    .slice(0, params.numReturn)
    .map((pair, index) => ({ ...pair, rank: index + 1 }))

  if (!primerPairs.length) {
    diagnostics.push('未找到满足全部约束的候选对，可放宽 Tm/GC/产物长度或互补性限制。')
  }

  return {
    success: primerPairs.length > 0,
    designId,
    sequenceId: input.sequenceId || 'sequence',
    sequenceTemplate: sequence,
    taskType: input.taskType,
    runtimeMs: Math.round(performance.now() - started),
    summary: {
      totalPairsReturned: primerPairs.length,
      leftPrimersConsidered: forwardCandidates.length,
      rightPrimersConsidered: reverseCandidates.length,
      pairExplanations: `considered ${forwardCandidates.length} left / ${reverseCandidates.length} right candidates, returned ${primerPairs.length} pairs`,
    },
    primerPairs,
    diagnostics,
  }
}

function enumerateCandidates(
  sequence: string,
  direction: 'forward' | 'reverse',
  input: PrimerDesignInput,
): PrimerCandidate[] {
  const params = input.primerParameters
  const candidates: PrimerCandidate[] = []
  const maxCandidates = 5000
  const step = sequence.length > 8000 ? 2 : 1
  for (let start = 0; start <= sequence.length - params.minSize; start += step) {
    for (let length = params.minSize; length <= params.maxSize; length += 1) {
      const end = start + length
      if (end > sequence.length) continue
      if (overlapsRegions(start, end, input.excludedRegions)) continue
      const templateSlice = sequence.slice(start, end)
      if (templateSlice.includes('N')) continue
      const primerSequence = direction === 'forward' ? templateSlice : reverseComplement(templateSlice)
      const candidate = evaluatePrimer(primerSequence, start, end, direction, input)
      if (candidate) candidates.push(candidate)
      if (candidates.length >= maxCandidates) return candidates
    }
  }
  return candidates
}

function evaluatePrimer(
  sequence: string,
  bindingStart: number,
  bindingEnd: number,
  direction: 'forward' | 'reverse' | 'probe',
  input: PrimerDesignInput,
): PrimerCandidate | null {
  const params = direction === 'probe' ? probeParamsToPrimerParams(input.probeParameters) : input.primerParameters
  const thermo = input.thermodynamicParameters
  const advanced = input.advanced
  const length = sequence.length
  const tm = calculateTm(sequence, thermo.saltMonovalent)
  const gcPercent = calculateGcPercent(sequence)
  const selfAny = maxComplementarity(sequence, sequence)
  const selfEnd = maxThreePrimeComplementarity(sequence, sequence)
  const polyX = longestPolyX(sequence)
  const warnings: string[] = []

  if (tm < params.minTm || tm > params.maxTm) return null
  if (gcPercent < params.minGc || gcPercent > params.maxGc) return null
  if (polyX > thermo.maxPolyX) return null
  if (selfAny > advanced.maxSelfAny || selfEnd > advanced.maxSelfEnd) return null
  if (params.gcClamp && !hasGcClamp(sequence, params.gcClampLength)) warnings.push("3'端 GC clamp 不明显")

  const endStability = calculateEndStability(sequence)
  const hairpinTm = selfAny >= 5 ? +(tm * selfAny / length).toFixed(1) : 0
  const penalty = +(
    Math.abs(length - params.optSize) * advanced.lengthWeight
    + Math.abs(tm - params.optTm) * advanced.tmWeight
    + Math.abs(gcPercent - params.optGc) / 4 * advanced.gcWeight
    + selfAny * advanced.complWeight
    + selfEnd * advanced.complWeight * 2
    + Math.max(0, polyX - 3) * 2
    + (warnings.length ? 3 : 0)
  ).toFixed(2)

  return {
    direction,
    sequence,
    position: direction === 'reverse' ? [bindingEnd - 1, length] : [bindingStart, length],
    bindingStart,
    bindingEnd,
    length,
    tm,
    gcPercent,
    selfAny,
    selfEnd,
    hairpinTm,
    endStability,
    penalty,
    warnings,
  }
}

function findProbe(
  sequence: string,
  productStart: number,
  productEnd: number,
  input: PrimerDesignInput,
): PrimerInfo | undefined {
  const probeParams = input.probeParameters
  const probeInput: PrimerDesignInput = {
    ...input,
    primerParameters: probeParamsToPrimerParams(probeParams),
  }
  const searchStart = productStart + input.primerParameters.minSize + 5
  const searchEnd = productEnd - input.primerParameters.minSize - 5
  const probes: PrimerCandidate[] = []
  for (let start = searchStart; start <= searchEnd - probeParams.minSize; start += 1) {
    for (let length = probeParams.minSize; length <= probeParams.maxSize; length += 1) {
      const end = start + length
      if (end > searchEnd) continue
      const probeSeq = sequence.slice(start, end)
      if (probeSeq.includes('N')) continue
      if (probeParams.avoidFivePrimeG && probeSeq.startsWith('G')) continue
      const probe = evaluatePrimer(probeSeq, start, end, 'probe', probeInput)
      if (probe) probes.push(probe)
    }
  }
  return probes.sort((a, b) => a.penalty - b.penalty)[0]
}

function probeParamsToPrimerParams(probe: ProbeParameters): PrimerParameters {
  return {
    optSize: probe.optSize,
    minSize: probe.minSize,
    maxSize: probe.maxSize,
    optTm: probe.optTm,
    minTm: probe.minTm,
    maxTm: probe.maxTm,
    maxTmDiff: 10,
    optGc: 55,
    minGc: probe.minGc,
    maxGc: probe.maxGc,
    gcClamp: false,
    gcClampLength: 0,
    productMin: 0,
    productMax: 0,
    numReturn: 1,
  }
}

function diagnoseSequence(sequence: string): string[] {
  const stats = getSequenceStats(sequence)
  const diagnostics: string[] = []
  if (!stats.length) diagnostics.push('未检测到 DNA 序列。')
  if (stats.nCount / Math.max(1, stats.length) > 0.05) diagnostics.push('N 碱基比例超过 5%，可能显著影响候选数量。')
  if (stats.gcPercent < 30) diagnostics.push('模板 GC 含量偏低，建议适当放宽 Tm 或 GC 约束。')
  if (stats.gcPercent > 70) diagnostics.push('模板 GC 含量偏高，建议关注二级结构与退火温度。')
  return diagnostics
}

function overlapsRegions(start: number, end: number, regions: RegionRange[]): boolean {
  return regions.some((region) => {
    const regionStart = region.start
    const regionEnd = region.start + region.length
    return start < regionEnd && end > regionStart
  })
}

function coversTargets(productStart: number, productEnd: number, regions: RegionRange[]): boolean {
  if (!regions.length) return true
  return regions.every((region) => productStart <= region.start && productEnd >= region.start + region.length)
}

function hasGcClamp(sequence: string, clampLength: number): boolean {
  if (!clampLength) return true
  const tail = sequence.slice(-Math.max(1, clampLength + 1))
  const gcCount = (tail.match(/[GC]/g) || []).length
  return gcCount >= clampLength
}

function longestPolyX(sequence: string): number {
  let longest = 0
  let current = 0
  let previous = ''
  for (const base of sequence) {
    current = base === previous ? current + 1 : 1
    previous = base
    longest = Math.max(longest, current)
  }
  return longest
}

function maxComplementarity(seqA: string, seqB: string): number {
  const a = seqA.toUpperCase()
  const b = reverseComplement(seqB.toUpperCase())
  let best = 0
  for (let offset = -b.length + 1; offset < a.length; offset += 1) {
    let run = 0
    for (let i = 0; i < a.length; i += 1) {
      const j = i - offset
      if (j < 0 || j >= b.length) {
        run = 0
        continue
      }
      if (a[i] === b[j]) {
        run += 1
        best = Math.max(best, run)
      } else {
        run = 0
      }
    }
  }
  return best
}

function maxThreePrimeComplementarity(seqA: string, seqB: string): number {
  const aTail = seqA.slice(-8)
  const bTail = seqB.slice(-8)
  return Math.max(maxSuffixMatch(aTail, reverseComplement(seqB)), maxSuffixMatch(bTail, reverseComplement(seqA)))
}

function maxSuffixMatch(tail: string, rcOther: string): number {
  let best = 0
  const max = Math.min(tail.length, rcOther.length)
  for (let size = 1; size <= max; size += 1) {
    if (tail.slice(-size) === rcOther.slice(0, size)) best = size
  }
  return best
}

function calculateEndStability(sequence: string): number {
  const tail = sequence.slice(-5)
  const gc = (tail.match(/[GC]/g) || []).length
  const at = tail.length - gc
  return +(-(gc * 2.1 + at * 1.1)).toFixed(1)
}

function collectPairWarnings(
  forward: PrimerInfo,
  reverse: PrimerInfo,
  tmDiff: number,
  complAny: number,
  complEnd: number,
  input: PrimerDesignInput,
): string[] {
  const warnings = [...forward.warnings, ...reverse.warnings]
  if (tmDiff > input.primerParameters.maxTmDiff) warnings.push(`正反向 Tm 差 ${tmDiff.toFixed(1)}°C 偏高`)
  if (complAny >= input.advanced.maxPairAny - 1) warnings.push('引物对任意互补接近上限')
  if (complEnd >= input.advanced.maxPairEnd - 1) warnings.push("引物对 3' 端互补接近上限")
  return [...new Set(warnings)]
}

function calculatePairScore(pairPenalty: number, warningCount: number): number {
  return Math.max(0, Math.min(100, Math.round(100 - pairPenalty * 1.6 - warningCount * 4)))
}

export function formatPrimerLocation(primer: PrimerInfo, direction: 'forward' | 'reverse'): string {
  if (direction === 'reverse') return `${primer.bindingStart + 1}-${primer.bindingEnd} (-)`
  return `${primer.bindingStart + 1}-${primer.bindingEnd} (+)`
}

export function exportPrimerReportHtml(result: PrimerDesignResult): string {
  const rows = result.primerPairs.map((pair) => `
    <tr>
      <td>${pair.rank}</td>
      <td>${pair.forwardPrimer.sequence}</td>
      <td>${pair.forwardPrimer.tm}</td>
      <td>${pair.forwardPrimer.gcPercent}</td>
      <td>${formatPrimerLocation(pair.forwardPrimer, 'forward')}</td>
      <td>${pair.reversePrimer.sequence}</td>
      <td>${pair.reversePrimer.tm}</td>
      <td>${pair.reversePrimer.gcPercent}</td>
      <td>${formatPrimerLocation(pair.reversePrimer, 'reverse')}</td>
      <td>${pair.probe?.sequence || ''}</td>
      <td>${pair.productSize}</td>
      <td>${pair.qualityScore}</td>
      <td>${pair.warnings.join('; ')}</td>
    </tr>`).join('')

  return `<!doctype html>
<html>
<head><meta charset="utf-8"><title>CygnusX PrimerForge Report</title></head>
<body>
  <h1>CygnusX PrimerForge 引物设计报告</h1>
  <table border="1">
    <tr><th>序列ID</th><td>${escapeHtml(result.sequenceId)}</td></tr>
    <tr><th>任务类型</th><td>${result.taskType}</td></tr>
    <tr><th>序列长度</th><td>${result.sequenceTemplate.length}</td></tr>
    <tr><th>候选对数</th><td>${result.summary.totalPairsReturned}</td></tr>
    <tr><th>设计耗时(ms)</th><td>${result.runtimeMs}</td></tr>
  </table>
  <h2>引物详情</h2>
  <table border="1">
    <thead>
      <tr>
        <th>排名</th><th>正向引物(5'-3')</th><th>正向Tm</th><th>正向GC%</th><th>正向位置</th>
        <th>反向引物(5'-3')</th><th>反向Tm</th><th>反向GC%</th><th>反向位置</th>
        <th>探针</th><th>产物大小(bp)</th><th>综合评分</th><th>预警</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</body>
</html>`
}

export function generateSynthesisOrderDraft(input: OrderDraftInput): OrderDraft {
  const subject = `引物合成订单 - ${input.labName || 'CygnusX'} - ${input.sequenceId}`
  const primerLines = input.pairs.map((pair) => {
    const base = [
      `引物对 #${pair.rank}，产物 ${pair.productSize} bp，评分 ${pair.qualityScore}`,
      `  ${input.sequenceId}_F${pair.rank}: 5'-${pair.forwardPrimer.sequence}-3'`,
      `  ${input.sequenceId}_R${pair.rank}: 5'-${pair.reversePrimer.sequence}-3'`,
    ]
    if (pair.probe) {
      base.push(`  ${input.sequenceId}_P${pair.rank}: 5'-${pair.probe.sequence}-3' (${input.fluorophore}/${input.quencher})`)
    }
    return base.join('\n')
  }).join('\n\n')

  const body = `收件人：${input.company.name} <${input.company.email}>

您好，

请协助合成以下引物，序列方向均为 5'-3'。

${primerLines || '（尚未选择引物）'}

合成要求：
- 纯化方式：${input.purification}
- 合成规模：${input.scale}
- 交付形式：${input.deliveryForm}
- 特殊要求：${input.specialRequirements || '无'}

联系人信息：
- 联系人：${input.contactName || '待填写'}
- 实验室：${input.labName || '待填写'}

烦请确认价格、交期与订单号，谢谢。
`
  return {
    subject,
    body,
    recipient: input.company.email,
  }
}

export function genPrimerSampleSeq(): string {
  return `>ACTB_qPCR_demo
AGCTGAGAGGGAAATCGTGCGTGACATTAAGGAGAAGCTGTGCTACGTCGCCCTGGACTTCGAGCAAGAGATGGCCACGGCTGCTTCCAGCTCCTCCCTGGAGAAGAGCTACGAGCTGCCTGACGGCCAGGTCATCACCATTGGCAATGAGCGGTTCAGGTGTCCGGAGACGACGAGGCCCAGAGCAAGAGAGGTATCCTGACCCTGAAGTACCCCATCGAGCACGGCATCGTCACCAACTGGGACGACATGGAGAAGATCTGGCACCACACCTTCTACAATGAGCTGCGTGTGGCCCCTGAGGAGCACCCCGTGCTGCTGACCGAGGCCCCCCTGAACCCCAAGGCCAACCGCGAGAAGATGACCCAGATCATGTTTGAGACCTTCAACACCCCAGCCATGTACGTTGCTATCCAGGCTGTGCTATCCCTGTACGCCTCTGGTCGTACCACCGGCATTGTGATGGACTCCGGTGACGGGGTCACCCACACTGTGCCCATCTACGAGGGGTATGCCCTCCCCCATGCCATCCTGCGTCTGGACCTGGCTGGCCGGGACCTGACTGACTACCTCATGAAGATCCTGACCGAGCGTGGCTACAGCTTCACCACCACGGCCGAGCGGGAAATCGTGCGTGACATTAAGGAGAAGCTGTGCTACGTCGCCCTGGACTTCGAGCAAGAGATGGCCACGGCTGCTTCCAGCTCCTCCCTGGAGAAGAGCTACGAGCTGCCTGACGGCCAGGTCATCACCATTGGCAATGAGCGGTTCAGGTGTCCGGAGACGACGAGGCCCAGAGCAAGAGAGGTATCCTGACCCTGAAGTACCCCATCGAGCACGGCATCGTCACCAACTGGGACGACATGGAGAAGATCTGG`
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
