/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      keyframes: {
        'soft-float': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
      animation: {
        'soft-float': 'soft-float 3s ease-in-out infinite',
      },
      // ===== 设计令牌映射（P0 统一）=====
      // 策略：将 Tailwind 默认色板重映射到平台 CSS 变量，使既有 bg-gray-100 / text-blue-600
      // 等类名自动获得「深色模式感知 + 与 Arco 色板一致」的能力，无需逐文件改类名。
      // 注意：white / black 不重映射——text-white 在彩色按钮上须保持纯白。
      colors: {
        // —— 语义色（新代码优先使用）——
        primary: {
          DEFAULT: 'var(--arco-primary)',
          hover: 'var(--arco-primary-hover)',
          active: 'var(--arco-primary-active)',
          light: 'var(--arco-primary-light)',
        },
        success: {
          DEFAULT: 'var(--arco-success)',
          light: 'var(--arco-success-light)',
        },
        warning: {
          DEFAULT: 'var(--arco-warning)',
          light: 'var(--arco-warning-light)',
        },
        danger: {
          DEFAULT: 'var(--arco-danger)',
          light: 'var(--arco-danger-light)',
        },
        // —— 中性语义（新代码优先使用）——
        neutral: {
          bg: 'var(--neutral-bg)',
          card: 'var(--neutral-card)',
          border: 'var(--neutral-border)',
          hover: 'var(--neutral-hover)',
        },
        // —— 文字层级 ——
        text: {
          primary: 'var(--neutral-text-1)',
          secondary: 'var(--neutral-text-2)',
          tertiary: 'var(--neutral-text-3)',
          disabled: 'var(--neutral-text-4)',
        },

        // ===== 默认色板重映射 → 设计令牌（让旧类名自动对齐）=====
        gray: {
          50: 'var(--neutral-hover)',      // 表头/悬停底
          100: 'var(--neutral-bg)',        // 页面/区块底
          200: 'var(--neutral-border)',    // 边框
          300: 'var(--neutral-text-4)',    // 禁用
          400: 'var(--neutral-text-3)',    // 辅助文字
          500: 'var(--neutral-text-2)',    // 次要文字
          600: 'var(--neutral-text-2)',
          700: 'var(--neutral-text-1)',
          800: 'var(--neutral-text-1)',    // 主文字
          900: 'var(--neutral-text-1)',    // 标题
          950: 'var(--neutral-text-1)',
        },
        blue: {
          50: 'var(--arco-primary-light)',
          100: 'var(--arco-primary-light)',
          200: 'var(--arco-primary-light)',
          300: 'var(--arco-primary)',
          400: 'var(--arco-primary)',
          500: 'var(--arco-primary)',
          600: 'var(--arco-primary)',      // 主色文字
          700: 'var(--arco-primary-active)',
          800: 'var(--arco-primary-active)',
          900: 'var(--arco-primary-active)',
          950: 'var(--arco-primary-active)',
        },
        red: {
          50: 'var(--arco-danger-light)',
          100: 'var(--arco-danger-light)',
          200: 'var(--arco-danger-light)',
          300: 'var(--arco-danger)',
          400: 'var(--arco-danger)',
          500: 'var(--arco-danger)',
          600: 'var(--arco-danger)',
          700: 'var(--arco-danger)',
          800: 'var(--arco-danger)',
          900: 'var(--arco-danger)',
          950: 'var(--arco-danger)',
        },
        green: {
          50: 'var(--arco-success-light)',
          100: 'var(--arco-success-light)',
          200: 'var(--arco-success-light)',
          300: 'var(--arco-success)',
          400: 'var(--arco-success)',
          500: 'var(--arco-success)',
          600: 'var(--arco-success)',
          700: 'var(--arco-success)',
          800: 'var(--arco-success)',
          900: 'var(--arco-success)',
          950: 'var(--arco-success)',
        },
        orange: {
          50: 'var(--arco-warning-light)',
          100: 'var(--arco-warning-light)',
          200: 'var(--arco-warning-light)',
          300: 'var(--arco-warning)',
          400: 'var(--arco-warning)',
          500: 'var(--arco-warning)',
          600: 'var(--arco-warning)',
          700: 'var(--arco-warning)',
          800: 'var(--arco-warning)',
          900: 'var(--arco-warning)',
          950: 'var(--arco-warning)',
        },
        yellow: {
          50: 'var(--arco-warning-light)',
          100: 'var(--arco-warning-light)',
          200: 'var(--arco-warning-light)',
          300: 'var(--arco-warning)',
          400: 'var(--arco-warning)',
          500: 'var(--arco-warning)',
          600: 'var(--arco-warning)',
          700: 'var(--arco-warning)',
          800: 'var(--arco-warning)',
          900: 'var(--arco-warning)',
          950: 'var(--arco-warning)',
        },
        // 紫色未在令牌体系中，统一收敛到主色（克制用色）
        purple: {
          50: 'var(--arco-primary-light)',
          100: 'var(--arco-primary-light)',
          200: 'var(--arco-primary-light)',
          300: 'var(--arco-primary)',
          400: 'var(--arco-primary)',
          500: 'var(--arco-primary)',
          600: 'var(--arco-primary)',
          700: 'var(--arco-primary-active)',
          800: 'var(--arco-primary-active)',
          900: 'var(--arco-primary-active)',
          950: 'var(--arco-primary-active)',
        },
      },
      // ===== 阴影统一（新增键，不覆盖 Tailwind 默认 shadow-*）=====
      boxShadow: {
        'card': 'var(--shadow-card)',
        'card-hover': 'var(--shadow-card-hover)',
        'dropdown': 'var(--shadow-dropdown)',
        'soft': 'var(--shadow-soft)',
      },
      // 注：圆角不在此覆盖 Tailwind 默认 sm/md/lg 比例尺（避免全站 rounded-lg 从 8px→16px 位移）。
      // 圆角统一通过替换 CSS 硬编码 border-radius 为 var(--radius-sm/md/lg) 实现，见 global.css 令牌。
    },
  },
  // 关闭 preflight：项目 global.css 已有全局 reset，且避免覆盖 naive-ui 组件默认样式
  corePlugins: {
    preflight: false,
  },
  plugins: [],
}
