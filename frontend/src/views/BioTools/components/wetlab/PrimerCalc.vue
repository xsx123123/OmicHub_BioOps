<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCard, NIcon, NInput, NTag } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import { analyzePrimer, formatNum } from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const seqText = ref('CGTTGACCCGATATACGCGGTA')

const result = computed(() => analyzePrimer(seqText.value))

function loadSample() {
  seqText.value = 'CGTTGACCCGATATACGCGGTA'
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  return [
    `【引物分析】长度 ${r.length} nt，GC ${formatNum(r.gcPercent)}%`,
    `Tm（Wallace）≈ ${formatNum(r.tmWallace, 5)} ℃；Tm（盐校正）≈ ${formatNum(r.tmSalt, 5)} ℃`,
    `输入序列：${seqText.value.toUpperCase().replace(/\s+/g, '')}`,
    `反向互补：${r.reverseComplement}`,
  ].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">引物 Tm / 反向互补 / GC% 统计</div>
        <div class="wlc-desc">输入 DNA 序列（自动过滤空格与数字），即时统计长度、GC 含量、Tm 与反向互补序列。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <NInput
          v-model:value="seqText"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 8 }"
          placeholder="输入 DNA 序列，如 ATCGGCTA…"
        />
        <div class="wlc-stat-row">
          <NTag v-if="result.valid" size="small" :bordered="false">长度 {{ result.length }} nt</NTag>
          <NTag v-if="result.valid" size="small" :bordered="false" type="info">GC {{ formatNum(result.gcPercent) }}%</NTag>
          <NTag v-if="result.valid" size="small" :bordered="false" type="success">
            Tm ≈ {{ result.length < 14 ? formatNum(result.tmWallace, 5) : formatNum(result.tmSalt, 5) }} ℃
          </NTag>
        </div>
        <div class="wlc-hint">
          短引物（&lt;14 nt）参考 Wallace 法则 Tm = 2(A+T) + 4(G+C) = {{ formatNum(result.tmWallace, 5) }} ℃；
          较长序列参考盐校正经验式（[Na⁺]=50 mM）= {{ formatNum(result.tmSalt, 5) }} ℃。
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">反向互补序列</div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(result.reverseComplement, '反向互补序列')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-seq-out">{{ result.reverseComplement }}</div>
          <div class="wlc-sub">
            碱基组成：A {{ result.counts.A }} · T {{ result.counts.T }} · G {{ result.counts.G }} · C {{ result.counts.C }}
            <template v-if="result.counts.other"> · 其他 {{ result.counts.other }}</template>
          </div>
          <div class="wlc-sub">
            反向：{{ result.reverse }}<br />
            互补：{{ result.complement }}
          </div>
        </template>
        <div v-else class="wlc-empty">输入 DNA 序列后自动统计</div>
        <div class="wlc-formula">
          Wallace 法则（短引物）：Tm = 2(A+T) + 4(G+C)；
          盐校正经验式：Tm = 81.5 + 16.6·log₁₀[Na⁺] + 0.41·GC% − 675/L。GC% = (G+C)/长度。
        </div>
      </div>
    </div>
  </NCard>
</template>
