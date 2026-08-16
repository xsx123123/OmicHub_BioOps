<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NButton, NIcon, NModal, useMessage } from 'naive-ui'
import {
  LockClosedOutline,
  MailOutline,
  CopyOutline,
  CheckmarkOutline,
} from '@vicons/ionicons5'
import { useSiteConfigStore } from '@/stores/site-config'
import { consumeModuleLockedNotice } from '@/utils/moduleGuard'

const props = defineProps<{
  /** 锁定模块的注册表 key（会话级去重标记用） */
  moduleKey: string
  /** 锁定模块显示名（首弹弹窗文案用） */
  moduleName: string
}>()

const message = useMessage()
const siteConfig = useSiteConfigStore()

// 每会话首次进入该锁定模块：在占位页之上额外弹一次提示弹窗
const noticeVisible = ref(false)

onMounted(() => {
  // 确保管理员联系方式已加载（供「联系管理员」胶囊使用）；失败不阻塞占位页
  siteConfig.fetchSiteConfig().catch(() => {})
  if (consumeModuleLockedNotice(props.moduleKey)) {
    noticeVisible.value = true
  }
})

const contact = computed(() => siteConfig.adminContact)

// 复制管理员联系方式（navigator.clipboard 失败时降级 execCommand，照 RegistrationDisabledModal 先例）
const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null
async function copyContact() {
  const text = contact.value?.trim()
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
    } catch {
      /* ignore */
    }
    document.body.removeChild(ta)
  }
  copied.value = true
  message.success('联系方式已复制')
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copied.value = false
  }, 2000)
}

onUnmounted(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <div class="not-authorized">
    <div class="na-lock" aria-hidden="true">
      <NIcon :size="44">
        <LockClosedOutline />
      </NIcon>
    </div>
    <h2 class="na-title">该模块未开通</h2>
    <p class="na-desc">您暂无此模块的使用权限，如需开通请联系管理员解锁。</p>

    <!-- 管理员联系方式：mailto 胶囊 + 复制按钮（未配置联系方式时不显示） -->
    <div v-if="contact" class="na-contact-row">
      <a
        :href="`mailto:${contact}`"
        class="na-contact-pill"
        :title="`发送邮件到 ${contact}`"
      >
        <NIcon :size="14" class="na-pill-icon">
          <MailOutline />
        </NIcon>
        <span class="na-pill-text">{{ contact }}</span>
      </a>
      <button
        class="na-copy-btn"
        type="button"
        :title="copied ? '已复制' : '复制联系方式'"
        @click="copyContact"
      >
        <NIcon :size="14">
          <CheckmarkOutline v-if="copied" />
          <CopyOutline v-else />
        </NIcon>
      </button>
    </div>

    <a v-if="contact" :href="`mailto:${contact}`" class="na-contact-btn-link">
      <NButton type="primary" size="large">联系管理员</NButton>
    </a>

    <!-- 会话首次进入的提示弹窗 -->
    <NModal
      v-model:show="noticeVisible"
      :auto-focus="false"
      :mask-closable="true"
      transform-origin="center"
    >
      <div class="na-modal">
        <h3 class="na-modal-title">模块未开通</h3>
        <p class="na-modal-desc">您暂无「{{ moduleName }}」模块的使用权限，请联系管理员解锁后使用。</p>
        <NButton type="primary" class="na-modal-btn" @click="noticeVisible = false">
          我知道了
        </NButton>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.not-authorized {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  background: var(--neutral-bg);
  box-sizing: border-box;
}

.na-lock {
  width: 96px;
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  margin-bottom: 24px;
}

.na-title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.na-desc {
  margin: 0 0 24px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--neutral-text-2);
  text-align: center;
}

/* ===== 联系方式胶囊 + 复制按钮（照 RegistrationDisabledModal 样式） ===== */
.na-contact-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 20px;
  max-width: 100%;
}

.na-contact-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
  padding: 8px 16px;
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: background 0.2s ease;
}

.na-contact-pill:hover {
  filter: brightness(0.92);
}

.na-pill-icon {
  flex-shrink: 0;
  color: var(--arco-primary);
}

.na-pill-text {
  flex-shrink: 0;
  white-space: nowrap;
}

.na-copy-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--neutral-border);
  background: var(--neutral-card);
  border-radius: 999px;
  color: var(--neutral-text-2);
  cursor: pointer;
  transition: all 0.2s ease;
}

.na-copy-btn:hover {
  background: var(--neutral-hover);
  color: var(--arco-primary);
  border-color: var(--arco-primary);
}

.na-contact-btn-link {
  text-decoration: none;
}

/* ===== 会话首弹弹窗 ===== */
.na-modal {
  width: 400px;
  max-width: calc(100vw - 48px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 28px 28px 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.na-modal-title {
  margin: 0 0 8px;
  font-size: 17px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.na-modal-desc {
  margin: 0 0 20px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--neutral-text-2);
  text-align: center;
}

.na-modal-btn {
  width: 100%;
}
</style>
