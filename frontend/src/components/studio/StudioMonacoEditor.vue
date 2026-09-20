<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'
import { useThemeStore } from '@/stores/theme'
import { cygnusxMonacoTheme, ensureCygnusxMonacoThemes } from './monacoTheme'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import CssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import HtmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import TsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'

const workerScope = self as typeof self & {
  MonacoEnvironment?: { getWorker: (_moduleId: string, label: string) => Worker }
}
workerScope.MonacoEnvironment = {
  getWorker(_moduleId, label) {
    if (label === 'json') return new JsonWorker()
    if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker()
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new HtmlWorker()
    if (label === 'typescript' || label === 'javascript') return new TsWorker()
    return new EditorWorker()
  },
}

const props = withDefaults(defineProps<{
  modelValue: string
  language?: string
  readonly?: boolean
}>(), {
  language: 'plaintext',
  readonly: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  save: []
  run: [selection?: string]
  cursor: [line: number, column: number]
}>()

const host = ref<HTMLDivElement | null>(null)
const themeStore = useThemeStore()
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let changingFromOutside = false

function selectedText(): string {
  if (!editor) return ''
  const selection = editor.getSelection()
  return selection ? editor.getModel()?.getValueInRange(selection) || '' : ''
}

defineExpose({
  focus: () => editor?.focus(),
  selectedText,
  layout: () => editor?.layout(),
})

onMounted(() => {
  if (!host.value) return
  ensureCygnusxMonacoThemes()
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: props.language,
    theme: cygnusxMonacoTheme(themeStore.isDark),
    readOnly: props.readonly,
    automaticLayout: true,
    minimap: { enabled: true, scale: 0.8 },
    fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
    fontSize: 13,
    lineHeight: 21,
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
    cursorSmoothCaretAnimation: 'on',
    scrollBeyondLastLine: false,
    renderWhitespace: 'selection',
    roundedSelection: true,
    bracketPairColorization: { enabled: true },
    guides: { bracketPairs: true, indentation: true },
  })
  editor.onDidChangeModelContent(() => {
    if (!changingFromOutside) emit('update:modelValue', editor?.getValue() || '')
  })
  editor.onDidChangeCursorPosition(({ position }) => emit('cursor', position.lineNumber, position.column))
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => emit('save'))
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => emit('run'))
  editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => emit('run', selectedText()))
})

watch(() => props.modelValue, (value) => {
  if (!editor || editor.getValue() === value) return
  changingFromOutside = true
  editor.setValue(value)
  changingFromOutside = false
})
watch(() => props.language, (language) => {
  const model = editor?.getModel()
  if (model) monaco.editor.setModelLanguage(model, language)
})
watch(() => props.readonly, (readOnly) => editor?.updateOptions({ readOnly }))
watch(() => themeStore.isDark, (isDark) => monaco.editor.setTheme(cygnusxMonacoTheme(isDark)))

onBeforeUnmount(() => editor?.dispose())
</script>

<template><div ref="host" class="studio-monaco" /></template>

<style scoped>
.studio-monaco { width: 100%; height: 100%; min-height: 240px; }
</style>
