/**
 * 模块注册表 store —— 用户模块权限管控的数据源
 *
 * 注册表由后端 GET /modules/registry 下发（源自 data/MODULE_LOCKED.yaml），
 * 前端任何位置禁止写死模块名，一律经本 store 匹配。
 *
 * 拉取失败时静默并保持 loaded=false（下次 ensureLoaded 自动重试）：
 * 前端锁定仅是 UX 层，后端中间件才是硬门槛，注册表不可用时不做任何前端锁定。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import apiClient from '@/api/client'
import type { ModuleRegistryItem } from '@/types'
import {
  findModuleForApiUrl,
  findModuleForRoutePath,
  isModuleLocked as isModuleLockedPure,
  lockedModuleForPath as lockedModuleForPathPure,
} from '@/utils/moduleGuard'

export const useModulesStore = defineStore('modules', () => {
  const registry = ref<ModuleRegistryItem[]>([])
  const loaded = ref(false)

  // 并发去重：同一时刻只发一次请求，复用同一个 Promise（照 site-config 先例）
  let loadingPromise: Promise<void> | null = null

  /** 确保注册表已加载；并发调用复用同一请求，失败静默、下次调用重试。永不 reject。 */
  function ensureLoaded(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    if (loadingPromise) return loadingPromise
    const p = apiClient
      .get<{ modules: ModuleRegistryItem[] }>('/modules/registry')
      .then((res) => {
        registry.value = Array.isArray(res.data?.modules) ? res.data.modules : []
        loaded.value = true
      })
      .catch(() => {
        // 静默失败：loaded 保持 false，下次 ensureLoaded 自动重试
      })
      .finally(() => {
        loadingPromise = null
      })
    loadingPromise = p
    return p
  }

  /** 当前路由路径命中的「对该用户已锁定」的可锁模块，未命中返回 null */
  function lockedModuleForPath(path: string, disabledModules: string[]): ModuleRegistryItem | null {
    return lockedModuleForPathPure(path, registry.value, disabledModules)
  }

  /** 按 route_prefix 匹配菜单/路由路径（用于侧边栏锁图标，不写死模块 key） */
  function moduleForRoutePath(path: string): ModuleRegistryItem | null {
    return findModuleForRoutePath(path, registry.value)
  }

  /** 按 api_prefix 匹配请求 URL（用于 403 MODULE_LOCKED 拦截时取模块名） */
  function moduleForApiUrl(url: string): ModuleRegistryItem | null {
    return findModuleForApiUrl(url, registry.value)
  }

  /** 指定模块 key 是否对该用户锁定（仅可锁模块参与判断） */
  function isModuleLocked(key: string, disabledModules: string[]): boolean {
    return isModuleLockedPure(key, registry.value, disabledModules)
  }

  return {
    registry,
    loaded,
    ensureLoaded,
    lockedModuleForPath,
    moduleForRoutePath,
    moduleForApiUrl,
    isModuleLocked,
  }
})
