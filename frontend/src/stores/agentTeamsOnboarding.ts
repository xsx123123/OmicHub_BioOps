import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

// TODO(持久化缺口)：Manager onboarding 偏好本应持久化（刷新后保留），但项目未安装
// pinia-plugin-persistedstate，后端也无 Manager 偏好接口；按规范不引入新依赖、
// 组件不直接操作 localStorage，故暂为会话级内存态——刷新后丢失，下次创建房间会重新发起。
// 待后端提供偏好接口或前端引入持久化插件后迁移，迁移点仅在本文件。

export type OnboardingStepKey = 'name' | 'style' | 'autonomy' | 'language'

export interface OnboardingOption {
  label: string
  value: string
}

export interface OnboardingStep {
  key: OnboardingStepKey
  /** 提问文案；可引用已起的称呼 */
  question: (managerName: string) => string
  options: OnboardingOption[]
}

/** 四步引导（对齐 AgentTeams 客户端首轮行为）：起名 → 沟通风格 → 谨慎/自主 → 语言确认 */
const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    key: 'name',
    question: () => '你好，我是这个协作室的 Manager，负责分解任务、组建 Worker 团队并把关键步骤交给你把关。先认识一下——你想怎么称呼我？',
    options: [
      { label: '就叫 Manager', value: 'Manager' },
      { label: '小 O', value: '小 O' },
      { label: '管家', value: '管家' },
    ],
  },
  {
    key: 'style',
    question: (name) => `好的，我是「${name}」。日常沟通里，你更喜欢哪种风格？`,
    options: [
      { label: '正式专业', value: '正式专业' },
      { label: '亲切友好', value: '亲切友好' },
      { label: '极简高效', value: '极简高效' },
    ],
  },
  {
    key: 'autonomy',
    question: () => '执行方式上，你更倾向哪一种？',
    options: [
      { label: '谨慎模式：重要决定先请示', value: '谨慎模式' },
      { label: '自主模式：可以直接执行', value: '自主模式' },
    ],
  },
  {
    key: 'language',
    question: () => '最后确认一下：我们用中文沟通，可以吗？',
    options: [
      { label: '确认，用中文', value: '中文' },
      { label: '改用 English', value: 'English' },
    ],
  },
]

export const useAgentTeamsOnboardingStore = defineStore('agentTeamsOnboarding', () => {
  /** idle=未发起；asking=进行中；done=已完成或已稍后（本会话内不再发起） */
  const phase = ref<'idle' | 'asking' | 'done'>('idle')
  const stepIndex = ref(0)
  /** 已作答的步骤；跳过的步骤无记录。 */
  const answers = ref<Partial<Record<OnboardingStepKey, string>>>({})

  const managerName = computed(() => answers.value.name || 'Manager')
  const currentStep = computed(() => (phase.value === 'asking' ? ONBOARDING_STEPS[stepIndex.value] : null))

  /** 首个房间创建成功后发起；本会话已完成（含"稍后再说"）则不重复发起 */
  function begin() {
    if (phase.value !== 'idle') return
    stepIndex.value = 0
    phase.value = 'asking'
  }

  function answerCurrent(value: string) {
    const step = currentStep.value
    if (!step) return
    answers.value = { ...answers.value, [step.key]: value }
    advance()
  }

  function skipCurrent() {
    if (phase.value !== 'asking') return
    advance()
  }

  /** 整体跳过：偏好可稍后补充，不影响正常使用 */
  function dismiss() {
    phase.value = 'done'
  }

  function advance() {
    if (stepIndex.value < ONBOARDING_STEPS.length - 1) {
      stepIndex.value += 1
    } else {
      phase.value = 'done'
    }
  }

  return { phase, stepIndex, answers, managerName, currentStep, begin, answerCurrent, skipCurrent, dismiss }
})
