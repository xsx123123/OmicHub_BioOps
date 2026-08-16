<script setup lang="ts">
import { ref } from 'vue'
import { NAlert, NIcon, NTabPane, NTabs } from 'naive-ui'
import { FlaskOutline } from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
// PCR / 克隆
import MasterMixCalc from './components/wetlab/MasterMixCalc.vue'
import LigationCalc from './components/wetlab/LigationCalc.vue'
import CopyNumberCalc from './components/wetlab/CopyNumberCalc.vue'
import QpcrCalc from './components/wetlab/QpcrCalc.vue'
import NucConvertCalc from './components/wetlab/NucConvertCalc.vue'
// NGS 建库
import PoolingCalc from './components/wetlab/PoolingCalc.vue'
import BeadsCalc from './components/wetlab/BeadsCalc.vue'
// 序列处理
import PrimerCalc from './components/wetlab/PrimerCalc.vue'
// 溶液 / 缓冲液
import DilutionCalc from './components/wetlab/DilutionCalc.vue'
import MolarCalc from './components/wetlab/MolarCalc.vue'
import RcfCalc from './components/wetlab/RcfCalc.vue'
import BufferCalc from './components/wetlab/BufferCalc.vue'

const activeTab = ref('pcr')
</script>

<template>
  <div class="wetlab-calculators-page">
    <PageHeader
      title="湿实验计算器"
      subtitle="PCR/克隆、NGS 建库、序列处理与溶液配制等常用湿实验计算，纯本地运算"
      back-to="/tools"
      back-label="返回工具箱"
    />

    <NAlert type="info" :bordered="false" class="local-alert">
      <template #icon><NIcon><FlaskOutline /></NIcon></template>
      纯本地运算，数据不离开浏览器；每个计算器均可一键载入示例与复制结果。
    </NAlert>

    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="pcr" tab="PCR / 克隆">
        <MasterMixCalc />
        <LigationCalc />
        <CopyNumberCalc />
        <QpcrCalc />
        <NucConvertCalc />
      </NTabPane>

      <NTabPane name="ngs" tab="NGS 建库">
        <PoolingCalc />
        <BeadsCalc />
      </NTabPane>

      <NTabPane name="seq" tab="序列处理">
        <PrimerCalc />
      </NTabPane>

      <NTabPane name="buffer" tab="溶液 / 缓冲液">
        <DilutionCalc />
        <MolarCalc />
        <RcfCalc />
        <BufferCalc />
      </NTabPane>
    </NTabs>
  </div>
</template>

<!-- 共享样式以非 scoped 方式全局引入，供各计算器子组件复用 wlc-* 类名 -->
<style>
@import './components/wetlab/wetlab-shared.css';
</style>

<style scoped>
.wetlab-calculators-page {
  padding: 16px;
  min-height: 100%;
}
.local-alert {
  margin-bottom: 12px;
}
@media (max-width: 768px) {
  .wetlab-calculators-page {
    padding: 12px;
  }
}
</style>
