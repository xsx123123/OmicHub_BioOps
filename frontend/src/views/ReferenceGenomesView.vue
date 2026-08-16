<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NEmpty, NIcon, NInput, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import {
  AddOutline,
  ArrowForwardOutline,
  CheckmarkCircleOutline,
  SearchOutline,
} from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import { fetchSpecies, globalSearch } from '@/api/referenceGenomes'
import type {
  BuildStatus,
  DataFileType,
  DatabaseDataFile,
  GenomeVersion,
  SearchResult,
  SpeciesDatabase,
} from '@/types/referenceGenomes'

const router = useRouter()
const message = useMessage()

const speciesList = ref<SpeciesDatabase[]>([])
const loading = ref(false)
const searchQuery = ref('')
const categoryFilter = ref<'all' | 'plant' | 'animal' | 'microbe'>('all')
const statusFilter = ref<'all' | BuildStatus>('all')
const sortBy = ref<'default' | 'species' | 'genes' | 'versions'>('default')
const defaultVersionBySpecies = ref<Record<string, string>>({})

const categoryOptions = [
  { label: '全部分类', value: 'all' },
  { label: '植物', value: 'plant' },
  { label: '动物', value: 'animal' },
  { label: '微生物', value: 'microbe' },
]

const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '就绪', value: 'ready' },
  { label: '构建中', value: 'building' },
  { label: '缺失文件', value: 'missing' },
  { label: '异常', value: 'error' },
]

const sortOptions = [
  { label: '默认排序', value: 'default' },
  { label: '按物种名称', value: 'species' },
  { label: '按基因数量', value: 'genes' },
  { label: '按版本数量', value: 'versions' },
]

const sourceOrder: DataFileType[] = ['fasta', 'gff', 'go', 'kegg']
const sourceLabel: Record<DataFileType, string> = {
  fasta: 'FA',
  gff: 'GFF',
  go: 'GO',
  kegg: 'KEGG',
}

/* ────── 辅助函数（原 mock 中内联） ────── */

function getDefaultGenomeVersion(species: SpeciesDatabase): GenomeVersion {
  return species.genomeVersions.find((v) => v.isDefault) ?? species.genomeVersions[0]
}

function getDataFileEntries(version: GenomeVersion): DatabaseDataFile[] {
  return (['fasta', 'gff', 'go', 'kegg'] as DataFileType[])
    .map((key) => version.dataFiles[key])
    .filter((file): file is DatabaseDataFile => Boolean(file))
}

function getSpeciesBuildStatus(species: SpeciesDatabase): BuildStatus {
  const files = species.genomeVersions.flatMap(getDataFileEntries)
  if (files.some((f) => f.buildStatus === 'error')) return 'error'
  if (files.some((f) => f.buildStatus === 'building')) return 'building'
  if (files.some((f) => f.buildStatus === 'missing')) return 'missing'
  return 'ready'
}

function countGenes(species: SpeciesDatabase) {
  return species.genomeVersions.reduce((sum, v) => sum + v.stats.totalGenes, 0)
}

function countReadyFiles(species: SpeciesDatabase) {
  return species.genomeVersions
    .flatMap(getDataFileEntries)
    .filter((file) => file.buildStatus === 'ready').length
}

/* ────── 数据加载 ────── */

onMounted(async () => {
  loading.value = true
  try {
    const res = await fetchSpecies()
    speciesList.value = res.species
    defaultVersionBySpecies.value = Object.fromEntries(
      res.species.map((s) => [s.id, getDefaultGenomeVersion(s).versionId]),
    )
  } catch (e) {
    message.error('加载参考基因组数据失败')
  } finally {
    loading.value = false
  }
})

/* ────── 全局搜索（防抖 + 下拉） ────── */

const searchResult = ref<SearchResult | null>(null)
const searchLoading = ref(false)
const showDropdown = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q.trim()) {
    searchResult.value = null
    showDropdown.value = false
    return
  }
  searchTimer = setTimeout(async () => {
    searchLoading.value = true
    showDropdown.value = true
    try {
      searchResult.value = await globalSearch({ q: q.trim(), limit: 5 })
    } catch {
      searchResult.value = null
    } finally {
      searchLoading.value = false
    }
  }, 300)
})

function onSearchFocus() {
  if (searchResult.value && searchQuery.value.trim()) showDropdown.value = true
}

function onSearchBlur() {
  // 延迟关闭，让点击事件有机会触发
  setTimeout(() => { showDropdown.value = false }, 200)
}

function hitGene(g: { versionId: string; geneId: string }) {
  showDropdown.value = false
  searchQuery.value = ''
  router.push(`/database/${g.versionId}?gene=${encodeURIComponent(g.geneId)}`)
}

function hitSpecies(s: { commonName: string }) {
  showDropdown.value = false
  searchQuery.value = s.commonName
}

function hitGo(g: { versionId: string; goId: string }) {
  showDropdown.value = false
  searchQuery.value = ''
  router.push(`/database/${g.versionId}?go=${encodeURIComponent(g.goId)}`)
}

function hitKegg(k: { versionId: string; id: string }) {
  showDropdown.value = false
  searchQuery.value = ''
  router.push(`/database/${k.versionId}?kegg=${encodeURIComponent(k.id)}`)
}

/* ────── 列表过滤与排序 ────── */

const summary = computed(() => {
  const list = speciesList.value
  const versions = list.flatMap((s) => s.genomeVersions)
  const files = versions.flatMap(getDataFileEntries)
  return {
    totalSpecies: list.length,
    totalVersions: versions.length,
    totalGenes: versions.reduce((sum, v) => sum + v.stats.totalGenes, 0),
    readyFiles: files.filter((f) => f.buildStatus === 'ready').length,
    totalFiles: files.length,
  }
})

const filteredSpecies = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  let list = speciesList.value.filter((species) => {
    if (categoryFilter.value !== 'all' && species.category !== categoryFilter.value) return false
    const status = getSpeciesBuildStatus(species)
    if (statusFilter.value !== 'all' && status !== statusFilter.value) return false
    if (!query) return true
    return [
      species.commonName,
      species.scientificName,
      species.taxonomyId,
      species.description,
      ...species.genomeVersions.flatMap((v) => [v.versionName, v.assemblyName, ...v.tags]),
    ].some((value) => value.toLowerCase().includes(query))
  })

  if (sortBy.value === 'species') {
    list = [...list].sort((a, b) => a.scientificName.localeCompare(b.scientificName))
  }
  if (sortBy.value === 'genes') {
    list = [...list].sort((a, b) => countGenes(b) - countGenes(a))
  }
  if (sortBy.value === 'versions') {
    list = [...list].sort((a, b) => b.genomeVersions.length - a.genomeVersions.length)
  }
  return list
})

function effectiveDefaultVersion(species: SpeciesDatabase) {
  return species.genomeVersions.find((v) => v.versionId === defaultVersionBySpecies.value[species.id])
    ?? getDefaultGenomeVersion(species)
}

function versionStatusType(status: BuildStatus): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (status === 'ready') return 'success'
  if (status === 'building') return 'warning'
  if (status === 'error') return 'error'
  if (status === 'missing') return 'default'
  return 'info'
}

function statusText(status: BuildStatus) {
  if (status === 'ready') return '就绪'
  if (status === 'building') return '构建中'
  if (status === 'missing') return '缺失'
  return '异常'
}

function fileEnabled(version: GenomeVersion, type: DataFileType) {
  return version.dataFiles[type]?.buildStatus === 'ready'
}

function openVersion(version: GenomeVersion) {
  router.push(`/database/${version.versionId}`)
}

function setDefault(species: SpeciesDatabase, version: GenomeVersion) {
  defaultVersionBySpecies.value = { ...defaultVersionBySpecies.value, [species.id]: version.versionId }
  message.success(`已将 ${species.commonName} ${version.versionName} 设为默认数据库版本`)
}

function openRegisterDialog() {
  message.info('数据库注册当前通过 YAML 配置接入：编辑 databases.yaml / jbrowse_config.yaml 后热重载')
}
</script>

<template>
  <div class="database-page" role="main" aria-label="参考基因组数据库">
    <PageHeader title="参考基因组数据库" subtitle="集中管理 FA、GFF、GO、KEGG 与跨版本基因映射。">
      <template #actions>
        <NButton type="primary" secondary class="register-button" @click="openRegisterDialog">
          <template #icon><NIcon><AddOutline /></NIcon></template>
          注册数据库
        </NButton>
      </template>
    </PageHeader>

    <NSpin :show="loading">
      <section class="summary-grid">
        <div class="summary-item">
          <span class="summary-label">物种</span>
          <span class="summary-value">{{ summary.totalSpecies }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">版本</span>
          <span class="summary-value">{{ summary.totalVersions }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">基因</span>
          <span class="summary-value">{{ summary.totalGenes.toLocaleString() }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">数据文件</span>
          <span class="summary-value">{{ summary.readyFiles }}/{{ summary.totalFiles }}</span>
        </div>
      </section>

      <section class="toolbar">
        <div class="search-input-wrap">
          <NInput
            v-model:value="searchQuery"
            clearable
            placeholder="搜索物种、版本、Taxonomy ID 或注释关键词"
            class="search-input"
            @focus="onSearchFocus"
            @blur="onSearchBlur"
          >
            <template #prefix><NIcon><SearchOutline /></NIcon></template>
          </NInput>
          <div v-if="showDropdown && searchQuery.trim()" class="global-search-dropdown">
            <div v-if="searchLoading" class="dropdown-loading">搜索中...</div>
            <template v-else-if="searchResult">
              <template v-if="searchResult.genes.length">
                <div class="dropdown-group-title">基因</div>
                <button
                  v-for="g in searchResult.genes.slice(0, 5)"
                  :key="`${g.versionId}-${g.geneId}`"
                  class="dropdown-item"
                  @mousedown.prevent="hitGene(g)"
                >
                  <span class="mono">{{ g.geneId }}</span>
                  <span class="dropdown-item-sub">{{ g.geneName }} · {{ g.chromosome }}</span>
                </button>
              </template>
              <template v-if="searchResult.goTerms.length">
                <div class="dropdown-group-title">GO 术语</div>
                <button
                  v-for="g in searchResult.goTerms.slice(0, 5)"
                  :key="`${g.versionId}-${g.goId}`"
                  class="dropdown-item"
                  @mousedown.prevent="hitGo(g)"
                >
                  <span class="mono">{{ g.goId }}</span>
                  <span class="dropdown-item-sub">{{ g.name }} ({{ g.geneCount }})</span>
                </button>
              </template>
              <template v-if="searchResult.kegg.length">
                <div class="dropdown-group-title">KEGG 通路</div>
                <button
                  v-for="k in searchResult.kegg.slice(0, 5)"
                  :key="`${k.versionId}-${k.id}`"
                  class="dropdown-item"
                  @mousedown.prevent="hitKegg(k)"
                >
                  <span class="mono">{{ k.id }}</span>
                  <span class="dropdown-item-sub">{{ k.name }} ({{ k.geneCount }})</span>
                </button>
              </template>
              <template v-if="searchResult.species.length">
                <div class="dropdown-group-title">物种</div>
                <button
                  v-for="s in searchResult.species.slice(0, 5)"
                  :key="s.speciesId"
                  class="dropdown-item"
                  @mousedown.prevent="hitSpecies(s)"
                >
                  <span>{{ s.commonName }}</span>
                  <span class="dropdown-item-sub">{{ s.match }}</span>
                </button>
              </template>
              <div
                v-if="!searchResult.genes.length && !searchResult.goTerms.length && !searchResult.kegg.length && !searchResult.species.length"
                class="dropdown-empty"
              >
                无匹配结果
              </div>
            </template>
          </div>
        </div>
        <NSelect v-model:value="categoryFilter" :options="categoryOptions" class="filter-select" />
        <NSelect v-model:value="statusFilter" :options="statusOptions" class="filter-select" />
        <NSelect v-model:value="sortBy" :options="sortOptions" class="sort-select" />
      </section>

      <section v-if="filteredSpecies.length" class="species-grid">
        <article
          v-for="species in filteredSpecies"
          :key="species.id"
          class="species-card"
        >
          <header class="species-header">
            <div class="species-icon" :style="{ background: species.gradient }">{{ species.icon }}</div>
            <div class="species-title-block">
              <div class="species-title-row">
                <h2>{{ species.commonName }}</h2>
                <NTag size="small" :type="versionStatusType(getSpeciesBuildStatus(species))" round>
                  {{ statusText(getSpeciesBuildStatus(species)) }}
                </NTag>
              </div>
              <p class="species-latin">{{ species.scientificName }}</p>
              <p class="species-desc">{{ species.description }}</p>
            </div>
          </header>

          <div class="default-version">
            <div class="version-main">
              <span class="version-name">{{ effectiveDefaultVersion(species).versionName }}</span>
              <span class="assembly-name">{{ effectiveDefaultVersion(species).assemblyName }}</span>
            </div>
            <div class="version-tags">
              <NTag
                v-for="tag in effectiveDefaultVersion(species).tags"
                :key="tag"
                size="tiny"
                round
                type="info"
              >{{ tag }}</NTag>
            </div>
          </div>

          <div class="source-row">
            <span
              v-for="source in sourceOrder"
              :key="source"
              class="source-chip"
              :class="{ ready: fileEnabled(effectiveDefaultVersion(species), source) }"
            >{{ sourceLabel[source] }}</span>
          </div>

          <div class="metric-grid">
            <div>
              <span class="metric-value">{{ effectiveDefaultVersion(species).stats.chromosomes }}</span>
              <span class="metric-label">染色体</span>
            </div>
            <div>
              <span class="metric-value">{{ effectiveDefaultVersion(species).stats.totalGenes.toLocaleString() }}</span>
              <span class="metric-label">基因</span>
            </div>
            <div>
              <span class="metric-value">{{ effectiveDefaultVersion(species).stats.genomeSize }}</span>
              <span class="metric-label">大小</span>
            </div>
            <div>
              <span class="metric-value">{{ countReadyFiles(species) }}</span>
              <span class="metric-label">就绪文件</span>
            </div>
          </div>

          <div class="version-list">
            <button
              v-for="version in species.genomeVersions"
              :key="version.versionId"
              class="version-pill"
              :class="{ active: version.versionId === effectiveDefaultVersion(species).versionId }"
              @click="setDefault(species, version)"
            >
              <span>{{ version.versionName }}</span>
              <NIcon v-if="version.versionId === effectiveDefaultVersion(species).versionId" :size="14">
                <CheckmarkCircleOutline />
              </NIcon>
            </button>
          </div>

          <footer class="card-actions">
            <NButton type="primary" size="small" @click="openVersion(effectiveDefaultVersion(species))">
              查看数据库
              <template #icon><NIcon><ArrowForwardOutline /></NIcon></template>
            </NButton>
            <NButton size="small" quaternary @click="setDefault(species, effectiveDefaultVersion(species))">
              设为默认
            </NButton>
          </footer>
        </article>
      </section>

      <NEmpty v-else-if="!loading" class="empty-state" description="暂无匹配的数据库" />
    </NSpin>
  </div>
</template>

<style scoped>
.database-page {
  --db-primary: var(--brand-primary);
  --db-purple: #722ed1;
  --db-cyan: #0fc6c2;
  --db-text: var(--neutral-text-1);
  --db-subtext: var(--neutral-text-2);
  --db-muted: var(--neutral-text-3);
  --db-border: var(--neutral-border);
  --db-bg: var(--neutral-bg);
  --db-card: var(--neutral-card);
  --db-soft: var(--neutral-hover);
  --db-accent-soft: var(--brand-primary-light);
  min-height: 100%;
}

.register-button {
  border-radius: var(--radius-button);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 82px;
  padding: 16px;
  border: 1px solid var(--db-border);
  border-radius: 8px;
  background: var(--db-card);
}

.summary-label {
  color: var(--db-muted);
  font-size: 12px;
}

.summary-value {
  color: var(--db-text);
  font-size: 24px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid var(--db-border);
  border-radius: 8px;
  background: var(--db-card);
}

.search-input-wrap {
  position: relative;
  flex: 1 1 340px;
  min-width: 220px;
}

.search-input {
  width: 100%;
}

.filter-select {
  width: 136px;
}

.sort-select {
  width: 148px;
}

.global-search-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 100;
  max-height: 360px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--db-border);
  border-radius: 8px;
  background: var(--db-card);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
}

.dropdown-group-title {
  padding: 6px 8px 4px;
  color: var(--db-muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--db-text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.dropdown-item:hover {
  background: var(--db-soft);
}

.dropdown-item-sub {
  color: var(--db-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-loading,
.dropdown-empty {
  padding: 16px;
  color: var(--db-muted);
  font-size: 13px;
  text-align: center;
}

.species-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.species-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
  min-height: 330px;
  padding: 18px;
  border: none;
  border-radius: var(--radius-card);
  background: var(--db-card);
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.species-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
}

.species-header {
  display: flex;
  gap: 12px;
  min-width: 0;
}

.species-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  font-size: 23px;
}

.species-title-block {
  min-width: 0;
  flex: 1;
}

.species-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.species-title-row h2 {
  margin: 0;
  color: var(--db-text);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0;
}

.species-latin,
.species-desc {
  margin: 0;
  color: var(--db-muted);
  font-size: 12px;
  line-height: 1.45;
}

.species-latin {
  margin-top: 3px;
  font-style: italic;
}

.species-desc {
  margin-top: 5px;
  color: var(--db-subtext);
}

.default-version {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  background: var(--db-soft);
}

.version-main,
.metric-grid > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.version-name {
  color: var(--db-text);
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
}

.assembly-name,
.metric-label {
  color: var(--db-muted);
  font-size: 12px;
}

.assembly-name {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  word-break: break-word;
}

.version-tags {
  display: flex;
  align-content: flex-start;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}

.source-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.source-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 26px;
  min-width: 48px;
  padding: 0 10px;
  border: 1px dashed var(--db-border);
  border-radius: 6px;
  color: var(--db-muted);
  background: var(--db-soft);
  font-size: 12px;
  font-weight: 700;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.source-chip.ready {
  border-style: solid;
  border-color: color-mix(in srgb, var(--db-primary) 30%, transparent);
  color: var(--db-primary);
  background: var(--db-accent-soft);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.metric-grid > div {
  padding: 9px 10px;
  border-radius: 8px;
  background: var(--db-soft);
}

.metric-value {
  color: var(--db-text);
  font-size: 15px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.version-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.version-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--db-border);
  border-radius: 6px;
  background: var(--db-soft);
  color: var(--db-subtext);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.version-pill.active {
  border-color: color-mix(in srgb, var(--db-primary) 30%, transparent);
  color: var(--db-primary);
  background: var(--db-accent-soft);
}

.card-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
}

.empty-state {
  padding: 72px 24px;
  border: 1px solid var(--db-border);
  border-radius: 8px;
  background: var(--db-card);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .species-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .summary-grid,
  .species-grid,
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .filter-select,
  .sort-select {
    width: 100%;
  }

  .card-actions {
    flex-direction: column;
  }
}
</style>
