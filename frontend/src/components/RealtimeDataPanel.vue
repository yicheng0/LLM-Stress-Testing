<template>
  <div class="section realtime-panel">
    <div class="section-header">
      <div>
        <h2 class="section-title">实时测试数据面板</h2>
        <div class="panel-subtitle">自动汇总最近任务和运行中任务，每 3 秒刷新一次</div>
      </div>
      <div class="toolbar">
        <el-tag :type="activeTasks.length ? 'success' : 'info'" effect="plain">
          {{ activeTasks.length ? '实时运行中' : '暂无运行任务' }}
        </el-tag>
        <el-tag :type="freshness.type" effect="plain">{{ freshness.label }}</el-tag>
        <el-segmented v-model="windowSize" :options="windowOptions" />
        <el-button :icon="paused ? VideoPlay : VideoPause" @click="paused = !paused">
          {{ paused ? '继续刷新' : '暂停刷新' }}
        </el-button>
        <el-button :icon="FullScreen" @click="toggleFullscreen">大屏模式</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div class="section-body">
      <el-alert
        v-if="refreshError"
        class="refresh-alert"
        type="warning"
        :closable="false"
        :title="`刷新失败：${refreshError}，已保留上次数据`"
      />

      <div class="diagnosis-summary" :class="diagnosisMeta.className">
        <div class="diagnosis-status">
          <el-icon><component :is="diagnosisMeta.icon" /></el-icon>
        </div>
        <div class="diagnosis-main">
          <div class="diagnosis-kicker">{{ diagnosisMeta.label }}</div>
          <strong>{{ diagnostics.summary }}</strong>
          <div class="diagnosis-ratios">
            <span>RPM {{ formatAchievement(rpmAchievement) }}</span>
            <span>TPM {{ formatAchievement(tpmAchievement) }}</span>
            <span>成功率 {{ percent(aggregate.successRate) }}</span>
            <span>P95 {{ seconds(aggregate.p95) }}</span>
          </div>
          <div v-if="diagnostics.reasons.length" class="diagnosis-reasons">
            <span v-for="reason in diagnostics.reasons" :key="reason">{{ reason }}</span>
          </div>
        </div>
        <div class="diagnosis-actions">
          <el-button
            v-for="action in diagnostics.actions"
            :key="`${action.type}-${action.label}`"
            size="small"
            :type="action.type === 'new_test' ? 'primary' : 'default'"
            @click="handleDiagnosticAction(action.type)"
          >
            {{ action.label }}
          </el-button>
        </div>
      </div>

      <div class="live-card-grid">
        <div v-for="card in metricCards" :key="card.label" class="live-card" :class="card.tone">
          <div class="live-card-icon">
            <el-icon><component :is="card.icon" /></el-icon>
          </div>
          <div>
            <div class="live-card-label">{{ card.label }}</div>
            <div class="live-card-value">{{ card.value }}</div>
            <div class="live-card-sub">{{ card.sub }}</div>
          </div>
        </div>
      </div>

      <div class="diagnostic-grid">
        <div v-for="item in diagnosticItems" :key="item.label" class="diagnostic-card" :class="item.type">
          <div class="diagnostic-label">{{ item.label }}</div>
          <strong>{{ item.value }}</strong>
          <span>{{ item.hint }}</span>
        </div>
      </div>

      <div class="live-layout">
        <div class="chart-tile large">
          <div class="tile-header">
            <h3>吞吐实时趋势</h3>
            <span>RPM / TPM / 目标线</span>
          </div>
          <div ref="trendEl" class="live-chart" />
        </div>

        <div class="chart-tile">
          <div class="tile-header">
            <h3>任务状态分布</h3>
            <span>{{ total }} 条记录</span>
          </div>
          <div ref="statusEl" class="live-chart" />
        </div>

        <div class="chart-tile">
          <div class="tile-header">
            <h3>协议任务分布</h3>
            <span>OpenAI / Anthropic / Gemini</span>
          </div>
          <div ref="protocolEl" class="live-chart" />
        </div>

        <div ref="activityTileEl" class="activity-tile">
          <div class="tile-header">
            <h3>活跃 / 最近任务</h3>
            <span>异常和运行中优先</span>
          </div>
          <div v-if="!items.length && !loading" class="empty-state">
            <strong>暂无测试数据</strong>
            <span>启动一次压测后，这里会展示实时吞吐、成功率和协议分布。</span>
            <el-button type="primary" @click="router.push('/tests/new')">新建测试</el-button>
          </div>
          <div v-else class="activity-list">
            <button
              v-for="item in recentItems"
              :key="item.id"
              type="button"
              class="activity-row"
              @click="goTask(item)"
            >
              <span :class="['status-dot', `status-${item.status}`]" />
              <span class="activity-main">
                <strong>{{ item.name }}</strong>
                <span>{{ statusText(item.status) }} · {{ protocolText(item.api_protocol) }} · {{ item.model }}</span>
                <span v-if="item.error_message" class="activity-error">{{ errorText(item.error_message) }}</span>
                <span v-if="item.issue_tags?.length" class="issue-tags">
                  <el-tag
                    v-for="tag in item.issue_tags"
                    :key="tag"
                    size="small"
                    :type="issueTagType(tag)"
                    effect="plain"
                  >
                    {{ tag }}
                  </el-tag>
                </span>
              </span>
              <span class="activity-runtime">{{ runtimeText(item) }}</span>
              <span class="activity-metrics">
                <span><strong>{{ number(item.rpm) }}</strong><em>RPM</em></span>
                <span><strong>{{ number(item.tpm) }}</strong><em>TPM</em></span>
                <span><strong>{{ percent(item.success_rate) }}</strong><em>成功率</em></span>
                <span><strong>{{ seconds(item.latency_p95) }}</strong><em>P95</em></span>
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import {
  CircleCheck,
  DataAnalysis,
  FullScreen,
  Histogram,
  Refresh,
  TrendCharts,
  VideoPause,
  VideoPlay,
  Warning
} from '@element-plus/icons-vue'
import { getRealtimeDashboard } from '../api/client'

const router = useRouter()
const loading = ref(false)
const items = ref([])
const total = ref(0)
const samples = ref([])
const dashboard = ref(null)
const paused = ref(false)
const lastRefreshAt = ref(null)
const refreshError = ref('')
const windowSize = ref(30)
const windowOptions = [
  { label: '1 分钟', value: 20 },
  { label: '3 分钟', value: 60 },
  { label: '5 分钟', value: 100 }
]
const trendEl = ref()
const statusEl = ref()
const protocolEl = ref()
const activityTileEl = ref()
let timer
let trendChart
let statusChart
let protocolChart

const activeStatuses = ['queued', 'running', 'stopping']
const activeTasks = computed(() => items.value.filter((item) => activeStatuses.includes(item.status)))
const recentItems = computed(() => [...items.value].sort(taskPriority).slice(0, 8))
const latestReportTask = computed(() => recentItems.value.find((item) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(item.status)))
const aggregate = computed(() => {
  const metrics = dashboard.value?.metrics || {}
  return {
    rpm: numeric(metrics.rpm),
    tpm: numeric(metrics.tpm),
    expectedRpm: numeric(metrics.expected_rpm, null),
    expectedTpm: numeric(metrics.expected_tpm, null),
    expectedTps: numeric(metrics.expected_tps, null),
    expectedLatency: numeric(metrics.expected_latency_sec, null),
    successRate: numeric(metrics.success_rate, null),
    p95: numeric(metrics.latency_p95, null)
  }
})
const topError = computed(() => Object.entries(dashboard.value?.error_counts || {})[0] || null)
const failedCount = computed(() => (dashboard.value?.status_counts?.failed || 0) + (dashboard.value?.status_counts?.interrupted || 0))
const freshness = computed(() => {
  if (refreshError.value) return { label: '刷新异常', type: 'warning' }
  if (!lastRefreshAt.value) return { label: '等待数据', type: 'info' }
  const ageSec = Math.max(0, Math.round((Date.now() - Date.parse(lastRefreshAt.value)) / 1000))
  if (ageSec > 10) return { label: `数据 ${ageSec}s 前`, type: 'warning' }
  return { label: `已更新 ${ageSec}s`, type: 'success' }
})
const rpmAchievement = computed(() => achievementRatio(aggregate.value.rpm, aggregate.value.expectedRpm))
const tpmAchievement = computed(() => achievementRatio(aggregate.value.tpm, aggregate.value.expectedTpm))
const minAchievement = computed(() => {
  const ratios = [rpmAchievement.value, tpmAchievement.value].filter((item) => item !== null)
  return ratios.length ? Math.min(...ratios) : null
})
const healthTone = computed(() => {
  if (refreshError.value || failedCount.value > 0 || numeric(aggregate.value.successRate, 1) < 0.95) return 'danger'
  if (minAchievement.value !== null && minAchievement.value < 0.6) return 'warning'
  return 'ok'
})
const diagnostics = computed(() => {
  const fallback = {
    overall_status: total.value ? 'healthy' : 'idle',
    summary: total.value ? '实时数据暂无明显异常。' : '暂无测试数据，启动一次压测后可查看实时诊断。',
    reasons: [],
    actions: total.value ? [{ type: 'open_report', label: '查看最新报告' }] : [{ type: 'new_test', label: '新建测试' }]
  }
  const value = dashboard.value?.diagnostics || fallback
  return {
    overall_status: value.overall_status || fallback.overall_status,
    summary: value.summary || fallback.summary,
    reasons: Array.isArray(value.reasons) ? value.reasons : [],
    actions: Array.isArray(value.actions) ? value.actions : fallback.actions
  }
})
const diagnosisMeta = computed(() => {
  const meta = {
    healthy: { label: '诊断正常', className: 'healthy', icon: CircleCheck },
    warning: { label: '需要关注', className: 'warning', icon: Warning },
    critical: { label: '需要处理', className: 'critical', icon: Warning },
    idle: { label: '等待数据', className: 'idle', icon: DataAnalysis }
  }
  return meta[diagnostics.value.overall_status] || meta.idle
})

const metricCards = computed(() => [
  {
    label: '活跃任务',
    value: number(dashboard.value?.active_tasks ?? activeTasks.value.length),
    sub: `历史 ${number(total.value)} 条任务`,
    icon: DataAnalysis,
    tone: 'blue'
  },
  {
    label: '实时 RPM',
    value: number(aggregate.value.rpm),
    sub: targetText(aggregate.value.rpm, aggregate.value.expectedRpm),
    icon: TrendCharts,
    tone: 'green'
  },
  {
    label: '实时 TPM',
    value: number(aggregate.value.tpm),
    sub: targetText(aggregate.value.tpm, aggregate.value.expectedTpm),
    icon: Histogram,
    tone: 'purple'
  },
  {
    label: '成功率 / P95',
    value: percent(aggregate.value.successRate),
    sub: `P95 ${seconds(aggregate.value.p95)} / 预期 ${seconds(aggregate.value.expectedLatency)}`,
    icon: DataAnalysis,
    tone: healthTone.value === 'danger' ? 'red' : 'orange'
  }
])
const diagnosticItems = computed(() => [
  {
    label: '数据新鲜度',
    value: freshness.value.label,
    hint: lastRefreshAt.value ? `最后刷新 ${time(lastRefreshAt.value)}` : '等待首次刷新',
    type: refreshError.value ? 'warning' : 'ok'
  },
  {
    label: '目标达成',
    value: minAchievement.value === null ? '暂无目标' : formatAchievement(minAchievement.value),
    hint: `RPM ${formatAchievement(rpmAchievement.value)} · TPM ${formatAchievement(tpmAchievement.value)}`,
    type: minAchievement.value === null || minAchievement.value >= 0.9 ? 'ok' : minAchievement.value >= 0.6 ? 'warning' : 'danger'
  },
  {
    label: '异常分布',
    value: topError.value ? topError.value[0] : '暂无主要异常',
    hint: topError.value ? `${topError.value[1]} 次 · 失败/中断 ${failedCount.value} 个任务` : '最近任务未记录错误',
    type: topError.value ? 'danger' : 'ok'
  },
  {
    label: '质量状态',
    value: aggregate.value.successRate === null ? '等待样本' : percent(aggregate.value.successRate),
    hint: `P95 ${seconds(aggregate.value.p95)} · 活跃 ${activeTasks.value.length} 个`,
    type: numeric(aggregate.value.successRate, 1) >= 0.95 ? 'ok' : 'warning'
  }
])

async function loadData() {
  if (paused.value) return
  loading.value = true
  try {
    const data = await getRealtimeDashboard()
    dashboard.value = data
    items.value = data.recent_tasks || []
    total.value = data.total || 0
    lastRefreshAt.value = new Date().toISOString()
    refreshError.value = ''
    pushSample()
  } catch (error) {
    refreshError.value = error?.message || '未知错误'
  } finally {
    loading.value = false
  }
}

function pushSample() {
  const now = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date())
  samples.value = [
    ...samples.value.slice(-(Number(windowSize.value) - 1)),
    {
      time: now,
      rpm: Math.round(aggregate.value.rpm * 100) / 100,
      tpm: Math.round(aggregate.value.tpm),
      expectedRpm: aggregate.value.expectedRpm,
      expectedTpm: aggregate.value.expectedTpm,
      successRate: aggregate.value.successRate === null ? 0 : Math.round(aggregate.value.successRate * 10000) / 100
    }
  ]
}

function renderCharts() {
  if (!trendEl.value || !statusEl.value || !protocolEl.value) return
  trendChart ||= echarts.init(trendEl.value)
  statusChart ||= echarts.init(statusEl.value)
  protocolChart ||= echarts.init(protocolEl.value)
  trendChart.setOption(trendOption(), true)
  statusChart.setOption(statusOption(), true)
  protocolChart.setOption(protocolOption(), true)
}

function trendOption() {
  return {
    color: ['#2563eb', '#8b5cf6', '#94a3b8', '#f59e0b'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 50, right: 50, top: 42, bottom: 34 },
    xAxis: { type: 'category', data: samples.value.map((item) => item.time), boundaryGap: false },
    yAxis: [
      { type: 'value', name: 'RPM' },
      { type: 'value', name: 'TPM' }
    ],
    series: [
      { name: 'RPM', type: 'line', smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 }, data: samples.value.map((item) => item.rpm) },
      { name: 'TPM', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, areaStyle: { opacity: 0.1 }, data: samples.value.map((item) => item.tpm) },
      { name: '目标 RPM', type: 'line', showSymbol: false, lineStyle: { type: 'dashed' }, data: samples.value.map((item) => item.expectedRpm) },
      { name: '目标 TPM', type: 'line', showSymbol: false, yAxisIndex: 1, lineStyle: { type: 'dashed' }, data: samples.value.map((item) => item.expectedTpm) }
    ]
  }
}

function statusOption() {
  const colors = {
    queued: '#64748b',
    running: '#2563eb',
    stopping: '#f97316',
    completed: '#16a34a',
    failed: '#dc2626',
    cancelled: '#f59e0b',
    interrupted: '#9333ea'
  }
  const names = {
    queued: '排队',
    running: '运行',
    stopping: '停止中',
    completed: '完成',
    failed: '失败',
    cancelled: '取消',
    interrupted: '中断'
  }
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['48%', '72%'],
      center: ['50%', '43%'],
      data: Object.entries(dashboard.value?.status_counts || countBy(items.value, 'status')).map(([key, value]) => ({
        name: names[key] || key,
        value,
        itemStyle: { color: colors[key] || '#64748b' }
      }))
    }]
  }
}

function protocolOption() {
  const counts = dashboard.value?.protocol_counts || countBy(items.value, 'api_protocol')
  const labels = ['openai', 'anthropic', 'gemini']
  return {
    color: ['#2563eb', '#f97316', '#16a34a'],
    tooltip: { trigger: 'axis' },
    grid: { left: 44, right: 18, top: 24, bottom: 36 },
    xAxis: { type: 'category', data: labels.map(protocolText) },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      barWidth: 34,
      data: labels.map((label) => counts[label] || 0),
      itemStyle: { borderRadius: [6, 6, 0, 0] }
    }]
  }
}

function countBy(list, key) {
  return list.reduce((acc, item) => {
    const value = item[key] || 'openai'
    acc[value] = (acc[value] || 0) + 1
    return acc
  }, {})
}

function resizeCharts() {
  trendChart?.resize()
  statusChart?.resize()
  protocolChart?.resize()
}

function taskPriority(a, b) {
  const score = (item) => {
    if (item.status === 'failed' || item.status === 'interrupted') return 0
    if (activeStatuses.includes(item.status)) return 1
    return 2
  }
  return score(a) - score(b) || Date.parse(b.created_at || '') - Date.parse(a.created_at || '')
}

function goTask(item) {
  if (['completed', 'failed', 'cancelled', 'interrupted'].includes(item.status)) {
    router.push(`/tests/${item.id}/report`)
    return
  }
  router.push(`/tests/${item.id}/run`)
}

function handleDiagnosticAction(type) {
  if (type === 'new_test') {
    router.push('/tests/new')
    return
  }
  if (type === 'open_report' && latestReportTask.value) {
    router.push(`/tests/${latestReportTask.value.id}/report`)
    return
  }
  activityTileEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function toggleFullscreen() {
  const element = document.querySelector('.realtime-panel')
  if (!document.fullscreenElement && element?.requestFullscreen) {
    await element.requestFullscreen()
    return
  }
  if (document.fullscreenElement && document.exitFullscreen) {
    await document.exitFullscreen()
  }
}

function statusText(status) {
  const names = {
    queued: '排队',
    running: '运行',
    stopping: '停止中',
    completed: '完成',
    failed: '失败',
    cancelled: '取消',
    interrupted: '中断'
  }
  return names[status] || status || '-'
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic'
  if (protocol === 'gemini') return 'Gemini'
  return 'OpenAI'
}

function achievementRatio(current, target) {
  const currentValue = Number(current)
  const targetValue = Number(target)
  if (!targetValue || Number.isNaN(currentValue) || Number.isNaN(targetValue)) return null
  return currentValue / targetValue
}

function formatAchievement(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${Math.round(Number(value) * 100)}%`
}

function targetText(current, target) {
  if (target === undefined || target === null || Number.isNaN(Number(target))) return '暂无目标快照'
  return `${number(current)} / ${number(target)} · ${formatAchievement(achievementRatio(current, target))}`
}

function issueTagType(tag) {
  if (['异常结束', '有错误', '低成功率'].includes(tag)) return 'danger'
  if (['延迟高', 'RPM低', 'TPM低'].includes(tag)) return 'warning'
  if (tag === '运行中') return 'success'
  return 'info'
}

function errorText(value) {
  if (!value) return ''
  return String(value).replace(/\s+/g, ' ').slice(0, 120)
}

function runtimeText(item) {
  const startedAt = Date.parse(item.started_at || '')
  const completedAt = Date.parse(item.completed_at || '')
  if (!Number.isNaN(startedAt)) {
    const end = Number.isNaN(completedAt) ? Date.now() : completedAt
    return duration((end - startedAt) / 1000)
  }
  return `${number(item.concurrency)} 并发`
}

function numeric(value, fallback = 0) {
  const numberValue = Number(value)
  if (value === undefined || value === null || Number.isNaN(numberValue)) return fallback
  return numberValue
}

function duration(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  const total = Math.max(0, Math.round(Number(value)))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function time(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(date)
}

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
  return `${Number(value).toFixed(2)}s`
}

watch([items, samples], () => {
  nextTick(renderCharts)
}, { deep: true })

onMounted(async () => {
  await loadData()
  await nextTick()
  renderCharts()
  window.addEventListener('resize', resizeCharts)
  timer = window.setInterval(loadData, 3000)
})

onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.removeEventListener('resize', resizeCharts)
  trendChart?.dispose()
  statusChart?.dispose()
  protocolChart?.dispose()
})
</script>

<style scoped>
.panel-subtitle {
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
}

.refresh-alert {
  margin-bottom: 14px;
}

.diagnosis-summary {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid #dfe7f2;
  border-left-width: 5px;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.diagnosis-summary.healthy {
  border-left-color: #16a34a;
}

.diagnosis-summary.warning {
  border-left-color: #f59e0b;
}

.diagnosis-summary.critical {
  border-left-color: #dc2626;
}

.diagnosis-summary.idle {
  border-left-color: #64748b;
}

.diagnosis-status {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 24px;
}

.diagnosis-summary.healthy .diagnosis-status {
  background: #ecfdf3;
  color: #16a34a;
}

.diagnosis-summary.warning .diagnosis-status {
  background: #fffbeb;
  color: #d97706;
}

.diagnosis-summary.critical .diagnosis-status {
  background: #fef2f2;
  color: #dc2626;
}

.diagnosis-main {
  min-width: 0;
}

.diagnosis-kicker {
  color: #64748b;
  font-size: 12px;
}

.diagnosis-main strong {
  display: block;
  margin-top: 4px;
  color: #111827;
  font-size: 18px;
  line-height: 1.35;
}

.diagnosis-ratios,
.diagnosis-reasons,
.diagnosis-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.diagnosis-ratios {
  margin-top: 10px;
}

.diagnosis-ratios span {
  padding: 4px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
}

.diagnosis-reasons {
  margin-top: 8px;
}

.diagnosis-reasons span {
  max-width: 100%;
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnosis-actions {
  justify-content: flex-end;
}

.live-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.live-card {
  position: relative;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 12px;
  min-height: 118px;
  padding: 18px;
  overflow: hidden;
  border-radius: 8px;
  color: #ffffff;
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.14);
}

.live-card::after {
  position: absolute;
  right: -22px;
  bottom: -28px;
  width: 112px;
  height: 112px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  content: "";
}

.live-card.blue {
  background: linear-gradient(135deg, #2563eb, #06b6d4);
}

.live-card.green {
  background: linear-gradient(135deg, #16a34a, #14b8a6);
}

.live-card.purple {
  background: linear-gradient(135deg, #7c3aed, #db2777);
}

.live-card.orange {
  background: linear-gradient(135deg, #f97316, #ef4444);
}

.live-card.red {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
}

.live-card-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 22px;
}

.live-card-label {
  font-size: 13px;
  opacity: 0.88;
}

.live-card-value {
  margin-top: 8px;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 28px;
  font-weight: 800;
  line-height: 1.1;
}

.live-card-sub {
  margin-top: 8px;
  font-size: 12px;
  opacity: 0.86;
}

.diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.diagnostic-card {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid #dfe7f2;
  border-left-width: 4px;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.diagnostic-card.ok {
  border-left-color: #16a34a;
}

.diagnostic-card.warning {
  border-left-color: #f59e0b;
}

.diagnostic-card.danger {
  border-left-color: #dc2626;
}

.diagnostic-label {
  color: #64748b;
  font-size: 12px;
}

.diagnostic-card strong {
  display: block;
  margin-top: 6px;
  overflow: hidden;
  color: #111827;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnostic-card span {
  display: block;
  margin-top: 6px;
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.live-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.8fr);
  gap: 14px;
  margin-top: 16px;
}

.chart-tile,
.activity-tile {
  min-width: 0;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.chart-tile.large {
  grid-row: span 2;
}

.tile-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px 0;
}

.tile-header h3 {
  margin: 0;
  color: #111827;
  font-size: 16px;
}

.tile-header span {
  color: #64748b;
  font-size: 12px;
}

.live-chart {
  width: 100%;
  height: 300px;
}

.large .live-chart {
  height: 430px;
}

.activity-list {
  display: grid;
  gap: 8px;
  padding: 14px 18px 18px;
}

.activity-row {
  display: grid;
  grid-template-columns: 14px minmax(170px, 1fr) 72px minmax(260px, 1fr);
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 10px;
  border: 1px solid #e5edf6;
  border-radius: 8px;
  background: #f8fbff;
  color: #1e293b;
  text-align: left;
}

.activity-row:hover {
  border-color: #93b4e8;
  background: #eff6ff;
}

.activity-main,
.activity-metrics {
  display: flex;
  min-width: 0;
  gap: 4px;
}

.activity-main {
  flex-direction: column;
}

.activity-main > strong,
.activity-main > span:not(.issue-tags) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-main > span:not(.issue-tags),
.activity-runtime,
.activity-metrics em {
  color: #64748b;
  font-size: 12px;
}

.activity-main .activity-error {
  color: #b91c1c;
}

.issue-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}

.activity-runtime {
  font-family: "Fira Code", Consolas, monospace;
  text-align: right;
}

.activity-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
  font-family: "Fira Code", Consolas, monospace;
}

.activity-metrics span {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.activity-metrics strong,
.activity-metrics em {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-metrics em {
  font-style: normal;
}

.activity-metrics strong {
  color: #1e293b;
  font-size: 13px;
}

.activity-metrics,
.activity-runtime {
  font-family: "Fira Code", Consolas, monospace;
}

.empty-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 44px 18px;
  color: #64748b;
  text-align: center;
}

.empty-state strong {
  color: #1e293b;
  font-size: 15px;
}

.empty-state span {
  max-width: 320px;
  line-height: 1.6;
}

.realtime-panel:fullscreen {
  margin: 0;
  min-height: 100vh;
  padding: 18px;
  border: 0;
  border-radius: 0;
  background:
    radial-gradient(circle at 12% 8%, rgba(37, 99, 235, 0.22), transparent 30%),
    radial-gradient(circle at 88% 16%, rgba(249, 115, 22, 0.16), transparent 28%),
    #07111f;
  color: #e5eefb;
}

.realtime-panel:fullscreen .section-header {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.72);
}

.realtime-panel:fullscreen .section-title,
.realtime-panel:fullscreen .tile-header h3,
.realtime-panel:fullscreen .diagnosis-main strong,
.realtime-panel:fullscreen .diagnostic-card strong,
.realtime-panel:fullscreen .activity-metrics strong,
.realtime-panel:fullscreen .empty-state strong {
  color: #f8fafc;
}

.realtime-panel:fullscreen .panel-subtitle,
.realtime-panel:fullscreen .tile-header span,
.realtime-panel:fullscreen .activity-main > span:not(.issue-tags),
.realtime-panel:fullscreen .activity-runtime,
.realtime-panel:fullscreen .activity-metrics em,
.realtime-panel:fullscreen .diagnosis-kicker,
.realtime-panel:fullscreen .diagnosis-reasons span,
.realtime-panel:fullscreen .diagnostic-label,
.realtime-panel:fullscreen .diagnostic-card span,
.realtime-panel:fullscreen .empty-state {
  color: #94a3b8;
}

.realtime-panel:fullscreen .diagnosis-ratios span {
  background: rgba(148, 163, 184, 0.14);
  color: #cbd5e1;
}

.realtime-panel:fullscreen .section-body {
  background: transparent;
}

.realtime-panel:fullscreen .chart-tile,
.realtime-panel:fullscreen .diagnosis-summary,
.realtime-panel:fullscreen .diagnostic-card,
.realtime-panel:fullscreen .activity-tile {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.76);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.24);
}

.realtime-panel:fullscreen .activity-row {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.72);
  color: #e5eefb;
}

.realtime-panel:fullscreen .activity-row:hover {
  border-color: rgba(59, 130, 246, 0.72);
  background: rgba(30, 41, 59, 0.86);
}

@media (max-width: 1180px) {
  .live-card-grid,
  .diagnostic-grid,
  .live-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chart-tile.large {
    grid-row: auto;
  }
}

@media (max-width: 720px) {
  .live-card-grid,
  .diagnostic-grid,
  .live-layout {
    grid-template-columns: 1fr;
  }

  .diagnosis-summary {
    grid-template-columns: 1fr;
  }

  .diagnosis-actions {
    justify-content: flex-start;
  }

  .live-card {
    grid-template-columns: 1fr;
  }

  .live-card-value {
    font-size: 24px;
  }

  .activity-row {
    grid-template-columns: 14px minmax(0, 1fr);
  }

  .activity-runtime,
  .activity-metrics {
    grid-column: 2;
  }

  .activity-runtime {
    text-align: left;
  }

  .activity-metrics span {
    align-items: flex-start;
  }
}
</style>
