<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">启动前风险评估</h2>
      <el-tag :type="riskTagType" effect="plain">{{ riskLevelText }}</el-tag>
    </div>
    <div class="section-body">
      <div class="risk-grid">
        <div v-for="item in summaryItems" :key="item.label" class="risk-metric">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <em>{{ item.sub }}</em>
        </div>
      </div>
      <div class="risk-list">
        <el-alert
          v-for="item in riskItems"
          :key="item.title"
          :title="item.title"
          :description="item.description"
          :type="item.type"
          show-icon
          :closable="false"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  config: {
    type: Object,
    required: true
  }
})

const matrixInputs = computed(() => parseNumberList(props.config.input_tokens_list))
const matrixConcurrency = computed(() => parseNumberList(props.config.concurrency_list))
const isMatrix = computed(() => Boolean(props.config.matrix_mode))
const pointCount = computed(() => (
  isMatrix.value ? matrixInputs.value.length * matrixConcurrency.value.length : 1
))
const maxConcurrency = computed(() => (
  isMatrix.value ? Math.max(0, ...matrixConcurrency.value) : Number(props.config.concurrency || 0)
))
const maxInputTokens = computed(() => (
  isMatrix.value ? Math.max(0, ...matrixInputs.value) : Number(props.config.input_tokens || 0)
))
const tokensPerRequest = computed(() => maxInputTokens.value + Number(props.config.max_output_tokens || 0))
const effectiveDuration = computed(() => (
  isMatrix.value ? Number(props.config.matrix_duration_sec || 0) : Number(props.config.duration_sec || 0)
))
const estimatedMinutes = computed(() => pointCount.value * effectiveDuration.value / 60)
const estimatedPeakTokens = computed(() => tokensPerRequest.value * maxConcurrency.value)
const riskScore = computed(() => riskItems.value.reduce((sum, item) => sum + item.score, 0))
const riskTagType = computed(() => {
  if (riskScore.value >= 8) return 'danger'
  if (riskScore.value >= 4) return 'warning'
  return 'success'
})
const riskLevelText = computed(() => {
  if (riskScore.value >= 8) return '高风险'
  if (riskScore.value >= 4) return '中风险'
  return '低风险'
})

const summaryItems = computed(() => [
  { label: '测试点', value: `${pointCount.value} 组`, sub: isMatrix.value ? '矩阵组合' : '单点测试' },
  { label: '峰值并发', value: number(maxConcurrency.value), sub: '最高并发压力' },
  { label: '峰值 Token 压力', value: compact(estimatedPeakTokens.value), sub: '单轮并发估算' },
  { label: '预计时长', value: `${number(estimatedMinutes.value)} 分钟`, sub: '不含排队和重试' }
])

const riskItems = computed(() => {
  const items = []
  if (maxConcurrency.value >= 300) {
    items.push({
      title: '并发压力较高',
      description: '建议确认本机网络、文件句柄和目标 API 限流策略，必要时分批测试。',
      type: 'warning',
      score: 3
    })
  }
  if (maxInputTokens.value >= 50000) {
    items.push({
      title: '长上下文输入会显著放大成本和延迟',
      description: '建议先用较低并发验证模型支持的上下文长度，再逐步提升压力。',
      type: 'warning',
      score: 3
    })
  }
  if (estimatedMinutes.value >= 30) {
    items.push({
      title: '测试持续时间较长',
      description: '长时间压测更容易遇到限流、网络抖动或服务端配额变化，请预留观察窗口。',
      type: 'info',
      score: 2
    })
  }
  if (isMatrix.value && pointCount.value >= 12) {
    items.push({
      title: '矩阵测试点较多',
      description: '建议先确认小矩阵结果稳定，再扩大输入 Token 和并发组合。',
      type: 'info',
      score: 2
    })
  }
  if (!props.config.enable_stream && Number(props.config.max_output_tokens || 0) >= 4096) {
    items.push({
      title: '非流式大输出可能导致单请求等待时间过长',
      description: '如目标协议支持，建议开启流式模式以观察 TTFT 和 Decode 性能。',
      type: 'warning',
      score: 2
    })
  }
  if (!items.length) {
    items.push({
      title: '当前配置风险较低',
      description: '可以直接启动测试，后续根据实时面板和报告结果继续调参。',
      type: 'success',
      score: 0
    })
  }
  return items
})

function parseNumberList(value) {
  return [...new Set(String(value || '')
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0))]
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })
}

function compact(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))
}
</script>

<style scoped>
.risk-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.risk-metric {
  min-height: 86px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #f8fbff;
}

.risk-metric span,
.risk-metric em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.risk-metric strong {
  display: block;
  margin: 8px 0 4px;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 22px;
}

.risk-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

@media (max-width: 960px) {
  .risk-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .risk-grid {
    grid-template-columns: 1fr;
  }
}
</style>
