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
            <el-descriptions-item label="输入 Token">{{ task?.input_tokens || '-' }}</el-descriptions-item>
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

function formatPercent(value) {
  if (value === undefined || value === null) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
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

@media (max-width: 1180px) {
  .run-grid {
    grid-template-columns: 1fr;
  }
}
</style>
