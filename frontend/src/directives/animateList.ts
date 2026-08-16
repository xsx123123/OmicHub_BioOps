import type { App, Directive, DirectiveBinding } from 'vue'
import autoAnimate from '@formkit/auto-animate'

const MAX_CHILDREN = 200

const reducedMotion = typeof window !== 'undefined'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function getDuration(binding: DirectiveBinding): number {
  if (reducedMotion) return 0
  const modifier = Object.keys(binding.modifiers || {}).find((m) => /^\d+$/.test(m))
  return modifier ? Number(modifier) : 250
}

function apply(el: HTMLElement, binding: DirectiveBinding) {
  if (el.children.length > MAX_CHILDREN) return
  const duration = getDuration(binding)
  if (duration === 0) return
  autoAnimate(el, { duration, easing: 'ease-in-out' })
}

const vAnimateList: Directive = {
  mounted(el: HTMLElement, binding) {
    apply(el, binding)
  },
}

export function registerAnimateList(app: App) {
  app.directive('animate-list', vAnimateList)
}

export default vAnimateList
