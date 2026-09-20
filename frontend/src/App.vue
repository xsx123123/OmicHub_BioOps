<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NDialogProvider, NNotificationProvider, zhCN, dateZhCN, darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppErrorBoundary from '@/components/AppErrorBoundary.vue'
import CatPawsOverlay from '@/components/CatPawsOverlay.vue'
import MeteorShowerOverlay from '@/components/MeteorShowerOverlay.vue'
import { useThemeStore } from '@/stores/theme'
import { computed } from 'vue'

const themeStore = useThemeStore()
const naiveTheme = computed(() => (themeStore.isDark ? darkTheme : undefined))

const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const isDark = themeStore.isDark
  // Naive UI 的 seemly 颜色解析器只接受实际颜色值，不接受 CSS var()/color-mix()。
  // CSS 令牌仍由业务样式消费；这里保留同一套明暗语义，但传入可解析的最终颜色。
  const palette = isDark
    ? {
        primary: '#7691FF',
        primaryHover: '#93A8FF',
        primaryPressed: '#5D79F4',
        success: '#22C55E',
        successHover: '#4ADE80',
        successPressed: '#16A34A',
        warning: '#F59E0B',
        warningHover: '#FBBF24',
        warningPressed: '#D97706',
        danger: '#EF4444',
        dangerHover: '#F87171',
        dangerPressed: '#DC2626',
        textPrimary: '#F5F7FF',
        textSecondary: '#A7B0C3',
        textTertiary: '#68738A',
        surfaceBase: '#080B12',
        surfaceCard: '#121824',
        surfaceElevated: '#182033',
        surfaceGlass: 'rgba(255, 255, 255, 0.06)',
        surfaceHighlight: '#202A40',
        border: 'rgba(255, 255, 255, 0.06)',
      }
    : {
        primary: '#4C6FFF',
        primaryHover: '#6381FF',
        primaryPressed: '#3D5DE6',
        success: '#00B42A',
        successHover: '#25C841',
        successPressed: '#009A23',
        warning: '#FF7D00',
        warningHover: '#FF9A2E',
        warningPressed: '#D26900',
        danger: '#F53F3F',
        dangerHover: '#FF6B6B',
        dangerPressed: '#CC2E2E',
        textPrimary: '#1D2129',
        textSecondary: '#4E5969',
        textTertiary: '#86909C',
        surfaceBase: '#F5F6FA',
        surfaceCard: '#FFFFFF',
        surfaceElevated: '#FFFFFF',
        surfaceGlass: 'rgba(255, 255, 255, 0.58)',
        surfaceHighlight: '#F2F3F8',
        border: '#E5E6EB',
      }
  return {
    common: {
      primaryColor: palette.primary,
      primaryColorHover: palette.primaryHover,
      primaryColorPressed: palette.primaryPressed,
      primaryColorSuppl: palette.primary,
      successColor: palette.success,
      successColorHover: palette.successHover,
      successColorPressed: palette.successPressed,
      successColorSuppl: palette.success,
      warningColor: palette.warning,
      warningColorHover: palette.warningHover,
      warningColorPressed: palette.warningPressed,
      warningColorSuppl: palette.warning,
      errorColor: palette.danger,
      errorColorHover: palette.dangerHover,
      errorColorPressed: palette.dangerPressed,
      errorColorSuppl: palette.danger,
      infoColor: palette.primary,
      infoColorHover: palette.primaryHover,
      infoColorPressed: palette.primaryPressed,
      infoColorSuppl: palette.primary,
      textColorBase: palette.textPrimary,
      textColor1: palette.textPrimary,
      textColor2: palette.textSecondary,
      textColor3: palette.textTertiary,
      bodyColor: palette.surfaceBase,
      cardColor: palette.surfaceCard,
      modalColor: palette.surfaceElevated,
      popoverColor: palette.surfaceElevated,
      dividerColor: palette.border,
      borderColor: palette.border,
      fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
      borderRadius: '8px',
      borderRadiusSmall: '4px',
    },
    Button: {
      borderRadiusPrimary: '8px',
      borderRadiusTiny: '4px',
      borderRadiusSmall: '4px',
      borderRadiusMedium: '8px',
      borderRadiusLarge: '8px',
    },
    Card: {
      borderRadius: '12px',
    },
    Tag: {
      borderRadius: '9999px',
    },
    Layout: {
      color: palette.surfaceBase,
      siderColor: palette.surfaceCard,
      headerColor: palette.surfaceGlass,
    },
    Menu: {
      borderRadiusHorizontal: '8px',
      itemHeight: '40px',
      itemIconColor: palette.textSecondary,
      itemTextColor: palette.textSecondary,
      itemIconColorHover: palette.textPrimary,
      itemTextColorHover: palette.textPrimary,
      itemColorHover: palette.surfaceHighlight,
      itemIconColorActive: palette.primary,
      itemTextColorActive: palette.primary,
      itemColorActive: isDark ? palette.surfaceHighlight : '#EEF1FF',
      itemIconColorChildActive: palette.primary,
      itemTextColorChildActive: palette.primary,
      itemColorChildActive: isDark ? palette.surfaceHighlight : '#EEF1FF',
    },
  }
})
</script>

<template>
  <NConfigProvider
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme="naiveTheme"
    :theme-overrides="themeOverrides"
  >
    <NMessageProvider>
      <NDialogProvider>
        <NNotificationProvider placement="top-right">
          <AppErrorBoundary>
            <RouterView />
          </AppErrorBoundary>
          <!-- 全局猫爪彩蛋覆盖层：监听 cygnusX:triggerCatPaws 事件（激活弹窗第 5 次 / 关于页召唤按钮） -->
          <CatPawsOverlay />
          <MeteorShowerOverlay />
        </NNotificationProvider>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
