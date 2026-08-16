<script setup lang="ts">
import { computed } from 'vue'
import { NAvatar } from 'naive-ui'

interface Props {
  /** 用户昵称，用于生成首字符与稳定背景色 */
  nickname?: string | null
  /** 可选头像 URL；提供时优先显示图片 */
  src?: string | null
  /** 头像尺寸，默认 32 */
  size?: number
}

const props = withDefaults(defineProps<Props>(), {
  nickname: '用户',
  src: '',
  size: 32,
})

const colors = [
  '#165DFF', '#14C9C2', '#F7BA1E', '#F53F3F',
  '#722ED1', '#EB2F96', '#00B42A', '#3491FA',
]

const initial = computed(() => {
  const name = props.nickname?.toString() ?? ''
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const firstChar = trimmed.charAt(0)
  if (/[a-zA-Z]/.test(firstChar)) {
    return firstChar.toUpperCase()
  }
  return firstChar
})

const bgColor = computed(() => {
  const name = props.nickname?.toString() ?? ''
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  const index = Math.abs(hash) % colors.length
  return colors[index]
})

const avatarStyle = computed(() => ({
  backgroundColor: bgColor.value,
  color: '#fff',
  fontWeight: 600,
  fontSize: `${Math.round(props.size * 0.5)}px`,
}))
</script>

<template>
  <n-avatar
    round
    :size="size"
    :style="avatarStyle"
    :src="src || undefined"
  >
    <span class="user-avatar-text">{{ initial }}</span>
  </n-avatar>
</template>

<style scoped>
.user-avatar-text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}
</style>
