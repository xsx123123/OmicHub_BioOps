<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { NBadge, NTag } from 'naive-ui'
import { useCookieStore } from '@/stores/cookie'
import { useAuthStore } from '@/stores/auth'
import { useCookieWebSocket } from '@/composables/useCookieWebSocket'

const cookieStore = useCookieStore()
const authStore = useAuthStore()
const { connect } = useCookieWebSocket()

const cookieColor = computed(() => {
  const b = cookieStore.balance
  if (b >= 50) return 'success'
  if (b >= 10) return 'warning'
  return 'error'
})

onMounted(async () => {
  if (authStore.isLoggedIn) {
    await cookieStore.fetchAccount()
    connect()
  }
})
</script>

<template>
  <div v-if="authStore.isLoggedIn && cookieStore.account" class="cookie-badge">
    <NTag :type="cookieColor" size="small" round>
      🥫 {{ cookieStore.balance.toFixed(1) }}
    </NTag>
  </div>
</template>

<style scoped>
.cookie-badge {
  display: inline-flex;
  align-items: center;
  margin-right: 12px;
}
</style>
