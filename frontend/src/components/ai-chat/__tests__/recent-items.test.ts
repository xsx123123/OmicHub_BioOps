import { beforeEach, describe, expect, it } from 'vitest'
import { getRecent, pushRecent, recentRank } from '../recentItems'

/** node 测试环境无 localStorage，安装内存桩 */
function installLocalStorageStub() {
  const store = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
    },
  })
}

describe('recentItems（@ 与 / 面板最近使用）', () => {
  beforeEach(() => {
    installLocalStorageStub()
    localStorage.removeItem('cygnusx.panel.recent.v1')
  })

  it('新插入项置顶', () => {
    pushRecent('mention', 'file-1')
    pushRecent('mention', 'file-2')
    expect(getRecent('mention')).toEqual(['file-2', 'file-1'])
  })

  it('重复使用去重并重新置顶', () => {
    pushRecent('slash', '/rna')
    pushRecent('slash', '/code')
    pushRecent('slash', '/rna')
    expect(getRecent('slash')).toEqual(['/rna', '/code'])
  })

  it('最多保留 5 条', () => {
    for (let i = 1; i <= 8; i++) pushRecent('mention', `file-${i}`)
    const recent = getRecent('mention')
    expect(recent).toHaveLength(5)
    expect(recent[0]).toBe('file-8')
    expect(recent).not.toContain('file-3')
  })

  it('mention 与 slash 记录互不干扰', () => {
    pushRecent('mention', 'file-1')
    pushRecent('slash', '/go')
    expect(getRecent('mention')).toEqual(['file-1'])
    expect(getRecent('slash')).toEqual(['/go'])
  })

  it('recentRank：越近越小，未使用最大', () => {
    pushRecent('slash', '/rna')
    pushRecent('slash', '/code')
    expect(recentRank('slash', '/code')).toBe(0)
    expect(recentRank('slash', '/rna')).toBe(1)
    expect(recentRank('slash', '/unknown')).toBeGreaterThan(5)
  })

  it('存储损坏时静默降级为空列表', () => {
    localStorage.setItem('cygnusx.panel.recent.v1', '{not-json')
    expect(getRecent('mention')).toEqual([])
    pushRecent('mention', 'file-1')
    expect(getRecent('mention')).toEqual(['file-1'])
  })
})
