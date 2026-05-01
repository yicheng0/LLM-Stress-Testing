<template>
  <div v-loading="loading">
    <ProgressPanel
      :status="task?.status || status"
      :progress="progressWithDuration"
      :stopping="stopping"
      @stop="confirmStop"
      @report="goReport"
    />

    <MetricCards :items="metricItems" />
    <div v-if="hasExpectedMetrics" class="section">
      <div class="section-header">
        <h2 class="section-title">预期达成</h2>
        <el-tag :type="achievementStatus.type" effect="plain">{{ achievementStatus.label }}</el-tag>
      </div>
      <div class="section-body">
        <MetricCards :items="achievementItems" />
        <el-alert
          class="achievement-note"
          :title="achievementAdvice.title"
          :description="achievementAdvice.description"
          :type="achievementAdvice.type"
          show-icon
          :closable="false"
        />
      </div>
    </div>
    <RunDiagnostics :progress="progress" :logs="logs" :socket-status="socketStatus" />

    <div class="run-grid">
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">任务配置</h2>
          <el-tag :type="socketTagType" effect="plain">{{ socketStatusText }}</el-tag>
        </div>
        <div class="section-body">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="任务 ID">
              <span class="mono">{{ id }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="协议">{{ protocolText(task?.api_protocol) }}</el-descriptions-item>
            <el-descriptions-item label="模型">{{ task?.model || '-' }}</el-descriptions-item>
            <el-descriptions-item label="并发">{{ task?.concurrency || '-' }}</el-descriptions-item>
            <el-descriptions-item label="时长">{{ task?.duration_sec || '-' }} 秒</el-descriptions-item>
            <el-descriptions-item label="输入 Token 目标">{{ task?.input_tokens || '-' }}</el-descriptions-item>
            <el-descriptions-item label="最大输出">{{ task?.max_output_tokens || '-' }}</el-descriptions-item>
            <el-descriptions-item label="流式">{{ task?.enable_stream ? '开启' : '关闭' }}</el-descriptions-item>
            <el-descriptions-item label="Endpoint">{{ task?.endpoint || '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>

      <LogStream :logs="logs" @clear="logs = []" />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import LogStream from '../components/LogStream.vue'
import MetricCards from '../components/MetricCards.vue'
import ProgressPanel from '../components/ProgressPanel.vue'
import RunDiagnostics from '../components/RunDiagnostics.vue'
import { createProgressSocket, getReport, getTest, stopTest } from '../api/client'

const props = defineProps({
  id: {
    type: String,
    required: true
  }
})

const router = useRouter()
const task = ref(null)
const progress = ref(null)
const status = ref('queued')
const logs = ref([])
const loading = ref(false)
const stopping = ref(false)
const socketStatus = ref('connecting')
const lastUpdatedAt = ref(null)
const finalSummary = ref(null)
const finalSummaryLoading = ref(false)
let socket
let pollTimer
let pingTimer
let finalSummaryLoaded = false
let finalizing = false

const progressWithDuration = computed(() => ({
  ...(progress.value || {}),
  duration_sec: task.value?.duration_sec,
  started_at: task.value?.started_at,
  completed_at: task.value?.completed_at,
  updated_at: lastUpdatedAt.value,
  final_summary: finalSummary.value,
  final_summary_loading: finalSummaryLoading.value
}))

const metricItems = computed(() => [
  {
    label: '当前 RPM',
    value: formatNumber(progress.value?.current_rpm),
    sub: `QPS ${formatNumber(progress.value?.current_qps)}`,
    color: '#2563eb'
  },
  {
    label: '当前 TPM',
    value: formatNumber(progress.value?.current_tpm),
    sub: '按已成功请求估算',
    color: '#f97316'
  },
  {
    label: '成功率',
    value: formatPercent(progress.value?.success_rate),
    sub: `${formatNumber(progress.value?.successful_requests)} / ${formatNumber(progress.value?.completed_requests)}`,
    color: '#16a34a'
  },
  {
    label: '最近平均延迟',
    value: formatSeconds(progress.value?.avg_latency_sec),
    sub: '最近窗口',
    color: '#334155'
  }
])

const expectedMetrics = computed(() => task.value?.expected_metrics || task.value?.summary?.config?.expected_metrics || null)
const hasExpectedMetrics = computed(() => Boolean(expectedMetrics.value?.expected_rpm || expectedMetrics.value?.expected_tpm))
const rpmAchievement = computed(() => achievementRatio(progress.value?.current_rpm, expectedMetrics.value?.expected_rpm))
const tpmAchievement = computed(() => achievementRatio(progress.value?.current_tpm, expectedMetrics.value?.expected_tpm))
const achievementStatus = computed(() => {
  const ratios = [rpmAchievement.value, tpmAchievement.value].filter((item) => item !== null)
  if (!ratios.length) return { label: '等待数据', type: 'info' }
  const minRatio = Math.min(...ratios)
  if (minRatio >= 0.9) return { label: '接近预期', type: 'success' }
  if (minRatio >= 0.6) return { label: '低于预期', type: 'warning' }
  return { label: '明显低于预期', type: 'danger' }
})
const achievementItems = computed(() => [
  {
    label: 'RPM 达成率',
    value: formatAchievement(rpmAchievement.value),
    sub: `${formatNumber(progress.value?.current_rpm)} / ${formatNumber(expectedMetrics.value?.expected_rpm)}`,
    color: achievementColor(rpmAchievement.value)
  },
  {
    label: 'TPM 达成率',
    value: formatAchievement(tpmAchievement.value),
    sub: `${formatNumber(progress.value?.current_tpm)} / ${formatNumber(expectedMetrics.value?.expected_tpm)}`,
    color: achievementColor(tpmAchievement.value)
  },
  {
    label: '预期 TPS',
    value: formatNumber(expectedMetrics.value?.expected_tps),
    sub: `当前 ${formatNumber(progress.value?.current_tpm ? Number(progress.value.current_tpm) / 60 : null)}`,
    color: '#334155'
  },
  {
    label: '预计总 Token',
    value: compactNumber(expectedMetrics.value?.expected_total_tokens),
    sub: `${formatNumber(expectedMetrics.value?.expected_requests)} 请求 / 输入 ${compactNumber(expectedMetrics.value?.expected_input_token_total)}`,
    color: '#0f766e'
  }
])
const achievementAdvice = computed(() => {
  if (!hasExpectedMetrics.value) {
    return { title: '暂无预期快照', description: '旧任务可能没有启动前预期指标。', type: 'info' }
  }
  const successRate = Number(progress.value?.success_rate ?? 1)
  const avgLatency = Number(progress.value?.avg_latency_sec || 0)
  const expectedLatency = Number(expectedMetrics.value?.expected_latency_sec || 0)
  const minRatio = Math.min(...[rpmAchievement.value, tpmAchievement.value].filter((item) => item !== null), 1)
  if (successRate < 0.99) {
    return { title: '先看错误和限流', description: '成功率低时，吞吐达成率会被失败请求拉低，建议优先排查错误分布。', type: 'warning' }
  }
  if (expectedLatency && avgLatency > expectedLatency * 1.5) {
    return { title: '实际耗时高于假设', description: '当前平均延迟明显高于启动前假设，真实 RPM/TPM 低于预期是正常现象。', type: 'warning' }
  }
  if (minRatio < 0.6) {
    return { title: '吞吐明显低于预期', description: '如果成功率正常，可能是平均耗时假设过乐观、服务端排队或模型生成速度不足。', type: 'warning' }
  }
  return { title: '运行中指标可作为参考', description: '最终判断仍以完成后的报告为准，尤其是 P95/P99 和错误分布。', type: 'info' }
})

async function loadTask() {
  loading.value = true
  try {
    const data = await getTest(props.id)
    applyTaskSnapshot(data)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function applyTaskSnapshot(data) {
  task.value = data
  status.value = data.status
  if (data.progress) progress.value = data.progress
  if (data.summary) {
    finalSummary.value = data.summary
    finalSummaryLoaded = true
  }
  markUpdated()
  if (isTerminalStatus(data.status)) {
    finalizeRun()
  }
}

function connectSocket() {
  if (isTerminalStatus(status.value)) {
    socketStatus.value = 'ended'
    return
  }
  socketStatus.value = 'connecting'
  socket = createProgressSocket(props.id)
  socket.onopen = () => {
    if (!isTerminalStatus(status.value)) socketStatus.value = 'connected'
  }
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.type === 'progress') {
      progress.value = message.data
      markUpdated()
    }
    if (message.type === 'status') {
      handleStatusUpdate(message.data.status)
    }
    if (message.type === 'log') {
      logs.value = [...logs.value.slice(-49), message.data]
      markUpdated()
    }
  }
  socket.onerror = () => {
    if (!isTerminalStatus(status.value)) {
      socketStatus.value = 'polling'
      ElMessage.warning('实时连接异常，已启用状态轮询')
    }
  }
  socket.onclose = () => {
    socketStatus.value = isTerminalStatus(status.value) ? 'ended' : 'polling'
  }
  pingTimer = window.setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send('ping')
    }
  }, 20000)
}

function startPolling() {
  pollTimer = window.setInterval(async () => {
    if (isTerminalStatus(status.value)) return
    try {
      const data = await getTest(props.id)
      applyTaskSnapshot(data)
    } catch {
      // WebSocket remains the primary live channel.
    }
  }, 3000)
}

async function confirmStop() {
  if (stopping.value || !['queued', 'running'].includes(status.value)) return
  try {
    await ElMessageBox.confirm('确认停止当前测试任务？', '停止任务', {
      type: 'warning',
      confirmButtonText: '停止',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  stopping.value = true
  handleStatusUpdate('stopping')
  try {
    await stopTest(props.id)
    ElMessage.success('已发送停止请求')
  } catch (error) {
    ElMessage.error(error.message)
    await loadTask()
  } finally {
    if (isTerminalStatus(status.value)) stopping.value = false
  }
}

function goReport() {
  router.push(`/tests/${props.id}/report`)
}

function formatNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function compactNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))
}

function formatPercent(value) {
  if (value === undefined || value === null) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function achievementRatio(actual, expected) {
  const actualValue = Number(actual)
  const expectedValue = Number(expected)
  if (!Number.isFinite(actualValue) || !Number.isFinite(expectedValue) || expectedValue <= 0) return null
  return actualValue / expectedValue
}

function formatAchievement(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function achievementColor(value) {
  if (value === null || value === undefined) return '#64748b'
  if (value >= 0.9) return '#16a34a'
  if (value >= 0.6) return '#f97316'
  return '#dc2626'
}

function formatSeconds(value) {
  if (value === undefined || value === null) return '-'
  return `${Number(value).toFixed(3)}s`
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic Messages'
  if (protocol === 'gemini') return 'Gemini API'
  return 'OpenAI-compatible'
}

function handleStatusUpdate(nextStatus) {
  status.value = nextStatus
  if (task.value) task.value.status = nextStatus
  markUpdated()
  if (isTerminalStatus(nextStatus)) {
    stopping.value = false
    finalizeRun()
  }
}

function markUpdated() {
  lastUpdatedAt.value = new Date().toISOString()
}

function isTerminalStatus(value) {
  return ['completed', 'failed', 'cancelled', 'interrupted'].includes(value)
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function finalizeRun() {
  if (finalizing) return
  finalizing = true
  socketStatus.value = 'ended'
  window.clearInterval(pollTimer)
  socket?.close()
  try {
    await loadFinalSummary()
    await refreshFinalTask()
  } finally {
    finalizing = false
  }
}

async function refreshFinalTask() {
  try {
    const data = await getTest(props.id)
    task.value = data
    status.value = data.status
    if (data.progress) progress.value = data.progress
    if (data.summary) {
      finalSummary.value = data.summary
      finalSummaryLoaded = true
    }
    markUpdated()
  } catch {
    // The terminal WebSocket event already carries the final status.
  }
}

async function loadFinalSummary() {
  if (finalSummaryLoaded || finalSummaryLoading.value) return
  finalSummaryLoading.value = true
  try {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        const report = await getReport(props.id)
        if (report?.summary) {
          finalSummary.value = report.summary
          finalSummaryLoaded = true
          markUpdated()
          return
        }
      } catch {
        // Report files can appear just after the terminal status update.
      }
      await sleep(1000)
    }
  } finally {
    finalSummaryLoading.value = false
  }
}

const socketStatusText = computed(() => {
  if (socketStatus.value === 'connected') return '实时连接中'
  if (socketStatus.value === 'polling') return '轮询更新'
  if (socketStatus.value === 'ended') return '已结束'
  return '连接中'
})

const socketTagType = computed(() => {
  if (socketStatus.value === 'connected') return 'success'
  if (socketStatus.value === 'polling') return 'warning'
  if (socketStatus.value === 'ended') return 'info'
  return 'info'
})

onMounted(async () => {
  await loadTask()
  connectSocket()
  if (!isTerminalStatus(status.value)) startPolling()
})

onBeforeUnmount(() => {
  socket?.close()
  window.clearInterval(pollTimer)
  window.clearInterval(pingTimer)
})
</script>

<style scoped>
.run-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 16px;
  margin-top: 16px;
}

.achievement-note {
  margin-top: 12px;
}

@media (max-width: 1180px) {
  .run-grid {
    grid-template-columns: 1fr;
  }
}
</style>
