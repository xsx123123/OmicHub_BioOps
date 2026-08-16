import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import { MotionPlugin } from '@vueuse/motion'
import App from './App.vue'
import router from './router'
import '@/styles/tokens.css'
import '@/styles/global.css'
import '@/styles/chat-theme.css'
import 'highlight.js/styles/github-dark.css'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import { useThemeStore } from '@/stores/theme'
import { registerAnimateList } from '@/directives/animateList'

const app = createApp(App)

app.use(createPinia())

// Pinia 初始化后立即恢复主题，避免闪白
const themeStore = useThemeStore()
themeStore.initTheme()

app.use(router)
app.use(naive)
app.use(MotionPlugin)
registerAnimateList(app)

app.mount('#app')
