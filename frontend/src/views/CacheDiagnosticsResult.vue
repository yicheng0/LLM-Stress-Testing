<template>
  <div v-loading="loading" class="cache-diagnostics-result">
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
          <span>当前请求：{{ currentRequestText }}</span>
          <span v-if="requestProgress">已执行 / 计划：{{ displayNumber(requestProgress.executed) }} / {{ displayNumber(requestProgress.planned) }}</span>
          <span v-else>已完成 Case：{{ displayNumber(caseProgress.completed) }} / {{ displayNumber(caseProgress.total) }}</span>
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
          <el-descriptions-item label="公共前缀目标">{{ tokenText(summaryConfig.cache_prefix_target_tokens ?? config.input_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="公共前缀实际">{{ tokenText(summaryConfig.cache_prefix_actual_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="每个 Case 请求次数">{{ requestCountText }}</el-descriptions-item>
          <el-descriptions-item label="计划请求总数">{{ displayNumber(plannedRequests) }}</el-descriptions-item>
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
            :title="`失败阶段：${item.failure_phase === 'prepare' ? '缓存建立' : '缓存验证'}`"
            :description="item.error_message || item.error_type || '请求失败'"
            type="error" show-icon :closable="false"
          />
          <el-descriptions :column="4" border class="case-stats">
            <el-descriptions-item label="计划请求">{{ displayNumber(caseStats(item).planned) }}</el-descriptions-item>
            <el-descriptions-item label="实际请求">{{ displayNumber(caseStats(item).executed) }}</el-descriptions-item>
            <el-descriptions-item label="验证样本">{{ displayNumber(caseStats(item).validation) }}</el-descriptions-item>
            <el-descriptions-item label="可判定验证">{{ displayNumber(caseStats(item).decidable) }}</el-descriptions-item>
            <el-descriptions-item label="缓存命中">{{ displayNumber(caseStats(item).hits) }}</el-descriptions-item>
            <el-descriptions-item label="未命中缓存">{{ displayNumber(caseStats(item).misses) }}</el-descriptions-item>
            <el-descriptions-item label="无法判定">{{ displayNumber(caseStats(item).unverifiable) }}</el-descriptions-item>
            <el-descriptions-item label="执行失败">{{ displayNumber(caseStats(item).failed) }}</el-descriptions-item>
            <el-descriptions-item label="Case 命中率">{{ percent(caseStats(item).hitRate) }}</el-descriptions-item>
          </el-descriptions>
          <el-table :data="requestRows(item)" border>
            <el-table-column prop="requestIndex" label="序号" width="70" />
            <el-table-column prop="phaseLabel" label="阶段" width="130" />
            <el-table-column prop="classification" label="单请求判定" width="115" />
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
const summaryConfig = computed(() => summary.value?.config || {})
const progress = computed(() => liveProgress.value || data.value?.progress || {})
const taskStatus = computed(() => liveStatus.value || data.value?.task_status || 'queued')
const isTerminal = computed(() => ['completed', 'failed', 'cancelled', 'interrupted'].includes(taskStatus.value))
const isRunning = computed(() => ['queued', 'running', 'stopping'].includes(taskStatus.value))
const statusText = computed(() => ({ queued: '排队中', running: '运行中', stopping: '停止中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' }[taskStatus.value] || taskStatus.value))
const resultCounts = computed(() => summary.value?.results || {})
const plannedRequests = computed(() => firstDefined(resultCounts.value.planned_requests, progress.value.planned_requests, null))
const requestProgress = computed(() => {
  const executed = firstDefined(progress.value.executed_requests, resultCounts.value.executed_requests, null)
  const planned = firstDefined(progress.value.planned_requests, resultCounts.value.planned_requests, null)
  return hasValue(executed) && hasValue(planned) ? { executed, planned } : null
})
const caseProgress = computed(() => ({
  completed: firstDefined(progress.value.completed_cases, resultCounts.value.total_cases, null),
  total: firstDefined(progress.value.total_cases, config.value.case_ids?.length, null)
}))
const currentRequestText = computed(() => {
  const index = progress.value.current_request_index
  const total = firstDefined(progress.value.requests_per_case, config.value.requests_per_case, summaryConfig.value.requests_per_case, null)
  return hasValue(index) ? `${displayNumber(index)} / ${displayNumber(total)}` : '不可用'
})
const requestCountText = computed(() => {
  const value = firstDefined(config.value.requests_per_case, summaryConfig.value.requests_per_case, null)
  return hasValue(value) ? `${displayNumber(value)} 次` : '不可用'
})
const progressPercent = computed(() => {
  const requestTotal = requestProgress.value?.planned
  const requestCompleted = requestProgress.value?.executed
  if (hasValue(requestTotal) && hasValue(requestCompleted)) {
    return Number(requestTotal) > 0 ? Math.min(100, Math.round(Number(requestCompleted) / Number(requestTotal) * 100)) : 0
  }
  const total = Number(caseProgress.value.total || 0)
  const completed = Number(caseProgress.value.completed || 0)
  return total ? Math.min(100, Math.round(completed / total * 100)) : 0
})
const counts = computed(() => ({ ...legacyCounts(), ...progress.value, ...resultCounts.value }))
const summaryCards = computed(() => [
  { label: '计划请求', value: displayNumber(firstDefined(counts.value.planned_requests, plannedRequests.value, null)), description: '不含失败重试', type: '' },
  { label: '实际请求', value: displayNumber(counts.value.executed_requests), description: '已完成业务请求', type: '' },
  { label: '可判定验证', value: displayNumber(counts.value.decidable_requests), description: '命中与明确未命中之和', type: '' },
  { label: '总体命中率', value: percent(counts.value.cache_hit_rate), description: '按全部可判定验证请求合并', type: 'success' },
  { label: '无法判定', value: displayNumber(counts.value.unverifiable_requests), description: '上游无缓存字段', type: 'info' },
  { label: '执行失败', value: displayNumber(counts.value.failed_requests), description: '验证请求执行失败', type: 'danger' }
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
function hasValue(value) { return value !== undefined && value !== null }
function firstDefined(...values) { return values.find(hasValue) }
function number(value) { return value === undefined || value === null ? '0' : Number(value).toLocaleString() }
function displayNumber(value) { return hasValue(value) ? number(value) : '不可用' }
function tokenText(value) { return hasValue(value) ? `${displayNumber(value)} Token` : '不可用' }
function seconds(value) { return value === undefined || value === null ? '不可用' : `${Number(value).toFixed(4)}s` }
function percent(value) { return value === undefined || value === null ? '不可用' : `${(Number(value) * 100).toFixed(2)}%` }
function protocolText(value) { return value === 'anthropic' ? 'Anthropic' : value === 'gemini' ? 'Gemini' : 'OpenAI-compatible' }
function caseStatusText(value) { return ({ cache_hit: '缓存命中', cache_miss: '未命中缓存', unverifiable: '无法判定', failed: '执行失败' }[value] || value) }
function statusType(value) { return ({ cache_hit: 'success', cache_miss: 'warning', unverifiable: 'info', failed: 'danger' }[value] || 'info') }
function legacyRequests(item) {
  return ['prepare', 'validate'].flatMap((phase, index) => item[phase] ? [{ ...item[phase], phase, request_index: index + 1 }] : [])
}
function requests(item) { return Array.isArray(item.requests) ? item.requests : legacyRequests(item) }
function requestRows(item) { return requests(item).map((request, index) => row(request, index + 1)) }
function classification(request) {
  if (request.phase === 'prepare') return '不参与判定'
  const value = request.classification
  if (hasValue(value)) return caseStatusText(value)
  if (!request.ok) return '执行失败'
  const cache = request.cache || {}
  if (!cache.observed) return '无法判定'
  return Number(cache.cached_input_tokens) > 0 ? '缓存命中' : '未命中缓存'
}
function row(item, fallbackIndex) {
  const cache = item.cache || {}
  const index = firstDefined(item.request_index, fallbackIndex)
  const isPrepare = item.phase === 'prepare'
  return {
    requestIndex: displayNumber(index),
    phaseLabel: item.phase_label || (isPrepare ? '缓存建立' : `缓存验证 #${displayNumber(index)}`),
    classification: classification(item),
    result: item.ok ? '成功' : '失败',
    status: displayNumber(item.status),
    latency: seconds(item.latency_sec),
    ttft: seconds(item.ttft_sec),
    input: displayNumber(item.input_tokens),
    output: displayNumber(item.output_tokens),
    total: displayNumber(item.total_tokens),
    cached: cache.observed ? displayNumber(cache.cached_input_tokens) : '不可用',
    created: cache.observed ? displayNumber(cache.cache_creation_input_tokens) : '不可用',
    inclusive: cache.observed ? displayNumber(cache.cache_inclusive_total_tokens) : '不可用',
    hitRate: cache.observed ? percent(cache.cache_hit_rate) : '不可用',
    error: item.error_message || item.error_type || '-'
  }
}
function caseStats(item) {
  const caseRequests = requests(item)
  const validations = caseRequests.filter((request) => request.phase === 'validate')
  const classifications = validations.map(classification)
  const hits = classifications.filter((value) => value === '缓存命中').length
  const misses = classifications.filter((value) => value === '未命中缓存').length
  const unverifiable = classifications.filter((value) => value === '无法判定').length
  const failed = classifications.filter((value) => value === '执行失败').length
  const decidable = hits + misses
  return {
    planned: firstDefined(item.planned_requests, null),
    executed: firstDefined(item.executed_requests, caseRequests.length),
    validation: firstDefined(item.validation_requests, validations.length),
    hits: firstDefined(item.cache_hit_requests, hits),
    misses: firstDefined(item.cache_miss_requests, misses),
    unverifiable: firstDefined(item.unverifiable_requests, unverifiable),
    failed: firstDefined(item.failed_requests, failed),
    decidable: firstDefined(item.decidable_requests, decidable),
    hitRate: firstDefined(item.cache_hit_rate, decidable ? hits / decidable : null)
  }
}
function legacyCounts() {
  const stats = (summary.value?.cases || []).map(caseStats)
  const sum = (key) => stats.reduce((total, item) => total + Number(item[key] || 0), 0)
  const hits = sum('hits')
  const misses = sum('misses')
  const decidable = hits + misses
  return {
    executed_requests: sum('executed'),
    validation_requests: sum('validation'),
    cache_hit_requests: hits,
    cache_miss_requests: misses,
    unverifiable_requests: sum('unverifiable'),
    failed_requests: sum('failed'),
    decidable_requests: decidable,
    cache_hit_rate: decidable ? hits / decidable : null
  }
}
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value)) : '-' }

onMounted(() => { load(); connectSocket(); pollTimer = setInterval(load, 3000) })
onBeforeUnmount(cleanupLive)
</script>

<style scoped>
.subtitle { margin: 5px 0 0; color: #6b7280; font-size: 13px; }
.progress-copy { display: flex; justify-content: space-between; margin-top: 10px; color: #6b7280; font-size: 13px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-card { padding: 16px; border: 1px solid #e5e7eb; border-left: 4px solid #6b7280; border-radius: 10px; background: #fff; }
.summary-card.success { border-left-color: #16a34a; }.summary-card.warning { border-left-color: #f59e0b; }.summary-card.info { border-left-color: #2563eb; }.summary-card.danger { border-left-color: #dc2626; }
.summary-card span, .summary-card em { display: block; color: #6b7280; font-size: 12px; font-style: normal; }.summary-card strong { display: block; margin: 7px 0; font-size: 24px; }
.case-list { display: grid; gap: 18px; }.case-result { display: grid; gap: 12px; }.case-head { display: flex; justify-content: space-between; gap: 12px; }.case-head h3 { margin: 0; }.case-head p { margin: 5px 0 0; color: #6b7280; }.case-stats { margin-bottom: 4px; }
.log-list { display: grid; gap: 8px; }.log-list div { display: grid; grid-template-columns: 90px 70px 1fr; gap: 8px; font-size: 13px; }.log-list p { margin: 0; }
.cache-diagnostics-result :deep(.el-table) { overflow-x: auto; }
@media (max-width: 1100px) { .progress-copy { flex-wrap: wrap; gap: 8px 16px; } }
@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .summary-grid { grid-template-columns: 1fr; }.case-head { flex-direction: column; }.log-list div { grid-template-columns: 1fr; } }
</style>
