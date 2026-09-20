import type { FastaRecord } from './types'

export type SequenceHandoffTarget = 'blast' | 'primer'

export interface SequenceHandoffPayload {
  source: 'sequence-studio'
  createdAt: string
  record: FastaRecord
}

const HANDOFF_PREFIX = 'cygnusx:sequence-handoff:'

export function storeSequenceHandoff(target: SequenceHandoffTarget, record: FastaRecord): void {
  const payload: SequenceHandoffPayload = {
    source: 'sequence-studio',
    createdAt: new Date().toISOString(),
    record,
  }
  sessionStorage.setItem(`${HANDOFF_PREFIX}${target}`, JSON.stringify(payload))
}

export function consumeSequenceHandoff(target: SequenceHandoffTarget): SequenceHandoffPayload | null {
  const key = `${HANDOFF_PREFIX}${target}`
  const raw = sessionStorage.getItem(key)
  if (!raw) return null
  sessionStorage.removeItem(key)
  try {
    return JSON.parse(raw) as SequenceHandoffPayload
  } catch {
    return null
  }
}
