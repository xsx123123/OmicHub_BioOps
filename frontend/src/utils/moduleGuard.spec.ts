/**
 * 模块权限守卫的单元测试
 *
 * 关键防回归点：
 * - 前缀边界：/ai 不得误匹配 /aiworkbench（必须按「前缀 + '/'」切分）
 * - lockable=false 的模块（首页 / 系统管理）永不参与锁定判断
 * - 数据库双入口：/database 与 /reference-genomes 同属一个模块
 * - API URL 口径兼容：/api/v1/ai/... 与注册表 /api/ai 都能匹配
 */
import { describe, expect, it } from 'vitest'
import type { ModuleRegistryItem } from '@/types'
import {
  consumeModuleLockedNotice,
  findModuleForApiUrl,
  findModuleForRoutePath,
  isModuleLocked,
  lockedModuleForPath,
  pathMatchesPrefix,
} from './moduleGuard'

const registry: ModuleRegistryItem[] = [
  {
    key: 'ai-assistant',
    name: 'AI 助手',
    route_prefix: ['/ai'],
    api_prefix: ['/api/ai'],
    lockable: true,
    default_locked: false,
    ai: true,
  },
  {
    key: 'database',
    name: '数据库',
    route_prefix: ['/database', '/reference-genomes'],
    api_prefix: ['/api/reference-genomes'],
    lockable: true,
    default_locked: false,
    ai: false,
  },
  {
    key: 'flows',
    name: '分析中心',
    route_prefix: ['/flows'],
    api_prefix: ['/api/flows'],
    lockable: true,
    default_locked: false,
    ai: false,
  },
  {
    key: 'home',
    name: '首页',
    route_prefix: ['/'],
    api_prefix: [],
    lockable: false,
    default_locked: false,
    ai: false,
  },
]

describe('pathMatchesPrefix', () => {
  it('精确匹配与下级路径匹配', () => {
    expect(pathMatchesPrefix('/ai', '/ai')).toBe(true)
    expect(pathMatchesPrefix('/ai/chat/123', '/ai')).toBe(true)
  })

  it('同前缀但非下级路径不得匹配（/ai ≠ /aiworkbench）', () => {
    expect(pathMatchesPrefix('/aiworkbench', '/ai')).toBe(false)
    expect(pathMatchesPrefix('/aiworkbench/x', '/ai')).toBe(false)
  })

  it('空前缀不匹配', () => {
    expect(pathMatchesPrefix('/ai', '')).toBe(false)
  })
})

describe('findModuleForRoutePath', () => {
  it('按 route_prefix 命中可锁模块，query 串不影响', () => {
    expect(findModuleForRoutePath('/ai', registry)?.key).toBe('ai-assistant')
    expect(findModuleForRoutePath('/flows?type=rna-seq', registry)?.key).toBe('flows')
  })

  it('数据库模块同时覆盖 /database 与 /reference-genomes', () => {
    expect(findModuleForRoutePath('/database', registry)?.key).toBe('database')
    expect(findModuleForRoutePath('/database/abc', registry)?.key).toBe('database')
    expect(findModuleForRoutePath('/reference-genomes/abc', registry)?.key).toBe('database')
  })

  it('lockable=false 的模块跳过', () => {
    expect(findModuleForRoutePath('/', registry)).toBe(null)
  })
})

describe('lockedModuleForPath / isModuleLocked', () => {
  it('命中锁定模块返回注册表条目', () => {
    const mod = lockedModuleForPath('/ai', registry, ['ai-assistant'])
    expect(mod?.key).toBe('ai-assistant')
  })

  it('未禁用或禁用列表为空时不锁定', () => {
    expect(lockedModuleForPath('/ai', registry, [])).toBe(null)
    expect(lockedModuleForPath('/ai', registry, ['database'])).toBe(null)
  })

  it('isModuleLocked 仅在可锁且被禁用时为 true', () => {
    expect(isModuleLocked('ai-assistant', registry, ['ai-assistant'])).toBe(true)
    expect(isModuleLocked('ai-assistant', registry, [])).toBe(false)
    // lockable=false 的模块即使出现在禁用列表里也不锁定（防误伤首页/系统管理）
    expect(isModuleLocked('home', registry, ['home'])).toBe(false)
  })
})

describe('findModuleForApiUrl', () => {
  it('兼容 /api/v1 前缀的 axios 相对 URL', () => {
    expect(findModuleForApiUrl('/ai/chat', registry)?.key).toBe('ai-assistant')
    expect(findModuleForApiUrl('/api/v1/ai/chat', registry)?.key).toBe('ai-assistant')
  })

  it('query 串与无前缀口径不影响匹配', () => {
    expect(findModuleForApiUrl('/reference-genomes?page=1', registry)?.key).toBe('database')
    expect(findModuleForApiUrl('/admin/users', registry)).toBe(null)
  })
})

describe('consumeModuleLockedNotice', () => {
  function fakeStorage(): Storage {
    const map = new Map<string, string>()
    return {
      getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
      setItem: (k: string, v: string) => void map.set(k, v),
      removeItem: (k: string) => void map.delete(k),
      clear: () => map.clear(),
      key: () => null,
      get length() {
        return map.size
      },
    }
  }

  it('同一会话同一模块只放行一次，不同模块互不影响', () => {
    const storage = fakeStorage()
    expect(consumeModuleLockedNotice('ai-assistant', storage)).toBe(true)
    expect(consumeModuleLockedNotice('ai-assistant', storage)).toBe(false)
    expect(consumeModuleLockedNotice('database', storage)).toBe(true)
  })
})
