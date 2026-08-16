import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { goalsApi, type GoalEvent, type GoalRuntimeGoal } from '@/api/goals'

const ACTIVE_STATUSES = new Set(['in_progress', 'waiting_user', 'waiting_external', 'paused'])

export const useGoalRuntimeStore = defineStore('goalRuntime', () => {
  const goalsBySession = ref<Record<string, GoalRuntimeGoal | undefined>>({})
  const eventsByGoal = ref<Record<string, GoalEvent[] | undefined>>({})
  const loadingBySession = ref<Record<string, boolean | undefined>>({})
  const errorBySession = ref<Record<string, string | undefined>>({})
  const controllers = new Map<string, AbortController>()

  const activeGoals = computed(() => Object.values(goalsBySession.value).filter(Boolean) as GoalRuntimeGoal[])

  function goalForSession(sessionId?: string): GoalRuntimeGoal | null {
    return sessionId ? goalsBySession.value[sessionId] || null : null
  }

  function eventsForGoal(goalId?: string): GoalEvent[] {
    return goalId ? eventsByGoal.value[goalId] || [] : []
  }

  function stopStream(goalId: string): void {
    controllers.get(goalId)?.abort()
    controllers.delete(goalId)
  }

  function saveGoal(goal: GoalRuntimeGoal): GoalRuntimeGoal {
    if (goal.session_id) goalsBySession.value[goal.session_id] = goal
    return goal
  }

  function appendEvent(event: GoalEvent): void {
    const previous = eventsByGoal.value[event.goal_id] || []
    if (previous.some((item) => item.sequence === event.sequence)) return
    eventsByGoal.value[event.goal_id] = [...previous, event].slice(-100)
  }

  async function connect(goal: GoalRuntimeGoal): Promise<void> {
    stopStream(goal.id)
    const controller = new AbortController()
    controllers.set(goal.id, controller)
    const after = eventsForGoal(goal.id).at(-1)?.sequence || 0
    try {
      await goalsApi.streamEvents(
        goal.id,
        after,
        (event) => {
          appendEvent(event)
          void goalsApi.get(goal.id).then(saveGoal).catch(() => undefined)
        },
        controller.signal,
      )
    } catch (error) {
      if ((error as DOMException).name !== 'AbortError' && goal.session_id) {
        errorBySession.value[goal.session_id] = 'Goal 实时状态连接失败，可手动刷新。'
      }
    } finally {
      if (controllers.get(goal.id) === controller) controllers.delete(goal.id)
    }
  }

  async function loadActiveGoal(sessionId: string): Promise<GoalRuntimeGoal | null> {
    loadingBySession.value[sessionId] = true
    try {
      const goals = await goalsApi.list(sessionId)
      const goal = goals.find((item) => ACTIVE_STATUSES.has(item.status)) || null
      if (goal) {
        saveGoal(goal)
        errorBySession.value[sessionId] = undefined
        void connect(goal)
      } else {
        goalsBySession.value[sessionId] = undefined
      }
      return goal
    } catch (error) {
      errorBySession.value[sessionId] = (error as Error).message || 'Goal 状态加载失败'
      throw error
    } finally {
      loadingBySession.value[sessionId] = false
    }
  }

  async function startGoal(
    sessionId: string,
    objective: string,
    managerAgentId?: string,
  ): Promise<GoalRuntimeGoal> {
    const goal = saveGoal(await goalsApi.start({
      objective,
      session_id: sessionId,
      manager_agent_id: managerAgentId,
      mode: 'chat',
      permission: 'safe',
    }))
    errorBySession.value[sessionId] = undefined
    void connect(goal)
    return goal
  }

  async function controlGoal(
    sessionId: string,
    action: 'pause' | 'resume' | 'cancel',
  ): Promise<GoalRuntimeGoal> {
    const goal = goalForSession(sessionId) || await loadActiveGoal(sessionId)
    if (!goal) throw new Error('当前会话没有可控制的 Goal')
    const nextGoal = saveGoal(await goalsApi.control(goal.id, action))
    if (action === 'cancel') stopStream(nextGoal.id)
    else void connect(nextGoal)
    return nextGoal
  }

  function disposeSession(sessionId: string): void {
    const goal = goalForSession(sessionId)
    if (goal) stopStream(goal.id)
  }

  return {
    activeGoals,
    loadingBySession,
    errorBySession,
    goalForSession,
    eventsForGoal,
    loadActiveGoal,
    startGoal,
    controlGoal,
    disposeSession,
  }
})
