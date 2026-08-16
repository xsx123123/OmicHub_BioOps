<template>
  <div class="jbrowse-container">
    <!-- 顶部控制栏 -->
    <div class="control-bar">
      <div class="left-controls">
        <a-button type="text" @click="$router.back()">
          <template #icon><icon-left /></template>
          返回工具箱
        </a-button>
        <a-divider direction="vertical" />
        <span class="page-title">Web 基因组浏览器</span>
      </div>

      <div class="right-controls">
        <!-- 参考基因组选择 -->
        <a-select
          v-model="selectedAssembly"
          placeholder="选择参考基因组"
          style="width: 240px"
          :loading="assembliesLoading"
          @change="onAssemblyChange"
        >
          <a-option
            v-for="asm in assemblies"
            :key="asm.id"
            :value="asm.id"
            :label="asm.name"
          >
            <div class="asm-option">
              <span class="asm-name">{{ asm.name }}</span>
              <span class="asm-species">{{ asm.species }}</span>
              <a-tag v-if="!asm.fai_exists" size="small" color="red">缺少索引</a-tag>
            </div>
          </a-option>
        </a-select>

        <!-- 区域跳转 -->
        <a-input
          v-model="regionInput"
          placeholder="Chr1:1000000-2000000"
          style="width: 200px"
          @press-enter="jumpToRegion"
        >
          <template #prefix>
            <icon-location />
          </template>
        </a-input>

        <a-button type="primary" @click="loadBrowser">
          <template #icon><icon-refresh /></template>
          加载浏览器
        </a-button>

        <a-button @click="showUploadModal = true">
          <template #icon><icon-upload /></template>
          上传文件
        </a-button>

        <a-button @click="showScanDrawer = true">
          <template #icon><icon-folder /></template>
          我的文件
        </a-button>
      </div>
    </div>

    <!-- 已选轨道列表 -->
    <div v-if="selectedTracks.length > 0" class="track-bar">
      <span class="track-label">已选轨道:</span>
      <a-space wrap>
        <a-tag
          v-for="track in selectedTracks"
          :key="track.path"
          closable
          color="arcoblue"
          @close="removeTrack(track)"
        >
          {{ track.name }}
          <a-tag v-if="!track.indexed" size="mini" color="red">待索引</a-tag>
        </a-tag>
      </a-space>
    </div>

    <!-- JBrowse 2 渲染区 -->
    <div class="browser-view">
      <iframe
        v-if="jbrowseUrl"
        ref="jbrowseFrame"
        :src="jbrowseUrl"
        frameborder="0"
        class="jbrowse-iframe"
      />
      <div v-else class="empty-state">
        <a-empty>
          <template #image>
            <icon-desktop style="font-size: 64px; color: var(--color-text-3)" />
          </template>
          <template #description>
            <p>选择参考基因组和轨道后加载浏览器</p>
            <p class="hint">支持 BAM / BigWig / VCF / GFF3 等格式</p>
          </template>
        </a-empty>
      </div>
    </div>

    <!-- 上传文件弹窗 -->
    <a-modal
      v-model:visible="showUploadModal"
      title="上传轨道文件"
      width="600px"
      @ok="handleUpload"
      @cancel="resetUpload"
    >
      <a-form :model="uploadForm" layout="vertical">
        <a-form-item label="选择文件" required>
          <a-upload
            v-model:file-list="uploadForm.files"
            :auto-upload="false"
            :multiple="true"
            :limit="5"
            draggable
            accept=".bam,.cram,.bw,.bigwig,.vcf,.vcf.gz,.bed,.bed.gz,.gff3,.gff3.gz,.fasta,.fa"
          >
            <template #upload-button>
              <div class="upload-drag-area">
                <icon-upload style="font-size: 32px; color: var(--color-text-3)" />
                <p>点击或拖拽文件到此处上传</p>
                <p class="hint">支持 BAM, BigWig, VCF, BED, GFF3, FASTA</p>
                <p class="hint">单个文件最大 10GB</p>
              </div>
            </template>
          </a-upload>
        </a-form-item>

        <a-form-item label="关联参考基因组">
          <a-select v-model="uploadForm.assemblyId" placeholder="可选：关联参考基因组">
            <a-option
              v-for="asm in assemblies"
              :key="asm.id"
              :value="asm.id"
            >
              {{ asm.name }}
            </a-option>
          </a-select>
        </a-form-item>

        <a-form-item>
          <a-checkbox v-model="uploadForm.autoIndex">
            上传后自动创建索引（推荐）
          </a-checkbox>
        </a-form-item>
      </a-form>

      <!-- 上传进度 -->
      <div v-if="uploadProgress.length > 0" class="upload-progress">
        <a-divider />
        <div v-for="item in uploadProgress" :key="item.filename" class="progress-item">
          <div class="progress-header">
            <span>{{ item.filename }}</span>
            <a-tag :color="item.status === 'success' ? 'green' : item.status === 'error' ? 'red' : 'blue'">
              {{ item.statusText }}
            </a-tag>
          </div>
          <a-progress
            v-if="item.status === 'uploading'"
            :percent="item.percent"
            size="small"
            :animation="true"
          />
          <p v-if="item.message" class="progress-message">{{ item.message }}</p>
        </div>
      </div>
    </a-modal>

    <!-- 文件扫描抽屉 -->
    <a-drawer
      v-model:visible="showScanDrawer"
      title="我的文件"
      width="480px"
      :footer="false"
    >
      <a-spin :loading="scanLoading" style="width: 100%">
        <div class="scan-actions">
          <a-button type="primary" size="small" @click="refreshScan">
            <template #icon><icon-refresh /></template>
            刷新
          </a-button>
          <a-button size="small" @click="selectAllIndexed">
            选中所有已索引
          </a-button>
        </div>

        <a-list :bordered="false">
          <a-list-item v-for="file in scannedFiles" :key="file.path">
            <a-list-item-meta>
              <template #title>
                <div class="file-title">
                  <a-checkbox
                    v-model="file.selected"
                    :disabled="!file.can_load"
                    @change="toggleFile(file)"
                  />
                  <span :class="{ 'text-disabled': !file.can_load }">{{ file.name }}</span>
                </div>
              </template>
              <template #description>
                <div class="file-meta">
                  <a-tag size="mini">{{ file.type }}</a-tag>
                  <span>{{ file.size_human }}</span>
                  <span>{{ file.modified }}</span>
                </div>
              </template>
            </a-list-item-meta>
            <template #actions>
              <a-tag v-if="file.indexed" size="small" color="green">已索引</a-tag>
              <a-button
                v-else
                type="text"
                size="mini"
                @click="createIndex(file)"
              >
                创建索引
              </a-button>
            </template>
          </a-list-item>
        </a-list>

        <a-empty v-if="scannedFiles.length === 0 && !scanLoading" description="暂无文件" />
      </a-spin>

      <template #footer>
        <a-button type="primary" @click="loadSelectedFiles">
          加载选中文件 ({{ selectedScanFiles.length }})
        </a-button>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import {
  IconLeft,
  IconLocation,
  IconRefresh,
  IconUpload,
  IconFolder,
  IconDesktop
} from '@arco-design/web-vue/es/icon'

const route = useRoute()
const router = useRouter()

// ==================== 状态 ====================
const assemblies = ref([])
const assembliesLoading = ref(false)
const selectedAssembly = ref('')
const regionInput = ref('')
const jbrowseUrl = ref('')
const selectedTracks = ref([])

// 上传
const showUploadModal = ref(false)
const uploadForm = ref({
  files: [],
  assemblyId: '',
  autoIndex: true
})
const uploadProgress = ref([])

// 扫描
const showScanDrawer = ref(false)
const scanLoading = ref(false)
const scannedFiles = ref([])

// ==================== 计算属性 ====================
const selectedScanFiles = computed(() => 
  scannedFiles.value.filter(f => f.selected)
)

// ==================== 生命周期 ====================
onMounted(async () => {
  await loadAssemblies()

  // 从 URL 参数恢复状态
  const { assembly, tracks, region, autoLoad } = route.query
  if (assembly) {
    selectedAssembly.value = assembly
  }
  if (region) {
    regionInput.value = region
  }
  if (autoLoad) {
    // 从数据管理模块跳转过来，自动加载
    selectedTracks.value.push({
      path: autoLoad,
      name: autoLoad.split('/').pop(),
      indexed: true
    })
    await loadBrowser()
  }
})

// ==================== API 调用 ====================
const loadAssemblies = async () => {
  assembliesLoading.value = true
  try {
    const res = await fetch('/api/jbrowse/assemblies')
    const data = await res.json()
    assemblies.value = data.assemblies || []

    // 默认选择第一个有索引的
    const available = assemblies.value.find(a => a.fai_exists)
    if (available && !selectedAssembly.value) {
      selectedAssembly.value = available.id
    }
  } catch (e) {
    Message.error('加载参考基因组失败')
  } finally {
    assembliesLoading.value = false
  }
}

const loadBrowser = async () => {
  if (!selectedAssembly.value) {
    Message.warning('请先选择参考基因组')
    return
  }

  const trackPaths = selectedTracks.value.map(t => t.path)
  const params = new URLSearchParams()
  params.set('assembly', selectedAssembly.value)
  if (trackPaths.length > 0) {
    trackPaths.forEach(p => params.append('tracks', p))
  }
  if (regionInput.value) {
    params.set('region', regionInput.value)
  }

  // 生成 JBrowse 2 URL
  const configUrl = `/api/jbrowse/config?${params.toString()}`
  jbrowseUrl.value = `/jbrowse2/?config=${encodeURIComponent(configUrl)}`

  // 更新 URL，方便分享
  router.replace({
    query: {
      assembly: selectedAssembly.value,
      tracks: trackPaths,
      region: regionInput.value || undefined
    }
  })
}

const onAssemblyChange = () => {
  // 切换参考基因组时，清空已选轨道（因为轨道是 assembly 相关的）
  selectedTracks.value = []
  jbrowseUrl.value = ''
}

const jumpToRegion = () => {
  if (!jbrowseUrl.value) {
    loadBrowser()
    return
  }
  // 如果浏览器已加载，通过 postMessage 与 iframe 通信跳转
  // 或者重新加载配置
  loadBrowser()
}

// ==================== 轨道管理 ====================
const removeTrack = (track) => {
  const idx = selectedTracks.value.findIndex(t => t.path === track.path)
  if (idx > -1) {
    selectedTracks.value.splice(idx, 1)
    loadBrowser()
  }
}

// ==================== 上传 ====================
const handleUpload = async () => {
  if (uploadForm.value.files.length === 0) {
    Message.warning('请选择要上传的文件')
    return
  }

  uploadProgress.value = uploadForm.value.files.map(f => ({
    filename: f.name,
    status: 'uploading',
    statusText: '上传中',
    percent: 0,
    message: ''
  }))

  // 逐个上传
  for (let i = 0; i < uploadForm.value.files.length; i++) {
    const file = uploadForm.value.files[i]
    const progress = uploadProgress.value[i]

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch(
        `/api/jbrowse/upload?user_id=${getUserId()}&assembly_id=${uploadForm.value.assemblyId}&auto_index=${uploadForm.value.autoIndex}`,
        {
          method: 'POST',
          body: formData
        }
      )

      const data = await res.json()

      if (res.ok) {
        progress.status = 'success'
        progress.statusText = '上传成功'
        progress.percent = 100
        progress.message = data.index_task_id ? '索引任务已排队' : ''

        // 自动添加到轨道
        selectedTracks.value.push({
          path: data.saved_path,
          name: data.filename,
          indexed: true
        })
      } else {
        progress.status = 'error'
        progress.statusText = '上传失败'
        progress.message = data.detail?.errors?.join(', ') || '未知错误'
      }
    } catch (e) {
      progress.status = 'error'
      progress.statusText = '上传失败'
      progress.message = e.message
    }
  }

  // 刷新扫描列表
  await refreshScan()

  // 延迟关闭弹窗
  setTimeout(() => {
    showUploadModal.value = false
    resetUpload()
  }, 2000)
}

const resetUpload = () => {
  uploadForm.value = { files: [], assemblyId: '', autoIndex: true }
  uploadProgress.value = []
}

// ==================== 扫描 ====================
const refreshScan = async () => {
  scanLoading.value = true
  try {
    const res = await fetch(`/api/jbrowse/scan?user_id=${getUserId()}`)
    const data = await res.json()

    scannedFiles.value = (data.files || []).map(f => ({
      ...f,
      selected: selectedTracks.value.some(t => t.path === f.path)
    }))
  } catch (e) {
    Message.error('扫描文件失败')
  } finally {
    scanLoading.value = false
  }
}

const toggleFile = (file) => {
  if (file.selected) {
    if (!selectedTracks.value.some(t => t.path === file.path)) {
      selectedTracks.value.push({
        path: file.path,
        name: file.name,
        indexed: file.indexed
      })
    }
  } else {
    const idx = selectedTracks.value.findIndex(t => t.path === file.path)
    if (idx > -1) selectedTracks.value.splice(idx, 1)
  }
}

const selectAllIndexed = () => {
  scannedFiles.value.forEach(f => {
    if (f.indexed) {
      f.selected = true
      toggleFile(f)
    }
  })
}

const loadSelectedFiles = () => {
  loadBrowser()
  showScanDrawer.value = false
}

const createIndex = async (file) => {
  try {
    const res = await fetch(`/api/jbrowse/index/create?file_path=${encodeURIComponent(file.path)}`, {
      method: 'POST'
    })
    const data = await res.json()

    if (res.ok) {
      Message.success(`索引任务已提交: ${data.task_id}`)
      file.indexStatus = 'queued'
    } else {
      Message.error(data.detail || '索引提交失败')
    }
  } catch (e) {
    Message.error('索引提交失败')
  }
}

// ==================== 工具函数 ====================
const getUserId = () => {
  // 从 store 或 localStorage 获取用户 ID
  // 这里简化处理
  return localStorage.getItem('user_id') || 'default'
}

// 监听扫描抽屉打开
watch(showScanDrawer, (val) => {
  if (val) refreshScan()
})
</script>

<style scoped>
.jbrowse-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--color-fill-2);
}

.control-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--color-bg-2);
  border-bottom: 1px solid var(--color-border);
}

.left-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-1);
}

.right-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.track-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 24px;
  background: var(--color-bg-2);
  border-bottom: 1px solid var(--color-border);
}

.track-label {
  font-size: 13px;
  color: var(--color-text-2);
  white-space: nowrap;
}

.browser-view {
  flex: 1;
  overflow: hidden;
  background: var(--color-bg-1);
}

.jbrowse-iframe {
  width: 100%;
  height: 100%;
  border: none;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.hint {
  font-size: 13px;
  color: var(--color-text-3);
  margin-top: 4px;
}

/* 上传弹窗 */
.upload-drag-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  border: 2px dashed var(--color-border);
  border-radius: 8px;
  background: var(--color-fill-2);
  transition: all 0.2s;
}

.upload-drag-area:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light-1);
}

.upload-progress {
  margin-top: 16px;
}

.progress-item {
  margin-bottom: 12px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.progress-message {
  font-size: 12px;
  color: var(--color-text-3);
  margin-top: 4px;
}

/* 扫描抽屉 */
.scan-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.file-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-text-3);
}

.text-disabled {
  color: var(--color-text-4);
}

/* 参考基因组选项 */
.asm-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.asm-name {
  font-weight: 500;
}

.asm-species {
  font-size: 12px;
  color: var(--color-text-3);
}
</style>
