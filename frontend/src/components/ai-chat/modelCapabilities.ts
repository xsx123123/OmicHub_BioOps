/**
 * 模型能力推断工具
 *
 * 在不依赖后端模型元数据的前提下，依据模型 id / name / model / provider
 * 做启发式标注，供 ModelNavBar 的能力标签与"通用 / 生信专用"分组使用。
 */
import type { Capability, ModelType } from './types'
import type { ChatModelOption } from '@/types/chat'

interface InferredCapabilities {
  capabilities: Capability[]
  modelType: ModelType
  contextWindow: number
}

/** 能力标签展示优先级（用于"最多展示 3 个"截断） */
export const CAPABILITY_PRIORITY: Capability[] = ['bio', 'longContext', 'code', 'multimodal']

export const CAPABILITY_LABELS: Record<Capability, string> = {
  bio: '生信知识增强',
  longContext: '长文本',
  code: '代码',
  multimodal: '多模态',
}

/** 按优先级截断能力标签列表 */
export function topCapabilities(caps: Capability[], max = 3): Capability[] {
  return CAPABILITY_PRIORITY.filter((c) => caps.includes(c)).slice(0, max)
}

/**
 * 推断单个模型的能力与类型。
 * 规则基于关键字匹配，命中即标注；未命中返回空数组与 'general'。
 */
export function inferCapabilities(model: Pick<ChatModelOption, 'id' | 'name' | 'model' | 'provider_type'>): InferredCapabilities {
  const haystack = `${model.id} ${model.name} ${model.model} ${model.provider_type}`.toLowerCase()

  const capabilities: Capability[] = []

  // 代码：DeepSeek / Coder 系列
  if (/deepseek|coder|starcoder|qwen-coder|codeqwen/.test(haystack)) {
    capabilities.push('code')
  }

  // 多模态：视觉 / VL / Omni
  if (/(\bvl\b|vision|omni|\b4o\b|qwq| multimodal)/.test(haystack)) {
    capabilities.push('multimodal')
  }

  // 长文本：Max / Plus / 大参数 / 明确上下文标识
  if (/max|plus|\bk2\b|\b4o\b|128k|32b|72b|long.?context/.test(haystack)) {
    capabilities.push('longContext')
  }

  // 生信专用：包含 bio / 生信 关键字（默认模型库通常不命中）
  if (/bio|生信|biomedical/.test(haystack)) {
    capabilities.push('bio')
  }

  const modelType: ModelType = capabilities.includes('bio') ? 'bio' : 'general'

  // 上下文窗口粗估：含 128k 标 128，含 32b/plus/max 标 64，默认 32
  let contextWindow = 32
  if (/128k/.test(haystack)) contextWindow = 128
  else if (/max|plus|72b|32b/.test(haystack)) contextWindow = 64

  return { capabilities, modelType, contextWindow }
}

/** 将后端 ChatModelOption 列表增强为带能力标注的 ModelOption 列表 */
export function enhanceModels(models: ChatModelOption[]) {
  return models.map((m) => {
    const inferred = inferCapabilities(m)
    return {
      id: m.id,
      name: m.name,
      description: `${m.provider_type} · ${m.model}`,
      provider: m.provider_type,
      capabilities: inferred.capabilities,
      modelType: inferred.modelType,
      contextWindow: inferred.contextWindow,
    }
  })
}
