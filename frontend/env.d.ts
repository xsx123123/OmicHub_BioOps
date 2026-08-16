/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface Window {
  initHeroAnimation?: (canvas: HTMLCanvasElement) => (() => void) | undefined
  initLoginAnimation?: (canvas: HTMLCanvasElement) => (() => void) | undefined
}

declare module 'vue-virtual-scroller' {
  import type { Component, VNode } from 'vue'

  interface ScrollerInstance {
    scrollToBottom: () => void
    scrollToItem: (index: number) => void
    scrollToPosition: (position: number) => void
    $el: HTMLElement
  }

  export const RecycleScroller: Component
  export const DynamicScroller: Component & { new (): ScrollerInstance }
  export const DynamicScrollerItem: Component
}
