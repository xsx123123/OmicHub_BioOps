<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = withDefaults(defineProps<{
  original: string
  modified: string
  language?: string
}>(), { language: 'plaintext' })

const host = ref<HTMLDivElement | null>(null)
let editor: monaco.editor.IStandaloneDiffEditor | null = null
let originalModel: monaco.editor.ITextModel | null = null
let modifiedModel: monaco.editor.ITextModel | null = null

function createModels() {
  originalModel?.dispose()
  modifiedModel?.dispose()
  originalModel = monaco.editor.createModel(props.original, props.language)
  modifiedModel = monaco.editor.createModel(props.modified, props.language)
  editor?.setModel({ original: originalModel, modified: modifiedModel })
}

onMounted(() => {
  if (!host.value) return
  editor = monaco.editor.createDiffEditor(host.value, {
    theme: 'omichub-studio-light',
    automaticLayout: true,
    readOnly: true,
    renderSideBySide: true,
    originalEditable: false,
    minimap: { enabled: false },
    fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    fontSize: 12,
    lineHeight: 20,
    scrollBeyondLastLine: false,
  })
  createModels()
})
watch(() => [props.original, props.modified, props.language], createModels)
onBeforeUnmount(() => { editor?.dispose(); originalModel?.dispose(); modifiedModel?.dispose() })
</script>

<template><div ref="host" class="studio-monaco-diff" /></template>
<style scoped>.studio-monaco-diff{width:100%;height:100%;min-height:260px}</style>
