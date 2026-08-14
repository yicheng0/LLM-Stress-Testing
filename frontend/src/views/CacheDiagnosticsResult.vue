<template>
  <div v-loading="loading">
    <div class="section">
      <div class="section-header">
        <div>
          <h2 class="section-title">缓存专项结果</h2>
          <p class="subtitle">{{ data?.config?.name || '缓存专项测试' }} · {{ statusText }}</p>
        </div>
        <div class="toolbar">
          <el-button @click="router.push('/tests/cache-diagnostics')">再次测试</el-button>
          <el-button @click="router.push('/history')">历史记录</el-button>
          <el-button v-if="isRunning" type="danger" plain :loading="stopping" @click="stop">停止</el-button>
          <el-button v-if="summary" type="primary" :icon="Download" @click="downloadPdf">下载 PDF</el-button>
        </div>
      </div>
      <div class="section-body">
        <el-progress :percentage="progressPercent" :status="isTerminal ? 'success' : undefined" />
        <div class="progress-copy">
          <span>当前 Case：{{ progress?.current_case || (isTerminal ? '已完成' : '等待开始') }}</span>
          <span>{{ number(progress?.completed_cases || summary?.results?.total_cases || 0) }} / {{ number(progress?.total_cases || config.case_ids?.length || 0) }}</span>
        </div>
      </div>
    </div>

    <div class="summary-grid">
      <div v-for="item in summaryCards" :key="item.label" class="summary-card" :class="item.type">
        <span>{{ item.label }}</span><strong>{{ item.value }}</strong><em>{{ item.description }}</em>
      </div>
    </div>

    <div class="section">
      <div class="section-header"><h2 class="section-title">测试配置</h2></div>
      <div class="section-body">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="协议">{{ protocolText(config.api_protocol) }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ config.model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="流式">{{ config.enable_stream ? '开启' : '关闭' }}</el-descriptions-item>
          <el-descriptions-item label="Endpoint">{{ config.endpoint || '-' }}</el-descriptions-item>
          <el-descriptions-item label="公共前缀">{{ number(config.cache_prefix_actual_tokens || 4096) }} Token</el-descriptions-item>
          <el-descriptions-item label="Case 数">{{ number(config.case_ids?.length) }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <div v-if="summary" class="section">
      <div class="section-header"><h2 class="section-title">Case 执行摘要</h2></div>
      <div class="section-body case-list">
        <article v-for="item in summary.cases || []" :key="item.case_id" class="case-result">
          <div class="case-head">
            <div><h3>{{ item.case_name }}</h3><p>{{ item.description }}</p></div>
            <el-tag :type="statusType(item.status)" effect="plain">{{ caseStatusText(item.status) }}</el-tag>
          </div>
          <el-alert
            v-if="item.failure_phase"
            :title="`失败阶段：${item.failure_phase === 'prepare' ? '准备请求' : '验证请求'}`"
            :description="item.error_message || item.error_type || '请求失败'"
            type="error" show-icon :closable="false"
          />
          <el-table :data="phaseRows(item)" border>
            <el-table-column prop="phaseLabel" label="阶段" width="100" />
            <el-table-column prop="result" label="结果" width="80" />
            <el-table-column prop="status" label="状态码" width="85" />
            <el-table-column prop="latency" label="总延迟" width="105" />
            <el-table-column prop="ttft" label="TTFT" width="105" />
            <el-table-column prop="input" label="输入 Token" width="105" />
            <el-table-column prop="output" label="输出 Token" width="105" />
            <el-table-column prop="total" label="总 Token" width="100" />
            <el-table-column prop="cached" label="缓存命中" width="105" />
            <el-table-column prop="created" label="缓存创建" width="105" />
            <el-table-column prop="inclusive" label="含缓存" width="100" />
            <el-table-column prop="hitRate" label="命中率" width="95" />
            <el-table-column prop="error" label="错误" min-width="200" show-overflow-tooltip />
          </el-table>
        </article>
      </div>
    </div>

    <div class="section">
      <div class="section-header"><h2 class="section-title">事件日志</h2></div>
      <div class="section-body log-list">
        <div v-for="event in data?.events || []" :key="event.id"><span>{{ formatTime(event.created_at) }}</span><strong>{{ event.level }}</strong><p>{{ event.message }}</p></div>
        <p v-if="!data?.events?.length" class="muted">暂无事件</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { createProgressSocket, downloadUrl, getCacheDiagnostics, stopTest } from '../api/client'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const data = ref(null)
const liveProgress = ref(null)
const liveStatus = ref(null)
const loading = ref(false)
const stopping = ref(false)
let pollTimer
let socket

const summary = computed(() => data.value?.summary || null)
const config = computed(() => data.value?.config || {})
const progress = computed(() => liveProgress.value || data.value?.progress || {})
const taskStatus = computed(() => liveStatus.value || data.value?.task_status || 'queued')
const isTerminal = computed(() => ['completed', 'failed', 'cancelled', 'interrupted'].includes(taskStatus.value))
const isRunning = computed(() => ['queued', 'running', 'stopping'].includes(taskStatus.value))
const statusText = computed(() => ({ queued: '排队中', running: '运行中', stopping: '停止中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' }[taskStatus.value] || taskStatus.value))
const progressPercent = computed(() => {
  const total = Number(progress.value.total_cases || config.value.case_ids?.length || 0)
  const completed = Number(progress.value.completed_cases || summary.value?.results?.total_cases || 0)
  return total ? Math.min(100, Math.round(completed / total * 100)) : 0
})
const counts = computed(() => summary.value?.results || progress.value || {})
const summaryCards = computed(() => [
  { label: 'Case 总数', value: number(counts.value.total_cases || config.value.case_ids?.length), description: '固定场景串行执行', type: '' },
  { label: '缓存命中', value: number(counts.value.cache_hit_cases), description: '命中 Token > 0', type: 'success' },
  { label: '未命中缓存', value: number(counts.value.cache_miss_cases), description: '明确返回零命中', type: 'warning' },
  { label: '无法判定', value: number(counts.value.unverifiable_cases), description: '上游无缓存字段', type: 'info' },
  { label: '执行失败', value: number(counts.value.failed_cases), description: '准备或验证请求失败', type: 'danger' }
])

async function load() {
  loading.value = !data.value
  try { data.value = await getCacheDiagnostics(props.id) } catch (error) { ElMessage.error(error.message) } finally { loading.value = false }
  if (isTerminal.value) cleanupLive()
}

function connectSocket() {
  try {
    socket = createProgressSocket(props.id)
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'progress') liveProgress.value = message.data
      if (message.type === 'status') { liveStatus.value = message.data?.status || message.status; if (isTerminal.value) load() }
    }
  } catch { /* polling remains active */ }
}

async function stop() {
  stopping.value = true
  try { await stopTest(props.id); ElMessage.success('已请求停止') } catch (error) { ElMessage.error(error.message) } finally { stopping.value = false }
}

function downloadPdf() { window.open(downloadUrl(props.id, 'pdf'), '_blank', 'noopener,noreferrer') }
function cleanupLive() { if (pollTimer) clearInterval(pollTimer); if (socket) socket.close() }
function number(value) { return value === undefined || value === null ? '0' : Number(value).toLocaleString() }
function seconds(value) { return value === undefined || value === null ? '不可用' : `${Number(value).toFixed(4)}s` }
function percent(value) { return value === undefined || value === null ? '不可用' : `${(Number(value) * 100).toFixed(2)}%` }
function protocolText(value) { return value === 'anthropic' ? 'Anthropic' : value === 'gemini' ? 'Gemini' : 'OpenAI-compatible' }
function caseStatusText(value) { return ({ cache_hit: '缓存命中', cache_miss: '未命中缓存', unverifiable: '无法判定', failed: '执行失败' }[value] || value) }
function statusType(value) { return ({ cache_hit: 'success', cache_miss: 'warning', unverifiable: 'info', failed: 'danger' }[value] || 'info') }
function phaseRows(item) { return [['prepare', '准备请求'], ['validate', '验证请求']].map(([key, label]) => row(item[key], label)) }
function row(item, phaseLabel) {
  if (!item) return { phaseLabel, result: '未执行', status: '不可用', latency: '不可用', ttft: '不可用', input: '不可用', output: '不可用', total: '不可用', cached: '不可用', created: '不可用', inclusive: '不可用', hitRate: '不可用', error: '-' }
  const cache = item.cache || {}
  return { phaseLabel, result: item.ok ? '成功' : '失败', status: item.status || 0, latency: seconds(item.latency_sec), ttft: seconds(item.ttft_sec), input: number(item.input_tokens), output: number(item.output_tokens), total: number(item.total_tokens), cached: cache.observed ? number(cache.cached_input_tokens) : '不可用', created: cache.observed ? number(cache.cache_creation_input_tokens) : '不可用', inclusive: number(cache.cache_inclusive_total_tokens), hitRate: cache.observed ? percent(cache.cache_hit_rate) : '不可用', error: item.error_message || item.error_type || '-' }
}
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value)) : '-' }

onMounted(() => { load(); connectSocket(); pollTimer = setInterval(load, 3000) })
onBeforeUnmount(cleanupLive)
</script>

<style scoped>
.subtitle { margin: 5px 0 0; color: #6b7280; font-size: 13px; }
.progress-copy { display: flex; justify-content: space-between; margin-top: 10px; color: #6b7280; font-size: 13px; }
.summary-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-card { padding: 16px; border: 1px solid #e5e7eb; border-left: 4px solid #6b7280; border-radius: 10px; background: #fff; }
.summary-card.success { border-left-color: #16a34a; }.summary-card.warning { border-left-color: #f59e0b; }.summary-card.info { border-left-color: #2563eb; }.summary-card.danger { border-left-color: #dc2626; }
.summary-card span, .summary-card em { display: block; color: #6b7280; font-size: 12px; font-style: normal; }.summary-card strong { display: block; margin: 7px 0; font-size: 24px; }
.case-list { display: grid; gap: 18px; }.case-result { display: grid; gap: 12px; }.case-head { display: flex; justify-content: space-between; gap: 12px; }.case-head h3 { margin: 0; }.case-head p { margin: 5px 0 0; color: #6b7280; }
.log-list { display: grid; gap: 8px; }.log-list div { display: grid; grid-template-columns: 90px 70px 1fr; gap: 8px; font-size: 13px; }.log-list p { margin: 0; }
@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .summary-grid { grid-template-columns: 1fr; }.case-head { flex-direction: column; }.log-list div { grid-template-columns: 1fr; } }
</style>
