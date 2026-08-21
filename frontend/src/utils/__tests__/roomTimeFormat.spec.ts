import { describe, expect, it } from 'vitest'
import { formatRoomFullTime, formatRoomRelativeTime, formatRoomTime } from '@/utils/roomTimeFormat'

describe('roomTimeFormat', () => {
  it('returns empty string for empty or invalid input', () => {
    expect(formatRoomTime('')).toBe('')
    expect(formatRoomTime(undefined)).toBe('')
    expect(formatRoomTime('not-a-date')).toBe('')
    expect(formatRoomFullTime('')).toBe('')
    expect(formatRoomRelativeTime('')).toBe('')
  })

  it('formats same-day time as HH:mm', () => {
    const now = new Date()
    const raw = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}T08:05:00`
    expect(formatRoomTime(raw)).toBe('08:05')
  })

  it('formats same-year time as MM/dd HH:mm', () => {
    const now = new Date()
    const raw = `${now.getFullYear()}-01-02T03:04:00`
    const expected = now.getDate() === 2 && now.getMonth() === 0 ? '03:04' : '01/02 03:04'
    expect(formatRoomTime(raw)).toBe(expected)
  })

  it('formats cross-year time as yyyy/MM/dd', () => {
    expect(formatRoomTime('2001-05-06T07:08:09')).toBe('2001/05/06')
  })

  it('formats full tooltip time as yyyy年M月d日 HH:mm:ss', () => {
    expect(formatRoomFullTime('2026-08-16T11:42:57')).toBe('2026年8月16日 11:42:57')
  })

  it('returns empty relative time for future dates', () => {
    expect(formatRoomRelativeTime('2999-01-01T00:00:00')).toBe('')
  })
})
