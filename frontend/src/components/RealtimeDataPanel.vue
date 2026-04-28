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
        <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div class="section-body">
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

      <div class="live-layout">
        <div class="chart-tile large">
          <div class="tile-header">
            <h3>吞吐实时趋势</h3>
            <span>RPM / TPM</span>
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

        <div class="activity-tile">
          <div class="tile-header">
            <h3>最近测试任务</h3>
            <span>按创建时间排序</span>
          </div>
          <div v-if="!items.length && !loading" class="empty-state">暂无测试数据</div>
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
                <span>{{ protocolText(item.api_protocol) }} · {{ item.model }} · {{ item.concurrency }} 并发</span>
              </span>
              <span class="activity-metric">
                <strong>{{ rpmOf(item) }}</strong>
                <span>RPM</span>
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
import { DataAnalysis, Histogram, Refresh, TrendCharts } from '@element-plus/icons-vue'
import { listTests } from '../api/client'

const router = useRouter()
const loading = ref(false)
const items = ref([])
const total = ref(0)
const samples = ref([])
const trendEl = ref()
const statusEl = ref()
const protocolEl = ref()
let timer
let trendChart
let statusChart
let protocolChart

const activeStatuses = ['queued', 'running', 'stopping']
const activeTasks = computed(() => items.value.filter((item) => activeStatuses.includes(item.status)))
const recentItems = computed(() => items.value.slice(0, 6))
const aggregate = computed(() => {
  const running = items.value.filter((item) => item.status === 'running')
  const source = running.length ? running : items.value.slice(0, 12)
  const rpm = source.reduce((sum, item) => sum + numeric(item.progress?.current_rpm ?? item.summary?.results?.rpm), 0)
  const tpm = source.reduce((sum, item) => sum + numeric(item.progress?.current_tpm ?? item.summary?.results?.total_tpm), 0)
  const successRates = source
    .map((item) => numeric(item.progress?.success_rate ?? item.summary?.results?.success_rate, null))
    .filter((value) => value !== null)
  const successRate = successRates.length
    ? successRates.reduce((sum, value) => sum + value, 0) / successRates.length
    : null
  const p95Values = source
    .map((item) => numeric(item.summary?.results?.latency_sec?.p95, null))
    .filter((value) => value !== null)
  const p95 = p95Values.length ? Math.max(...p95Values) : null
  return { rpm, tpm, successRate, p95 }
})

const metricCards = computed(() => [
  {
    label: '活跃任务',
    value: number(activeTasks.value.length),
    sub: `最近 ${number(items.value.length)} 条任务`,
    icon: DataAnalysis,
    tone: 'blue'
  },
  {
    label: '实时 RPM',
    value: number(aggregate.value.rpm),
    sub: '运行任务聚合',
    icon: TrendCharts,
    tone: 'green'
  },
  {
    label: '实时 TPM',
    value: number(aggregate.value.tpm),
    sub: '输入 + 输出 Token',
    icon: Histogram,
    tone: 'purple'
  },
  {
    label: '成功率 / P95',
    value: percent(aggregate.value.successRate),
    sub: `P95 ${seconds(aggregate.value.p95)}`,
    icon: DataAnalysis,
    tone: 'orange'
  }
])

async function loadData() {
  loading.value = true
  try {
    const data = await listTests({ page: 1, page_size: 100 })
    items.value = data.items || []
    total.value = data.total || 0
    pushSample()
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
    ...samples.value.slice(-29),
    {
      time: now,
      rpm: Math.round(aggregate.value.rpm * 100) / 100,
      tpm: Math.round(aggregate.value.tpm),
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
    color: ['#2563eb', '#8b5cf6', '#16a34a'],
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
      { name: '成功率 %', type: 'line', smooth: true, showSymbol: false, data: samples.value.map((item) => item.successRate) }
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
      data: Object.entries(countBy(items.value, 'status')).map(([key, value]) => ({
        name: names[key] || key,
        value,
        itemStyle: { color: colors[key] || '#64748b' }
      }))
    }]
  }
}

function protocolOption() {
  const counts = countBy(items.value, 'api_protocol')
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

function goTask(item) {
  if (['completed', 'failed', 'cancelled', 'interrupted'].includes(item.status)) {
    router.push(`/tests/${item.id}/report`)
    return
  }
  router.push(`/tests/${item.id}/run`)
}

function rpmOf(item) {
  return number(item.progress?.current_rpm ?? item.summary?.results?.rpm)
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic'
  if (protocol === 'gemini') return 'Gemini'
  return 'OpenAI'
}

function numeric(value, fallback = 0) {
  const numberValue = Number(value)
  if (value === undefined || value === null || Number.isNaN(numberValue)) return fallback
  return numberValue
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
  grid-template-columns: 14px minmax(0, 1fr) 74px;
  gap: 10px;
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
.activity-metric {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.activity-main strong,
.activity-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-main span,
.activity-metric span {
  color: #64748b;
  font-size: 12px;
}

.activity-metric {
  align-items: flex-end;
  font-family: "Fira Code", Consolas, monospace;
}

.empty-state {
  padding: 54px 18px;
  color: #64748b;
  text-align: center;
}

@media (max-width: 1180px) {
  .live-card-grid,
  .live-layout {
    grid-template-columns: 1fr;
  }

  .chart-tile.large {
    grid-row: auto;
  }
}

@media (max-width: 720px) {
  .live-card {
    grid-template-columns: 1fr;
  }

  .live-card-value {
    font-size: 24px;
  }

  .activity-row {
    grid-template-columns: 14px minmax(0, 1fr);
  }

  .activity-metric {
    grid-column: 2;
    align-items: flex-start;
  }
}
</style>
