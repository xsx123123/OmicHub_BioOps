import type { SequenceStats } from '../types'

const COMPLEMENT: Record<string, string> = {
  A: 'T', T: 'A', U: 'A', C: 'G', G: 'C', R: 'Y', Y: 'R',
  S: 'S', W: 'W', K: 'M', M: 'K', B: 'V', V: 'B', D: 'H',
  H: 'D', N: 'N',
}

export function reverseComplement(sequence: string, isRna = false): string {
  let result = ''
  for (let index = sequence.length - 1; index >= 0; index -= 1) {
    const base = sequence[index]
    const upper = base.toUpperCase()
    let complement = COMPLEMENT[upper] || upper
    if (isRna && complement === 'T') complement = 'U'
    result += base === base.toLowerCase() ? complement.toLowerCase() : complement
  }
  return result
}

export function transcribe(dnaSeq: string): string {
  return dnaSeq.replace(/T/g, 'U').replace(/t/g, 'u')
}

export function reverseTranscribe(rnaSeq: string): string {
  return rnaSeq.replace(/U/g, 'T').replace(/u/g, 't')
}

export function calculateStats(sequence: string): SequenceStats {
  const normalized = sequence.toUpperCase().replace(/[^A-Z]/g, '')
  const baseCounts: Record<string, number> = {}
  for (const base of normalized) baseCounts[base] = (baseCounts[base] || 0) + 1
  const canonicalLength = (baseCounts.A || 0) + (baseCounts.T || 0) + (baseCounts.U || 0)
    + (baseCounts.C || 0) + (baseCounts.G || 0)
  const gcCount = (baseCounts.G || 0) + (baseCounts.C || 0)
  const atCount = (baseCounts.A || 0) + (baseCounts.T || 0) + (baseCounts.U || 0)
  const percentage = (count: number, denominator: number) => denominator ? +(count / denominator * 100).toFixed(2) : 0
  return {
    length: normalized.length,
    gcContent: percentage(gcCount, canonicalLength),
    atContent: percentage(atCount, canonicalLength),
    nContent: percentage(baseCounts.N || 0, normalized.length),
    baseCounts,
    molecularWeight: +(normalized.length * 330).toFixed(2),
  }
}
