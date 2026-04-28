<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">实时诊断</h2>
      <el-tag :type="overall.type" effect="plain">{{ overall.label }}</el-tag>
    </div>
    <div class="section-body">
      <div class="diagnostic-grid">
        <div v-for="item in diagnosticItems" :key="item.label" class="diagnostic-card" :class="item.type">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <em>{{ item.hint }}</em>
        </div>
      </div>

      <div class="diagnostic-list">
        <el-alert
          v-for="item in adviceItems"
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
  progress: {
    type: Object,
    default: null
  },
  logs: {
    type: Array,
    default: () => []
  },
  socketStatus: {
    type: String,
    default: 'connecting'
  }
})

const completed = computed(() => Number(props.progress?.completed_requests || 0))
const failed = computed(() => Number(props.progress?.failed_requests || 0))
const successRate = computed(() => {
  const value = props.progress?.success_rate
  return value === undefined || value === null ? null : Number(value)
})
const failureRate = computed(() => {
  if (successRate.value === null) return completed.value ? failed.value / completed.value : 0
  return Math.max(0, 1 - successRate.value)
})
const avgLatency = computed(() => Number(props.progress?.avg_latency_sec || 0))
const recentErrors = computed(() => props.logs.filter((item) => ['error', 'warning'].includes(item.level)).slice(-8))
const errorKeywords = computed(() => {
  const counts = {}
  recentErrors.value.forEach((item) => {
    const message = String(item.message || '').toLowerCase()
    let key = '其他'
    if (message.includes('timeout') || message.includes('超时')) key = '超时'
    else if (message.includes('429') || message.includes('rate') || message.includes('limit') || message.includes('限流')) key = '限流'
    else if (message.includes('401') || message.includes('403') || message.includes('auth') || message.includes('key')) key = '认证'
    else if (message.includes('5')) key = '服务端'
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})
const topError = computed(() => {
  const entries = Object.entries(errorKeywords.value).sort((a, b) => b[1] - a[1])
  return entries[0]?.[0] || '无'
})
const overall = computed(() => {
  if (failureRate.value >= 0.1 || topError.value !== '无') return { label: '需要关注', type: 'warning' }
  if (props.socketStatus === 'fallback') return { label: '连接降级', type: 'warning' }
  if (completed.value > 0) return { label: '运行正常', type: 'success' }
  return { label: '等待数据', type: 'info' }
})
const diagnosticItems = computed(() => [
  {
    label: '失败率',
    value: percent(failureRate.value),
    hint: `${number(failed.value)} 次失败`,
    type: failureRate.value >= 0.1 ? 'danger' : failureRate.value > 0 ? 'warning' : 'ok'
  },
  {
    label: '错误类型',
    value: topError.value,
    hint: `${recentErrors.value.length} 条告警/错误日志`,
    type: topError.value === '无' ? 'ok' : 'warning'
  },
  {
    label: '平均延迟',
    value: seconds(avgLatency.value),
    hint: '最近窗口',
    type: avgLatency.value >= 10 ? 'warning' : 'ok'
  },
  {
    label: '实时通道',
    value: props.socketStatus === 'connected' ? 'WebSocket' : '轮询',
    hint: props.socketStatus === 'connected' ? '实时连接正常' : '已使用轮询兜底',
    type: props.socketStatus === 'connected' ? 'ok' : 'warning'
  }
])
const adviceItems = computed(() => {
  const items = []
  if (topError.value === '认证') {
    items.push({
      title: '认证错误较多',
      description: '请检查 API Key、协议类型和对应 Header 是否匹配。',
      type: 'error'
    })
  }
  if (topError.value === '限流') {
    items.push({
      title: '疑似触发限流',
      description: '建议降低并发或增加请求间隔，再观察 RPM/TPM 是否恢复稳定。',
      type: 'warning'
    })
  }
  if (topError.value === '超时') {
    items.push({
      title: '请求超时增加',
      description: '建议提高 timeout，或降低输入 Token/并发来确认瓶颈来源。',
      type: 'warning'
    })
  }
  if (failureRate.value >= 0.1) {
    items.push({
      title: '失败率偏高',
      description: '当前失败率超过 10%，报告中的吞吐指标可能不能代表稳定容量。',
      type: 'warning'
    })
  }
  if (avgLatency.value >= 10) {
    items.push({
      title: '延迟偏高',
      description: '建议重点查看报告中的 P95/P99、TTFT 和 Decode 分布。',
      type: 'info'
    })
  }
  if (!items.length) {
    items.push({
      title: '暂未发现明显异常',
      description: '继续观察实时吞吐和成功率，完成后查看报告确认尾延迟。',
      type: 'success'
    })
  }
  return items
})

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })
}

function percent(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function seconds(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${Number(value).toFixed(3)}s`
}
</script>

<style scoped>
.diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.diagnostic-card {
  min-height: 88px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #f8fbff;
}

.diagnostic-card.warning {
  border-color: #fed7aa;
  background: #fff7ed;
}

.diagnostic-card.danger {
  border-color: #fecaca;
  background: #fff1f2;
}

.diagnostic-card span,
.diagnostic-card em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.diagnostic-card strong {
  display: block;
  margin: 8px 0 4px;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 20px;
}

.diagnostic-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

@media (max-width: 960px) {
  .diagnostic-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .diagnostic-grid {
    grid-template-columns: 1fr;
  }
}
</style>
