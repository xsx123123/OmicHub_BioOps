import { reverseComplement } from '../dna/dna'
import { translateFrame } from '../protein/translator'
import type { MotifMatch, OrfMatch, ReadingFrame } from '../types'

export function findOrfs(
  dnaSeq: string,
  minLengthAa = 30,
  startCodons = ['ATG'],
  stopCodons = ['TAA', 'TAG', 'TGA'],
): OrfMatch[] {
  const sequence = dnaSeq.toUpperCase().replace(/U/g, 'T').replace(/[^ACGT]/g, '')
  const reverse = reverseComplement(sequence)
  const matches: OrfMatch[] = []
  const frames: ReadingFrame[] = [1, 2, 3, -1, -2, -3]

  for (const frame of frames) {
    const template = frame > 0 ? sequence : reverse
    const offset = Math.abs(frame) - 1
    for (let startIndex = offset; startIndex + 2 < template.length; startIndex += 3) {
      if (!startCodons.includes(template.slice(startIndex, startIndex + 3))) continue
      for (let endIndex = startIndex + 3; endIndex + 2 < template.length; endIndex += 3) {
        if (!stopCodons.includes(template.slice(endIndex, endIndex + 3))) continue
        const dnaSequence = template.slice(startIndex, endIndex + 3)
        const lengthAa = dnaSequence.length / 3 - 1
        if (lengthAa >= minLengthAa) {
          const forwardStart = frame > 0 ? startIndex + 1 : sequence.length - (endIndex + 3) + 1
          const forwardEnd = frame > 0 ? endIndex + 3 : sequence.length - startIndex
          matches.push({
            id: `ORF_${matches.length + 1}`,
            frame,
            start: Math.min(forwardStart, forwardEnd),
            end: Math.max(forwardStart, forwardEnd),
            lengthNt: dnaSequence.length,
            lengthAa,
            dnaSequence,
            proteinSequence: translateFrame(dnaSequence, 1).replace(/\*$/, ''),
          })
        }
        break
      }
    }
  }
  return matches.sort((left, right) => right.lengthAa - left.lengthAa)
}

const IUPAC_PATTERN: Record<string, string> = {
  A: 'A', C: 'C', G: 'G', T: 'T', U: '[TU]', R: '[AG]', Y: '[CT]', S: '[GC]', W: '[AT]',
  K: '[GT]', M: '[AC]', B: '[CGT]', D: '[AGT]', H: '[ACT]', V: '[ACG]', N: '[ACGT]',
}

function motifRegex(pattern: string): RegExp {
  const source = pattern.toUpperCase().split('').map((base) => IUPAC_PATTERN[base] || base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('')
  return new RegExp(`(?=(${source}))`, 'g')
}

export function findMotifs(sequence: string, pattern: string, name = 'Motif'): MotifMatch[] {
  const normalized = sequence.toUpperCase().replace(/U/g, 'T').replace(/[^ACGT]/g, '')
  const matches: MotifMatch[] = []
  const collect = (template: string, strand: '+' | '-') => {
    for (const match of template.matchAll(motifRegex(pattern))) {
      const startIndex = match.index ?? 0
      const length = match[1]?.length || pattern.length
      const start = strand === '+' ? startIndex + 1 : normalized.length - (startIndex + length) + 1
      matches.push({ name, pattern, start, end: start + length - 1, strand })
    }
  }
  collect(normalized, '+')
  collect(reverseComplement(normalized), '-')
  return matches.sort((left, right) => left.start - right.start)
}
