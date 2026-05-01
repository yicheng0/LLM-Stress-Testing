<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">
        <span :class="['status-dot', `status-${status}`]" />
        {{ statusText }}
      </h2>
      <div class="toolbar">
        <el-button
          v-if="canStop"
          type="warning"
          :icon="SwitchButton"
          :loading="stopping"
          :disabled="stopping || status === 'stopping'"
          @click="$emit('stop')"
        >
          {{ stopping || status === 'stopping' ? '停止中' : '停止任务' }}
        </el-button>
        <el-button v-if="canReport" type="primary" :icon="DataAnalysis" @click="$emit('report')">
          查看报告
        </el-button>
      </div>
    </div>
    <div class="section-body">
      <el-progress :percentage="progressPercent" :status="progressStatus" />
      <div class="progress-grid">
        <div>
          <span class="muted">已完成</span>
          <strong>{{ number(progress?.completed_requests) }}</strong>
        </div>
        <div>
          <span class="muted">成功</span>
          <strong>{{ number(progress?.successful_requests) }}</strong>
        </div>
        <div>
          <span class="muted">失败</span>
          <strong>{{ number(progress?.failed_requests) }}</strong>
        </div>
        <div>
          <span class="muted">实际运行时长</span>
          <strong>{{ duration(actualRuntimeSec) }}</strong>
        </div>
        <div>
          <span class="muted">预计剩余</span>
          <strong>{{ remainingText }}</strong>
        </div>
        <div>
          <span class="muted">最近更新</span>
          <strong class="compact">{{ datetime(progress?.updated_at) }}</strong>
        </div>
        <div>
          <span class="muted">Summary</span>
          <strong class="compact">{{ summaryText }}</strong>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { DataAnalysis, SwitchButton } from '@element-plus/icons-vue'

const props = defineProps({
  status: {
    type: String,
    default: 'queued'
  },
  progress: {
    type: Object,
    default: null
  },
  stopping: {
    type: Boolean,
    default: false
  }
})

defineEmits(['stop', 'report'])

const statusMap = {
  queued: '排队中',
  running: '运行中',
  stopping: '停止中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断'
}

const terminalStatuses = ['completed', 'failed', 'cancelled', 'interrupted']
const statusText = computed(() => statusMap[props.status] || props.status)
const canStop = computed(() => ['queued', 'running', 'stopping'].includes(props.status) || props.stopping)
const canReport = computed(() => terminalStatuses.includes(props.status))
const progressPercent = computed(() => {
  const elapsed = actualRuntimeSec.value
  const duration = Number(props.progress?.duration_sec || props.progress?.target_duration_sec || 0)
  if (duration > 0) {
    return Math.min(100, Math.round((elapsed / duration) * 100))
  }
  return terminalStatuses.includes(props.status) ? 100 : 0
})
const progressStatus = computed(() => {
  if (props.status === 'failed') return 'exception'
  if (props.status === 'completed') return 'success'
  return undefined
})
const actualRuntimeSec = computed(() => {
  const startedAt = Date.parse(props.progress?.started_at || '')
  const completedAt = Date.parse(props.progress?.completed_at || '')
  if (!Number.isNaN(startedAt) && !Number.isNaN(completedAt) && completedAt >= startedAt) {
    return (completedAt - startedAt) / 1000
  }
  const elapsed = Number(props.progress?.elapsed_sec || 0)
  if (elapsed > 0) return elapsed
  return 0
})
const remainingText = computed(() => {
  if (terminalStatuses.includes(props.status)) return '0s'
  const target = Number(props.progress?.duration_sec || props.progress?.target_duration_sec || 0)
  if (!target) return '-'
  return duration(Math.max(0, target - actualRuntimeSec.value))
})
const summaryText = computed(() => {
  if (props.progress?.final_summary) return '已拉取'
  if (props.progress?.final_summary_loading) return '拉取中'
  return terminalStatuses.includes(props.status) ? '待生成' : '运行中'
})

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString()
}

function duration(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  const total = Math.max(0, Math.round(Number(value)))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function datetime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(date)
}
</script>

<style scoped>
.progress-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.progress-grid > div {
  min-height: 64px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: #ffffff;
}

.progress-grid span,
.progress-grid strong {
  display: block;
}

.progress-grid strong {
  margin-top: 6px;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 18px;
}

.progress-grid strong.compact {
  font-family: inherit;
  font-size: 14px;
}

@media (max-width: 960px) {
  .progress-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
