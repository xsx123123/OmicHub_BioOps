<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton, NIcon, NInput, NForm, NFormItem, NAlert, NScrollbar, NTag, NCheckbox,
  NUpload, useMessage, type FormInst, type FormRules, type UploadFileInfo,
} from 'naive-ui'
import {
  CloudUploadOutline, LogoGithub, CodeSlashOutline, ArrowBackOutline,
  TerminalOutline, WarningOutline, DocumentTextOutline,
} from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { SkillImportPreview } from '@/types/skill'

const message = useMessage()
const store = useAgentHubStore()

// ---------- Channel state ----------
type Channel = 'zip' | 'github' | 'markdown' | 'json'
const channel = ref<Channel>('zip')
const parsing = ref(false)
const confirming = ref(false)
const preview = ref<SkillImportPreview | null>(null)
const overwrite = ref(false)

// ZIP
const zipFile = ref<File | null>(null)
const dragOver = ref(false)

// GitHub
const githubFormRef = ref<FormInst | null>(null)
const githubModel = ref({ url: '' })
const githubRules: FormRules = {
  url: [
    { required: true, message: '请填写 GitHub 链接', trigger: 'blur' },
    { type: 'url', message: '请输入合法的 URL', trigger: 'blur' },
    {
      validator(_rule, value: string) {
        if (!value) return true
        try {
          const u = new URL(value)
          if (u.hostname !== 'github.com' && !u.hostname.endsWith('.github.com')) {
            return new Error('仅支持 github.com 域名')
          }
          return true
        } catch {
          return new Error('URL 格式不正确')
        }
      },
      trigger: 'blur',
    },
  ],
}

// Markdown
const markdownFile = ref<File | null>(null)

// JSON
const jsonInput = ref('')
const sampleJson = `{
  "name": "差异表达分析",
  "description": "基于 DESeq2 的差异表达分析技能",
  "icon": "🧬",
  "category": "数据处理",
  "prompt": "你擅长使用 DESeq2 进行差异表达分析..."
}`

const SOURCE_LABELS: Record<string, string> = {
  market: '市场', github: 'GitHub', zip: 'ZIP', markdown: 'Markdown', json: 'JSON', builtin: '内置',
}

const previewExists = computed(
  () => !!preview.value && store.skills.some((s) => s.id === preview.value!.skill_id),
)

// ---------- ZIP drag & drop ----------
function onDragOver(e: DragEvent) {
  e.preventDefault()
  dragOver.value = true
}
function onDragLeave() {
  dragOver.value = false
}
function onDrop(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) validateAndSetZip(file)
}
function onZipPickerChange(options: { file: UploadFileInfo }) {
  const f = options.file.file
  if (f) validateAndSetZip(f)
}
function validateAndSetZip(file: File) {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    message.error('仅支持 .zip 格式的技能包')
    return
  }
  if (file.size > 6 * 1024 * 1024) {
    message.error('技能包大小不能超过 6MB')
    return
  }
  zipFile.value = file
}

function onMarkdownChange(options: { file: UploadFileInfo }) {
  markdownFile.value = options.file.file ?? null
}

// ---------- Parse actions ----------
async function handleParseZip() {
  if (!zipFile.value) { message.warning('请先选择或拖入 zip 技能包'); return }
  parsing.value = true
  try {
    preview.value = await store.previewSkillFromZip(zipFile.value)
  } catch (e) { message.error(apiErrorMessage(e)) } finally { parsing.value = false }
}

async function handleParseGithub() {
  try { await githubFormRef.value?.validate() } catch { return }
  parsing.value = true
  try {
    preview.value = await store.previewSkillFromGithub(githubModel.value.url.trim())
  } catch (e) { message.error(apiErrorMessage(e)) } finally { parsing.value = false }
}

async function handleParseMarkdown() {
  if (!markdownFile.value) { message.warning('请先选择 Markdown 文件'); return }
  parsing.value = true
  try {
    preview.value = await store.previewSkillFromMarkdown(markdownFile.value)
  } catch (e) { message.error(apiErrorMessage(e)) } finally { parsing.value = false }
}

async function handleParseJson() {
  if (!jsonInput.value.trim()) { message.warning('请粘贴 JSON 配置'); return }
  parsing.value = true
  try {
    preview.value = await store.previewSkillFromJson(jsonInput.value)
  } catch (e) { message.error(apiErrorMessage(e)) } finally { parsing.value = false }
}

function backToChannels() {
  preview.value = null
  overwrite.value = false
}

async function handleConfirm() {
  if (!preview.value) return
  preview.value.name = preview.value.name.trim()
  preview.value.description = preview.value.description.trim()
  preview.value.version = preview.value.version.trim()
  if (!preview.value.name || !preview.value.description) {
    message.warning('请填写技能名称和描述后再确认导入')
    return
  }
  confirming.value = true
  try {
    await store.confirmSkillImport(preview.value, overwrite.value)
    message.success(`技能「${preview.value.name}」已入库`)
    preview.value = null
    overwrite.value = false
    zipFile.value = null
    markdownFile.value = null
  } catch (e) {
    message.error(apiErrorMessage(e))
  } finally {
    confirming.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function apiErrorMessage(e: unknown): string {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err?.response?.data?.detail || err?.message || '操作失败'
}
</script>

<template>
  <div class="skill-import-section">
    <!-- Preview mode -->
    <div v-if="preview" class="preview-pane">
      <div class="preview-head">
        <div class="preview-icon">{{ preview.icon }}</div>
        <div class="preview-title">
          <div class="preview-name">
            {{ preview.name }}
            <NTag v-if="preview.version" size="tiny" :bordered="false">v{{ preview.version }}</NTag>
            <NTag size="tiny" type="info" :bordered="false">{{ SOURCE_LABELS[preview.source_type] ?? preview.source_type }}</NTag>
          </div>
          <div class="preview-sub">
            <code>{{ preview.skill_id }}</code>
            <span v-if="preview.author">· {{ preview.author }}</span>
            <span v-if="preview.source_ref">· {{ preview.source_ref }}</span>
          </div>
        </div>
      </div>

      <NForm label-placement="top" size="small">
        <NFormItem label="技能名称" required>
          <NInput v-model:value="preview.name" placeholder="例如：单细胞样本 QC 审查" />
        </NFormItem>
        <NFormItem label="版本">
          <NInput v-model:value="preview.version" placeholder="例如：1.0.0（可选）" />
        </NFormItem>
        <NFormItem label="技能描述" required>
          <NInput v-model:value="preview.description" type="textarea" placeholder="说明技能解决什么问题、何时应该调用它" :autosize="{ minRows: 2, maxRows: 4 }" />
        </NFormItem>
      </NForm>

      <NAlert v-if="preview.has_scripts" type="warning" :bordered="false" class="preview-alert">
        <template #icon><NIcon :component="TerminalOutline" /></template>
        该技能包含可执行脚本（scripts/）。脚本将在沙盒中运行，代码不会进入模型上下文——请审查后再挂载到助手。
      </NAlert>
      <NAlert v-for="(warn, i) in preview.warnings" :key="i" type="warning" :bordered="false" class="preview-alert">
        <template #icon><NIcon :component="WarningOutline" /></template>
        {{ warn }}
      </NAlert>

      <div class="preview-block">
        <div class="preview-block-title">文件清单（{{ preview.files.length }}）</div>
        <NScrollbar style="max-height: 180px">
          <div class="file-list">
            <div v-for="f in preview.files" :key="f.path" class="file-row">
              <span class="file-path">{{ f.path }}</span>
              <NTag size="tiny" :bordered="false" :type="f.kind === 'script' ? 'warning' : f.kind === 'skill_md' ? 'info' : 'default'">
                {{ f.kind === 'skill_md' ? '入口' : f.kind === 'script' ? '脚本' : f.kind === 'reference' ? '参考' : f.kind === 'asset' ? '资源' : '其他' }}
              </NTag>
              <span class="file-size">{{ formatSize(f.size) }}</span>
            </div>
            <div v-if="!preview.files.length" class="file-none">无附带文件（纯指令技能）</div>
          </div>
        </NScrollbar>
      </div>

      <div v-if="preview.body" class="preview-block">
        <div class="preview-block-title">指令正文预览（SKILL.md）</div>
        <NScrollbar style="max-height: 200px">
          <pre class="preview-body">{{ preview.body }}</pre>
        </NScrollbar>
      </div>

      <div v-if="previewExists" class="preview-overwrite">
        <NCheckbox v-model:checked="overwrite">
          技能 <code>{{ preview.skill_id }}</code> 已存在，覆盖升级到该版本
        </NCheckbox>
      </div>

      <div class="preview-actions">
        <NButton @click="backToChannels">
          <template #icon><NIcon :component="ArrowBackOutline" /></template>
          返回
        </NButton>
        <NButton type="primary" :loading="confirming" :disabled="previewExists && !overwrite" @click="handleConfirm">
          确认导入
        </NButton>
      </div>
    </div>

    <!-- Channel mode -->
    <template v-else>
      <div class="omichub-segmented-toggle channel-toggle" role="group" aria-label="导入方式">
        <button :class="{ active: channel === 'zip' }" :aria-pressed="channel === 'zip'" @click="channel = 'zip'">
          <NIcon :component="CloudUploadOutline" /> 本地 ZIP
        </button>
        <button :class="{ active: channel === 'github' }" :aria-pressed="channel === 'github'" @click="channel = 'github'">
          <NIcon :component="LogoGithub" /> GitHub 导入
        </button>
        <button :class="{ active: channel === 'markdown' }" :aria-pressed="channel === 'markdown'" @click="channel = 'markdown'">
          <NIcon :component="DocumentTextOutline" /> Markdown
        </button>
        <button :class="{ active: channel === 'json' }" :aria-pressed="channel === 'json'" @click="channel = 'json'">
          <NIcon :component="CodeSlashOutline" /> JSON 粘贴
        </button>
      </div>

      <div class="channel-panel">
        <!-- ZIP -->
        <template v-if="channel === 'zip'">
          <div
            class="drop-zone"
            :class="{ 'drop-zone--active': dragOver }"
            @dragover="onDragOver"
            @dragleave="onDragLeave"
            @drop="onDrop"
          >
            <NIcon :component="CloudUploadOutline" :size="36" class="drop-icon" />
            <p class="drop-text">拖拽 ZIP 技能包到此处，或点击下方选择</p>
            <p class="drop-hint">内含 SKILL.md 与可选 scripts/ references/ assets/，≤6MB</p>
            <NUpload :default-upload="false" :max="1" accept=".zip" :show-file-list="false" @change="onZipPickerChange">
              <NButton size="small">选择 zip 文件</NButton>
            </NUpload>
            <div v-if="zipFile" class="drop-selected">已选择：{{ zipFile.name }}（{{ formatSize(zipFile.size) }}）</div>
          </div>
          <div class="channel-actions">
            <NButton type="primary" :loading="parsing" :disabled="!zipFile" @click="handleParseZip">解析并预览</NButton>
          </div>
        </template>

        <!-- GitHub -->
        <template v-else-if="channel === 'github'">
          <NForm ref="githubFormRef" :model="githubModel" :rules="githubRules" label-placement="top">
            <NFormItem label="GitHub 链接" path="url">
              <NInput v-model:value="githubModel.url" placeholder="https://github.com/owner/repo 或 .../tree/main/skills/my-skill" clearable />
            </NFormItem>
            <p class="channel-hint">支持仓库主页、tree 分支/子目录或直指 SKILL.md 的链接（公开仓库）。</p>
          </NForm>
          <div class="channel-actions">
            <NButton type="primary" :loading="parsing" @click="handleParseGithub">解析并预览</NButton>
          </div>
        </template>

        <!-- Markdown -->
        <template v-else-if="channel === 'markdown'">
          <p class="channel-hint">直接上传 .md 指令文件，无需预先打包。请在下一步补全名称、版本和描述。</p>
          <NUpload :default-upload="false" :max="1" accept=".md,text/markdown" :show-file-list="true" @change="onMarkdownChange">
            <NButton size="small">选择 Markdown 文件</NButton>
          </NUpload>
          <div class="channel-actions">
            <NButton type="primary" :loading="parsing" :disabled="!markdownFile" @click="handleParseMarkdown">解析并预览</NButton>
          </div>
        </template>

        <!-- JSON -->
        <template v-else>
          <p class="channel-hint">兼容旧版 JSON 配置（必填 name，可选 description/icon/category/prompt），将自动转换为 SKILL.md 格式。</p>
          <NInput
            v-model:value="jsonInput"
            type="textarea"
            class="json-textarea"
            :autosize="{ minRows: 8, maxRows: 16 }"
            :placeholder="sampleJson"
          />
          <div class="channel-actions">
            <NButton type="primary" :loading="parsing" @click="handleParseJson">解析并预览</NButton>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.skill-import-section { display: flex; flex-direction: column; gap: 16px; }

.channel-toggle { align-self: flex-start; }
.channel-toggle button { display: inline-flex; align-items: center; gap: 4px; }

.channel-panel {
  padding: 24px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
}
.channel-hint { font-size: 12px; color: var(--neutral-text-3, #888); margin: 0 0 12px; line-height: 1.6; }
.channel-actions { display: flex; justify-content: flex-end; margin-top: 16px; }

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 24px;
  border: 2px dashed var(--neutral-border);
  border-radius: 12px;
  text-align: center;
  transition: border-color 0.2s, background 0.2s;
  cursor: pointer;
}
.drop-zone--active {
  border-color: var(--arco-primary, #4C6FFF);
  background: rgba(76, 111, 255, 0.04);
}
.drop-icon { color: var(--neutral-text-3, #aaa); }
.drop-text { margin: 0; font-size: 14px; color: var(--text-primary, #333); }
.drop-hint { margin: 0; font-size: 12px; color: var(--neutral-text-3, #999); }
.drop-selected { margin-top: 8px; font-size: 12px; color: var(--arco-primary, #4C6FFF); }

.json-textarea :deep(textarea) {
  font-family: 'JetBrains Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}

/* Preview */
.preview-pane {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
}
.preview-head { display: flex; gap: 12px; align-items: center; }
.preview-icon {
  font-size: 32px;
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-primary-light, rgba(76, 111, 255, 0.08));
  border-radius: 12px;
  flex-shrink: 0;
}
.preview-title { min-width: 0; }
.preview-name { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.preview-sub { font-size: 12px; color: var(--n-text-color-3, #888); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-sub code { font-size: 11px; background: var(--n-color-embedded, #f5f6fa); padding: 1px 5px; border-radius: 4px; }
.preview-alert { font-size: 12px; }
.preview-block { border: 1px solid var(--neutral-border); border-radius: 10px; overflow: hidden; }
.preview-block-title { font-size: 12px; font-weight: 600; color: var(--n-text-color-2, #555); padding: 8px 12px; border-bottom: 1px solid var(--neutral-border); background: var(--n-color-embedded, #fafbfc); }
.file-list { padding: 4px 0; }
.file-row { display: flex; align-items: center; gap: 8px; padding: 5px 12px; font-size: 12px; }
.file-path { flex: 1; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { color: var(--n-text-color-3, #999); flex-shrink: 0; }
.file-none { padding: 10px 12px; font-size: 12px; color: var(--n-text-color-3, #999); }
.preview-body { margin: 0; padding: 12px; font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; font-family: monospace; }
.preview-overwrite { font-size: 13px; }
.preview-overwrite code { font-size: 11px; background: var(--n-color-embedded, #f5f6fa); padding: 1px 5px; border-radius: 4px; }
.preview-actions { display: flex; justify-content: space-between; }
</style>
