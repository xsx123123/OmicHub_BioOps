/**
 * CygnusX Monaco 主题（明暗成对）
 *
 * StudioMonacoEditor / StudioMonacoDiffEditor 共用。颜色取自 tokens.css 的
 * 深色 Surface 层级（--surface-card / --surface-elevated / --text-* 等），
 * 新增 Monaco 编辑场景必须先调用 ensureCygnusxMonacoThemes()，再按当前
 * 主题用 cygnusxMonacoTheme(isDark) 取名，并监听主题切换调 setTheme。
 */
import * as monaco from 'monaco-editor'

let defined = false

export function ensureCygnusxMonacoThemes(): void {
  if (defined) return
  defined = true
  monaco.editor.defineTheme('cygnusx-studio-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '8A8AA3', fontStyle: 'italic' },
      { token: 'keyword', foreground: '6C5CE7' },
      { token: 'string', foreground: '167D67' },
      { token: 'number', foreground: 'B05E1B' },
    ],
    colors: {
      'editor.background': '#FFFFFF',
      'editor.foreground': '#2B2B3D',
      'editorLineNumber.foreground': '#B0AFC2',
      'editorLineNumber.activeForeground': '#6C5CE7',
      'editorCursor.foreground': '#6C5CE7',
      'editor.selectionBackground': '#DDD7FF88',
      'editor.inactiveSelectionBackground': '#EEEAFE88',
      'editor.lineHighlightBackground': '#F8F7FF',
      'editorIndentGuide.background1': '#EEEAF8',
      'editorIndentGuide.activeBackground1': '#C8BEF3',
    },
  })
  monaco.editor.defineTheme('cygnusx-studio-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '68738A', fontStyle: 'italic' },
      { token: 'keyword', foreground: '93A8FF' },
      { token: 'string', foreground: '6FCF97' },
      { token: 'number', foreground: 'F2C94C' },
    ],
    colors: {
      'editor.background': '#121824',
      'editor.foreground': '#F5F7FF',
      'editorLineNumber.foreground': '#68738A',
      'editorLineNumber.activeForeground': '#93A8FF',
      'editorCursor.foreground': '#7691FF',
      'editor.selectionBackground': '#7691FF44',
      'editor.inactiveSelectionBackground': '#7691FF22',
      'editor.lineHighlightBackground': '#182033',
      'editorIndentGuide.background1': '#202A40',
      'editorIndentGuide.activeBackground1': '#2A3040',
      'editorGutter.background': '#121824',
      'editorWidget.background': '#182033',
      'editorWidget.border': '#2A3040',
      'minimap.background': '#0E1420',
    },
  })
}

export function cygnusxMonacoTheme(isDark: boolean): string {
  return isDark ? 'cygnusx-studio-dark' : 'cygnusx-studio-light'
}
