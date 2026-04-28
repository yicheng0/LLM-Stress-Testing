<template>
  <div class="print-page" v-loading="loading">
    <div class="print-actions">
      <el-button :icon="Back" @click="router.push(`/tests/${id}/report`)">返回报告</el-button>
      <el-button type="primary" :icon="Printer" @click="printReport">打印 / 另存为 PDF</el-button>
    </div>

    <main class="report-sheet">
      <header class="report-cover">
        <div class="brand-row">
          <img class="report-logo" src="https://wenwen-us.oss-us-west-1.aliyuncs.com/apipro_logo.png" alt="APIPro" />
          <div>
            <div class="brand-name">APIPro LLM Benchmark Studio</div>
            <div class="brand-desc">LLM API 性能测试报告</div>
          </div>
        </div>
        <div class="report-meta">
          <div>开发团队：APIPro 团队</div>
          <div>生成时间：{{ formatDateTime(new Date()) }}</div>
          <div>报告 ID：{{ id }}</div>
        </div>
      </header>

      <section class="summary-band">
        <div>
          <h1>{{ config.name || 'LLM API 性能测试报告' }}</h1>
          <p>{{ isMatrix ? '矩阵测试' : '单次测试' }} · {{ protocolText(config.api_protocol) }} · {{ config.model || '-' }}</p>
        </div>
        <div class="status-pill">{{ isMatrix ? `${number(summary.test_points)} 个测试点` : `${number(results.total_requests)} 次请求` }}</div>
      </section>

      <section class="report-section">
        <h2>测试配置</h2>
        <div class="info-grid">
          <div><span>协议</span><strong>{{ protocolText(config.api_protocol) }}</strong></div>
          <div><span>模型</span><strong>{{ config.model || '-' }}</strong></div>
          <div><span>节点</span><strong>{{ nodeText(config.base_url) }}</strong></div>
          <div><span>Base URL</span><strong>{{ config.base_url || '-' }}</strong></div>
          <div><span>Endpoint</span><strong>{{ config.endpoint || '-' }}</strong></div>
          <div><span>并发</span><strong>{{ number(config.concurrency) }}</strong></div>
          <div><span>输入 Token</span><strong>{{ number(config.input_tokens) }}</strong></div>
          <div><span>最大输出 Token</span><strong>{{ number(config.max_output_tokens) }}</strong></div>
          <div><span>测试时长</span><strong>{{ number(effectiveDuration) }} 秒</strong></div>
          <div><span>流式模式</span><strong>{{ config.enable_stream ? '开启' : '关闭' }}</strong></div>
        </div>
      </section>

      <section class="report-section">
        <h2>核心指标</h2>
        <div class="metric-grid">
          <div v-for="item in metricItems" :key="item.label" class="print-metric">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.sub }}</small>
          </div>
        </div>
      </section>

      <template v-if="isMatrix">
        <section class="report-section page-avoid">
          <h2>矩阵结果热力图</h2>
          <div ref="matrixHeatmapEl" class="print-chart chart-tall" />
        </section>

        <section class="report-section">
          <h2>矩阵测试点明细</h2>
          <table class="print-table">
            <thead>
              <tr>
                <th>输入 Token</th>
                <th>并发</th>
                <th>RPM</th>
                <th>TPS</th>
                <th>TPM</th>
                <th>成功率</th>
                <th>TTFT Avg</th>
                <th>TTFT P50</th>
                <th>TTFT P99</th>
                <th>耗时 Avg</th>
                <th>耗时 P50</th>
                <th>耗时 P99</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="point in matrixPoints" :key="`${point.input_tokens}-${point.concurrency}`">
                <td>{{ number(point.input_tokens) }}</td>
                <td>{{ number(point.concurrency) }}</td>
                <td>{{ number(point.rpm) }}</td>
                <td>{{ number(point.total_tps) }}</td>
                <td>{{ number(point.total_tpm) }}</td>
                <td>{{ percent(point.success_rate) }}</td>
                <td>{{ seconds(point.ttft_avg) }}</td>
                <td>{{ seconds(point.ttft_p50) }}</td>
                <td>{{ seconds(point.ttft_p99) }}</td>
                <td>{{ seconds(point.latency_avg) }}</td>
                <td>{{ seconds(point.latency_p50) }}</td>
                <td>{{ seconds(point.latency_p99) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <template v-else>
        <section class="report-section">
          <h2>延迟分布</h2>
          <table class="print-table">
            <thead>
              <tr>
                <th>指标</th>
                <th>Average</th>
                <th>P50</th>
                <th>P90</th>
                <th>P95</th>
                <th>P99</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in latencyRows" :key="row.name">
                <td>{{ row.name }}</td>
                <td>{{ row.avg }}</td>
                <td>{{ row.p50 }}</td>
                <td>{{ row.p90 }}</td>
                <td>{{ row.p95 }}</td>
                <td>{{ row.p99 }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="report-section chart-grid page-avoid">
          <div>
            <h2>时间序列</h2>
            <div ref="timeseriesEl" class="print-chart" />
          </div>
          <div>
            <h2>延迟直方图</h2>
            <div ref="latencyHistogramEl" class="print-chart" />
          </div>
          <div>
            <h2>TTFT / Decode</h2>
            <div ref="ttftDecodeEl" class="print-chart" />
          </div>
          <div>
            <h2>错误分布</h2>
            <div ref="errorEl" class="print-chart" />
          </div>
        </section>
      </template>

      <section class="report-section">
        <h2>事件摘要</h2>
        <table class="print-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>级别</th>
              <th>事件</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="event in report?.events || []" :key="event.id">
              <td>{{ formatDateTime(event.created_at) }}</td>
              <td>{{ event.level }}</td>
              <td>{{ event.message }}</td>
            </tr>
            <tr v-if="!report?.events?.length">
              <td colspan="3">暂无事件</td>
            </tr>
          </tbody>
        </table>
      </section>

      <footer class="report-footer">
        APIPro LLM Benchmark Studio · 国内节点 https://api.wenwen-ai.com · 海外节点 https://api.apipro.ai
      </footer>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, Printer } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { getReport } from '../api/client'

const props = defineProps({
  id: {
    type: String,
    required: true
  }
})

const route = useRoute()
const router = useRouter()
const report = ref(null)
const loading = ref(false)
const matrixHeatmapEl = ref(null)
const timeseriesEl = ref(null)
const latencyHistogramEl = ref(null)
const ttftDecodeEl = ref(null)
const errorEl = ref(null)
const chartMap = new Map()

const summary = computed(() => report.value?.summary || {})
const config = computed(() => report.value?.config || summary.value?.config || {})
const results = computed(() => summary.value?.results || {})
const charts = computed(() => report.value?.charts || {})
const isMatrix = computed(() => Boolean(summary.value?.matrix))
const matrixPoints = computed(() => charts.value.matrix_points || [])
const effectiveDuration = computed(() => config.value.matrix_mode ? config.value.matrix_duration_sec : config.value.duration_sec)

const metricItems = computed(() => {
  if (isMatrix.value) {
    const bestTpm = Math.max(0, ...matrixPoints.value.map((item) => Number(item.total_tpm || 0)))
    const bestRpm = Math.max(0, ...matrixPoints.value.map((item) => Number(item.rpm || 0)))
    const bestTps = Math.max(0, ...matrixPoints.value.map((item) => Number(item.total_tps || 0)))
    const successRates = matrixPoints.value.map((item) => Number(item.success_rate)).filter(Number.isFinite)
    const avgSuccess = successRates.length ? successRates.reduce((sum, item) => sum + item, 0) / successRates.length : null
    return [
      { label: '测试点', value: number(summary.value.test_points), sub: '输入 Token x 并发' },
      { label: '最高 TPM', value: number(bestTpm), sub: '矩阵峰值' },
      { label: '最高 RPM', value: number(bestRpm), sub: '矩阵峰值' },
      { label: '最高 TPS', value: number(bestTps), sub: `平均成功率 ${percent(avgSuccess)}` }
    ]
  }
  return [
    { label: '总请求', value: number(results.value.total_requests), sub: `成功 ${number(results.value.successful_requests)}` },
    { label: '成功率', value: percent(results.value.success_rate), sub: `失败 ${number(results.value.failed_requests)}` },
    { label: 'RPM', value: number(results.value.rpm), sub: `TPS ${number(results.value.total_tps)}` },
    { label: 'Total TPM', value: number(results.value.total_tpm), sub: `QPS ${number(results.value.qps)}` }
  ]
})

const latencyRows = computed(() => [
  metricRow('总耗时', 'latency_sec'),
  metricRow('TTFT', 'ttft_sec'),
  metricRow('Decode', 'decode_sec')
])

async function loadReport() {
  loading.value = true
  try {
    report.value = await getReport(props.id)
    await nextTick()
    renderCharts()
    if (route.query.autoprint === '1') {
      window.setTimeout(printReport, 650)
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function renderCharts() {
  if (isMatrix.value) {
    renderChart('matrixHeatmap', matrixHeatmapEl.value, matrixHeatmapOption())
    return
  }
  renderChart('timeseries', timeseriesEl.value, timeseriesOption())
  renderChart('latencyHistogram', latencyHistogramEl.value, histogramOption(charts.value.latency_histogram, 'Latency', '#2563eb'))
  renderChart('ttftDecode', ttftDecodeEl.value, ttftDecodeOption())
  renderChart('error', errorEl.value, errorOption())
}

function renderChart(key, element, option) {
  if (!element) return
  let chart = chartMap.get(key)
  if (!chart) {
    chart = echarts.init(element, null, { renderer: 'canvas' })
    chartMap.set(key, chart)
  }
  chart.setOption(option, true)
  chart.resize()
}

function printReport() {
  chartMap.forEach((chart) => chart.resize())
  window.setTimeout(() => window.print(), 120)
}

function metricRow(label, prefix) {
  return {
    name: label,
    avg: seconds(results.value[`${prefix}_avg`]),
    p50: seconds(results.value[`${prefix}_p50`]),
    p90: seconds(results.value[`${prefix}_p90`]),
    p95: seconds(results.value[`${prefix}_p95`]),
    p99: seconds(results.value[`${prefix}_p99`])
  }
}

function matrixHeatmapOption() {
  const inputs = uniqueSorted(matrixPoints.value.map((item) => item.input_tokens))
  const concurrency = uniqueSorted(matrixPoints.value.map((item) => item.concurrency))
  const values = matrixPoints.value.map((item) => Number(item.total_tpm)).filter(Number.isFinite)
  const max = Math.max(1, ...values)
  const pointMap = new Map(matrixPoints.value.map((item) => [
    `${Number(item.input_tokens)}:${Number(item.concurrency)}`,
    item
  ]))
  const data = []
  inputs.forEach((inputTokens, yIndex) => {
    concurrency.forEach((concurrencyValue, xIndex) => {
      const point = pointMap.get(`${inputTokens}:${concurrencyValue}`)
      data.push([xIndex, yIndex, point ? Number(point.total_tpm || 0) : null])
    })
  })
  return {
    animation: false,
    grid: { left: 82, right: 28, top: 24, bottom: 76 },
    xAxis: { type: 'category', name: '并发', nameLocation: 'middle', nameGap: 42, data: concurrency.map(String), splitArea: { show: true } },
    yAxis: { type: 'category', name: '输入 Token', nameGap: 54, data: inputs.map(compactNumber), splitArea: { show: true } },
    visualMap: { min: 0, max, calculable: false, orient: 'horizontal', left: 'center', bottom: 10, inRange: { color: ['#eff6ff', '#93c5fd', '#16a34a'] } },
    series: [{
      name: 'TPM',
      type: 'heatmap',
      data,
      label: { show: true, formatter: (params) => compactNumber(params.data?.[2]) },
      itemStyle: { borderColor: '#ffffff', borderWidth: 2 }
    }]
  }
}

function timeseriesOption() {
  const data = charts.value.timeseries || []
  return lineOption(
    data.map((item) => `${item.time_sec}s`),
    [
      { name: 'QPS', data: data.map((item) => item.qps || 0), color: '#2563eb' },
      { name: 'TPM', data: data.map((item) => item.tpm || 0), color: '#f97316' }
    ]
  )
}

function histogramOption(histogram, name, color) {
  const data = histogram || { bins: [], counts: [] }
  return {
    animation: false,
    grid: { left: 48, right: 18, top: 24, bottom: 40 },
    xAxis: { type: 'category', data: (data.bins || []).map((item) => Number(item).toFixed(2)) },
    yAxis: { type: 'value' },
    series: [{ name, type: 'bar', data: data.counts || [], itemStyle: { color } }]
  }
}

function ttftDecodeOption() {
  const ttft = charts.value.ttft_histogram || { bins: [], counts: [] }
  const decode = charts.value.decode_histogram || { bins: [], counts: [] }
  const labels = ttft.bins.length >= decode.bins.length ? ttft.bins : decode.bins
  return {
    animation: false,
    legend: { bottom: 0 },
    grid: { left: 48, right: 18, top: 24, bottom: 54 },
    xAxis: { type: 'category', data: labels.map((item) => Number(item).toFixed(2)) },
    yAxis: { type: 'value' },
    series: [
      { name: 'TTFT', type: 'bar', data: ttft.counts || [], itemStyle: { color: '#f97316' } },
      { name: 'Decode', type: 'bar', data: decode.counts || [], itemStyle: { color: '#2563eb' } }
    ]
  }
}

function errorOption() {
  const counts = charts.value.error_counts || {}
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }))
  return {
    animation: false,
    series: [{
      type: 'pie',
      radius: ['45%', '72%'],
      data: data.length ? data : [{ name: '无错误', value: 1 }],
      color: data.length ? ['#dc2626', '#f97316', '#64748b', '#2563eb'] : ['#16a34a'],
      label: { formatter: '{b}: {c}' }
    }]
  }
}

function lineOption(labels, series) {
  return {
    animation: false,
    legend: { bottom: 0 },
    grid: { left: 48, right: 18, top: 24, bottom: 54 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value' },
    series: series.map((item) => ({
      name: item.name,
      type: 'line',
      smooth: true,
      data: item.data,
      itemStyle: { color: item.color }
    }))
  }
}

function uniqueSorted(values) {
  return [...new Set(values.map((item) => Number(item)).filter(Number.isFinite))].sort((a, b) => a - b)
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function compactNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))
}

function percent(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function seconds(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${Number(value).toFixed(4)}s`
}

function formatDateTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic Messages'
  if (protocol === 'gemini') return 'Gemini API'
  return 'OpenAI-compatible'
}

function nodeText(baseUrl) {
  if (baseUrl === 'https://api.wenwen-ai.com') return '国内节点'
  if (baseUrl === 'https://api.apipro.ai') return '海外节点'
  return '自定义节点'
}

onMounted(loadReport)
onBeforeUnmount(() => {
  chartMap.forEach((chart) => chart.dispose())
  chartMap.clear()
})
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 24px;
  background: #e7edf5;
  color: #172033;
}

.print-actions {
  position: sticky;
  z-index: 10;
  top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  max-width: 1120px;
  margin: 0 auto 16px;
}

.report-sheet {
  max-width: 1120px;
  margin: 0 auto;
  padding: 34px;
  border: 1px solid #d8e0ec;
  background: #ffffff;
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.14);
}

.report-cover,
.brand-row,
.summary-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.report-cover {
  padding-bottom: 22px;
  border-bottom: 2px solid #1d4ed8;
}

.brand-row {
  justify-content: flex-start;
}

.report-logo {
  width: 56px;
  height: 56px;
  border: 1px solid #d8e0ec;
  border-radius: 8px;
  object-fit: contain;
}

.brand-name {
  font-size: 22px;
  font-weight: 800;
}

.brand-desc,
.report-meta,
.summary-band p,
.info-grid span,
.print-metric span,
.print-metric small,
.report-footer {
  color: #64748b;
}

.report-meta {
  font-size: 12px;
  line-height: 1.8;
  text-align: right;
}

.summary-band {
  margin: 22px 0;
  padding: 20px 22px;
  border: 1px solid #cfe0f5;
  border-radius: 8px;
  background: #f8fbff;
}

.summary-band h1 {
  margin: 0;
  font-size: 26px;
  line-height: 1.3;
}

.summary-band p {
  margin: 8px 0 0;
}

.status-pill {
  flex: 0 0 auto;
  padding: 8px 12px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 800;
}

.report-section {
  margin-top: 22px;
}

.report-section h2 {
  margin: 0 0 12px;
  padding-left: 10px;
  border-left: 4px solid #2563eb;
  font-size: 17px;
}

.info-grid,
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.info-grid div,
.print-metric {
  min-height: 74px;
  padding: 12px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.info-grid span,
.print-metric span,
.print-metric small {
  display: block;
  font-size: 12px;
}

.info-grid strong,
.print-metric strong {
  display: block;
  margin-top: 7px;
  overflow-wrap: anywhere;
  font-size: 15px;
}

.print-metric strong {
  color: #1d4ed8;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 24px;
}

.print-metric small {
  margin-top: 4px;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.print-chart {
  width: 100%;
  height: 280px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.chart-tall {
  height: 360px;
}

.print-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.print-table th,
.print-table td {
  padding: 8px 9px;
  border: 1px solid #d8e0ec;
  text-align: left;
  vertical-align: top;
}

.print-table th {
  background: #f3f7fb;
  color: #334155;
  font-weight: 800;
}

.report-footer {
  margin-top: 28px;
  padding-top: 14px;
  border-top: 1px solid #d8e0ec;
  font-size: 12px;
  text-align: center;
}

@media print {
  @page {
    size: A4;
    margin: 12mm;
  }

  .print-page {
    min-height: auto;
    padding: 0;
    background: #ffffff;
  }

  .print-actions {
    display: none;
  }

  .report-sheet {
    max-width: none;
    padding: 0;
    border: 0;
    box-shadow: none;
  }

  .report-section,
  .summary-band,
  .print-metric,
  .info-grid div,
  .print-table tr {
    break-inside: avoid;
    page-break-inside: avoid;
  }

  .page-avoid {
    break-inside: avoid;
    page-break-inside: avoid;
  }

  .print-chart {
    height: 250px;
  }

  .chart-tall {
    height: 330px;
  }
}

@media (max-width: 860px) {
  .print-page {
    padding: 12px;
  }

  .report-sheet {
    padding: 18px;
  }

  .report-cover,
  .summary-band {
    align-items: flex-start;
    flex-direction: column;
  }

  .report-meta {
    text-align: left;
  }

  .info-grid,
  .metric-grid,
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
