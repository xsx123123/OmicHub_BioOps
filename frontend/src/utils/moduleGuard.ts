/**
 * 模块权限管控的纯函数守卫
 *
 * 全部逻辑基于后端下发的模块注册表（ModuleRegistryItem），
 * 任何位置禁止写死模块名/模块 key 做判断。
 *
 * 匹配规则：path 等于前缀，或以「前缀 + '/'」开头
 * （避免 /ai 误匹配 /aiworkbench 这类同前缀路径）。
 */
import type { ModuleRegistryItem } from '@/types'

/** 路由/接口前缀匹配：相等，或以「前缀 + '/'」开头 */
export function pathMatchesPrefix(path: string, prefix: string): boolean {
  if (!prefix) return false
  return path === prefix || path.startsWith(prefix.endsWith('/') ? prefix : `${prefix}/`)
}

/** 在注册表中查找命中指定路由路径的可锁模块（lockable=false 的管理员专属模块跳过） */
export function findModuleForRoutePath(
  path: string,
  registry: ModuleRegistryItem[],
): ModuleRegistryItem | null {
  const clean = path.split('?')[0]
  for (const mod of registry) {
    if (!mod.lockable) continue
    if ((mod.route_prefix || []).some((p) => pathMatchesPrefix(clean, p))) return mod
  }
  return null
}

/** 当前路由路径是否命中「对该用户已锁定」的模块，命中返回注册表条目 */
export function lockedModuleForPath(
  path: string,
  registry: ModuleRegistryItem[],
  disabledModules: string[],
): ModuleRegistryItem | null {
  if (!disabledModules?.length) return null
  const mod = findModuleForRoutePath(path, registry)
  return mod && disabledModules.includes(mod.key) ? mod : null
}

/** 指定模块 key 是否在该用户的禁用列表中（仅可锁模块参与判断） */
export function isModuleLocked(
  key: string,
  registry: ModuleRegistryItem[],
  disabledModules: string[],
): boolean {
  if (!disabledModules?.includes(key)) return false
  const mod = registry.find((m) => m.key === key)
  return !!mod && mod.lockable
}

/** 去掉接口路径的 /api/v1 或 /api 前缀，统一两侧口径后再做前缀匹配 */
function stripApiPrefix(url: string): string {
  let u = url.split('?')[0]
  if (u.startsWith('/api/v1')) u = u.slice('/api/v1'.length)
  else if (u.startsWith('/api')) u = u.slice('/api'.length)
  return u || '/'
}

/** 按 api_prefix 匹配请求 URL（axios config.url 为相对 baseURL 的路径），返回命中的可锁模块 */
export function findModuleForApiUrl(
  url: string,
  registry: ModuleRegistryItem[],
): ModuleRegistryItem | null {
  const path = stripApiPrefix(url)
  for (const mod of registry) {
    if (!mod.lockable) continue
    if ((mod.api_prefix || []).some((p) => pathMatchesPrefix(path, stripApiPrefix(p)))) return mod
  }
  return null
}

const LOCKED_NOTICE_PREFIX = 'module_locked_seen_'

/**
 * 会话级去重：首次消费返回 true 并写入 sessionStorage，同会话后续调用返回 false。
 * 占位页首弹与 API 拦截弹窗共用同一 key 规则，互不重复打扰。
 */
export function consumeModuleLockedNotice(key: string, storage?: Storage): boolean {
  const store = storage ?? (typeof sessionStorage !== 'undefined' ? sessionStorage : undefined)
  if (!store) return false
  try {
    const k = LOCKED_NOTICE_PREFIX + key
    if (store.getItem(k)) return false
    store.setItem(k, '1')
    return true
  } catch {
    return false
  }
}
