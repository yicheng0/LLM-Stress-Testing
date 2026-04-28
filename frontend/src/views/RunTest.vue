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

    <div class="run-grid">
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">任务配置</h2>
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
import { createProgressSocket, getTest, stopTest } from '../api/client'

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
let socket
let pollTimer
let pingTimer

const progressWithDuration = computed(() => ({
  ...(progress.value || {}),
  duration_sec: task.value?.duration_sec
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
    task.value = data
    status.value = data.status
    if (data.progress) progress.value = data.progress
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function connectSocket() {
  socket = createProgressSocket(props.id)
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.type === 'progress') {
      progress.value = message.data
    }
    if (message.type === 'status') {
      status.value = message.data.status
      if (task.value) task.value.status = message.data.status
      if (['completed', 'failed', 'cancelled', 'interrupted'].includes(message.data.status)) {
        loadTask()
      }
    }
    if (message.type === 'log') {
      logs.value = [...logs.value.slice(-49), message.data]
    }
  }
  socket.onerror = () => {
    ElMessage.warning('实时连接异常，已启用状态轮询')
  }
  pingTimer = window.setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send('ping')
    }
  }, 20000)
}

function startPolling() {
  pollTimer = window.setInterval(async () => {
    if (['completed', 'failed', 'cancelled', 'interrupted'].includes(task.value?.status)) return
    try {
      const data = await getTest(props.id)
      task.value = data
      status.value = data.status
      if (data.progress) progress.value = data.progress
    } catch {
      // WebSocket remains the primary live channel.
    }
  }, 3000)
}

async function confirmStop() {
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
  try {
    await stopTest(props.id)
    ElMessage.success('已发送停止请求')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    stopping.value = false
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

onMounted(async () => {
  await loadTask()
  connectSocket()
  startPolling()
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
