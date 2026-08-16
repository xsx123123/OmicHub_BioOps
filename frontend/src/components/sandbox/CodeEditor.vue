<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import { EditorState, Compartment } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'

const props = withDefaults(
  defineProps<{
    modelValue: string
    readonly?: boolean
    placeholder?: string
  }>(),
  { readonly: false, placeholder: '在此输入 Python 代码…' },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  run: []
  save: []
}>()

const host = ref<HTMLDivElement | null>(null)
const view = shallowRef<EditorView | null>(null)
const themeComp = new Compartment()
const readonlyComp = new Compartment()

function buildState(doc: string): EditorState {
  return EditorState.create({
    doc,
    extensions: [
      lineNumbers(),
      history(),
      highlightActiveLine(),
      keymap.of([
        ...defaultKeymap,
        ...historyKeymap,
        {
          key: 'Mod-Enter',
          run: () => {
            emit('run')
            return true
          },
        },
        {
          key: 'Mod-s',
          run: () => {
            emit('save')
            return true
          },
        },
      ]),
      python(),
      themeComp.of(oneDark),
      readonlyComp.of(EditorView.editable.of(!props.readonly)),
      EditorView.lineWrapping,
      EditorView.theme({
        '&': { fontSize: '13px', height: '100%' },
        '.cm-scroller': { fontFamily: "'JetBrains Mono','Fira Code',monospace" },
        '.cm-placeholder': { color: 'var(--neutral-text-3, #86909c)', fontStyle: 'italic' },
      }),
      EditorState.allowMultipleSelections.of(true),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) emit('update:modelValue', u.state.doc.toString())
      }),
    ],
  })
}

function mount() {
  if (!host.value || view.value) return
  view.value = new EditorView({ state: buildState(props.modelValue), parent: host.value })
}

onMounted(mount)
onBeforeUnmount(() => {
  view.value?.destroy()
  view.value = null
})

watch(
  () => props.modelValue,
  (val) => {
    const v = view.value
    if (!v) return
    if (val === v.state.doc.toString()) return
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: val } })
  },
)

watch(
  () => props.readonly,
  (ro) => {
    view.value?.dispatch({ effects: readonlyComp.reconfigure(EditorView.editable.of(!ro)) })
  },
)

defineExpose({
  focus: () => view.value?.focus(),
  getCode: () => view.value?.state.doc.toString() ?? props.modelValue,
})
</script>

<template>
  <div class="cm-host" ref="host"></div>
</template>

<style scoped>
.cm-host {
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: 8px;
  background: #282c34;
}
.cm-host :deep(.cm-editor) {
  height: 100%;
}
.cm-host :deep(.cm-scroller) {
  overflow: auto;
}
</style>
