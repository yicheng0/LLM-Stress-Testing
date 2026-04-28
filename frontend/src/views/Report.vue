<template>
  <div v-loading="loading">
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">报告概览</h2>
        <div class="toolbar">
          <el-button :icon="Monitor" @click="router.push(`/tests/${id}/run`)">运行页</el-button>
          <el-button :icon="CopyDocument" @click="copyRerun">复制配置</el-button>
          <el-dropdown trigger="click" :disabled="!downloadItems.length" @command="openDownload">
            <el-button type="primary" :icon="Download">
              导出报告
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="item in downloadItems"
                  :key="item.kind"
                  :command="item.kind"
                >
                  {{ item.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div class="section-body">
        <el-descriptions :column="4" border>
          <el-descriptions-item label="模式">{{ isMatrix ? '矩阵测试' : '单次测试' }}</el-descriptions-item>
          <el-descriptions-item label="协议">{{ protocolText(config.api_protocol) }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ config.model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="并发">{{ config.concurrency || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ effectiveDuration }} 秒</el-descriptions-item>
          <el-descriptions-item label="流式">{{ config.enable_stream ? '开启' : '关闭' }}</el-descriptions-item>
          <el-descriptions-item label="测试点">{{ isMatrix ? summary.test_points : '-' }}</el-descriptions-item>
          <el-descriptions-item label="Base URL" :span="2">{{ config.base_url || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Endpoint" :span="2">{{ config.endpoint || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <template v-if="isMatrix">
      <MetricCards :items="matrixMetricItems" />
      <div class="grid-2 report-grid">
        <ChartPanel title="矩阵 TPM" :option="matrixTpmOption" />
        <ChartPanel title="矩阵 P95 延迟" :option="matrixLatencyOption" />
      </div>
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">矩阵测试点</h2>
        </div>
        <div class="section-body">
          <el-table :data="matrixPoints" border>
            <el-table-column prop="input_tokens" label="输入 Token" />
            <el-table-column prop="concurrency" label="并发" />
            <el-table-column prop="rpm" label="RPM" />
            <el-table-column prop="total_tpm" label="TPM" />
            <el-table-column label="成功率">
              <template #default="{ row }">{{ percent(row.success_rate) }}</template>
            </el-table-column>
            <el-table-column prop="latency_p95" label="P95 延迟" />
            <el-table-column prop="ttft_p95" label="P95 TTFT" />
          </el-table>
        </div>
      </div>
    </template>

    <template v-else>
      <MetricCards :items="metricItems" />

      <div class="grid-2 report-grid">
        <div class="section">
          <div class="section-header">
            <h2 class="section-title">延迟分布</h2>
          </div>
          <div class="section-body">
            <MetricsTable :rows="latencyRows" />
          </div>
        </div>

        <div class="section">
          <div class="section-header">
            <h2 class="section-title">吞吐指标</h2>
          </div>
          <div class="section-body">
            <el-table :data="throughputRows" border>
              <el-table-column prop="name" label="指标" />
              <el-table-column prop="value" label="数值" />
            </el-table>
          </div>
        </div>
      </div>

      <div class="grid-2">
        <ChartPanel title="时间序列" :option="timeseriesOption" />
        <ChartPanel title="延迟直方图" :option="latencyHistogramOption" />
        <ChartPanel title="TTFT / Decode" :option="ttftDecodeOption" />
        <ChartPanel title="错误分布" :option="errorOption" />
      </div>

      <div class="section">
        <div class="section-header">
          <h2 class="section-title">请求明细</h2>
          <el-button :icon="Refresh" :loading="detailsLoading" @click="loadDetails">刷新</el-button>
        </div>
        <div class="section-body">
          <el-table :data="details.items" v-loading="detailsLoading" border>
            <el-table-column prop="request_id" label="ID" width="80" />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.ok ? 'success' : 'danger'" effect="plain">{{ row.ok ? 'OK' : 'FAIL' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态码" width="90" />
            <el-table-column label="延迟" width="110">
              <template #default="{ row }">{{ seconds(row.latency_sec) }}</template>
            </el-table-column>
            <el-table-column label="TTFT" width="110">
              <template #default="{ row }">{{ seconds(row.ttft_sec) }}</template>
            </el-table-column>
            <el-table-column prop="total_tokens" label="Token" width="110" />
            <el-table-column prop="error_type" label="错误类型" min-width="130" />
            <el-table-column prop="error_message" label="错误信息" min-width="220" show-overflow-tooltip />
          </el-table>
          <div class="pagination-row">
            <el-pagination
              v-model:current-page="details.page"
              v-model:page-size="details.pageSize"
              :total="details.total"
              :page-sizes="[20, 50, 100, 200]"
              layout="total, sizes, prev, pager, next"
              @change="loadDetails"
            />
          </div>
        </div>
      </div>
    </template>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">事件</h2>
      </div>
      <div class="section-body">
        <el-timeline>
          <el-timeline-item
            v-for="event in report?.events || []"
            :key="event.id"
            :timestamp="formatTime(event.created_at)"
            :type="eventType(event.level)"
          >
            {{ event.message }}
          </el-timeline-item>
        </el-timeline>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, CopyDocument, Download, Monitor, Refresh } from '@element-plus/icons-vue'
import ChartPanel from '../components/ChartPanel.vue'
import MetricCards from '../components/MetricCards.vue'
import MetricsTable from '../components/MetricsTable.vue'
import { downloadUrl, getDetails, getReport } from '../api/client'

const props = defineProps({
  id: {
    type: String,
    required: true
  }
})

const router = useRouter()
const report = ref(null)
const loading = ref(false)
const detailsLoading = ref(false)
const details = reactive({
  total: 0,
  page: 1,
  pageSize: 50,
  items: []
})

const summary = computed(() => report.value?.summary || {})
const config = computed(() => report.value?.config || summary.value?.config || {})
const results = computed(() => summary.value?.results || {})
const charts = computed(() => report.value?.charts || {})
const isMatrix = computed(() => Boolean(summary.value?.matrix))
const matrixPoints = computed(() => charts.value.matrix_points || [])
const effectiveDuration = computed(() => config.value.matrix_mode ? config.value.matrix_duration_sec : config.value.duration_sec)
const downloadItems = computed(() => [
  { kind: 'html', label: 'HTML 可视化报告' },
  { kind: 'markdown', label: 'Markdown 报告' },
  { kind: 'summary', label: 'Summary JSON' },
  { kind: 'details', label: 'Details JSONL' },
  { kind: 'matrix_csv', label: 'Matrix CSV' }
].filter((item) => hasFile(item.kind)))

const metricItems = computed(() => [
  { label: '总请求', value: number(results.value.total_requests), sub: `成功 ${number(results.value.successful_requests)}`, color: '#2563eb' },
  { label: '成功率', value: percent(results.value.success_rate), sub: `失败 ${number(results.value.failed_requests)}`, color: '#16a34a' },
  { label: 'RPM', value: number(results.value.rpm), sub: `QPS ${number(results.value.qps)}`, color: '#f97316' },
  { label: 'Total TPM', value: number(results.value.total_tpm), sub: `TPS ${number(results.value.total_tps)}`, color: '#334155' }
])

const matrixMetricItems = computed(() => {
  const bestTpm = Math.max(0, ...matrixPoints.value.map(item => Number(item.total_tpm || 0)))
  const bestRpm = Math.max(0, ...matrixPoints.value.map(item => Number(item.rpm || 0)))
  const minP95 = Math.min(...matrixPoints.value.map(item => Number(item.latency_p95 || Infinity)))
  return [
    { label: '测试点', value: number(summary.value.test_points), sub: '输入 Token x 并发', color: '#2563eb' },
    { label: '最高 TPM', value: number(bestTpm), sub: '矩阵峰值', color: '#f97316' },
    { label: '最高 RPM', value: number(bestRpm), sub: '矩阵峰值', color: '#16a34a' },
    { label: '最低 P95', value: minP95 === Infinity ? '-' : seconds(minP95), sub: '延迟最优点', color: '#334155' }
  ]
})

const latencyRows = computed(() => [
  metricRow('总延迟', 'latency_sec'),
  metricRow('TTFT', 'ttft_sec'),
  metricRow('Decode', 'decode_sec')
])

const throughputRows = computed(() => [
  { name: 'Input TPM', value: number(results.value.input_tpm) },
  { name: 'Output TPM', value: number(results.value.output_tpm) },
  { name: 'Total TPM', value: number(results.value.total_tpm) },
  { name: 'Input TPS', value: number(results.value.input_tps) },
  { name: 'Output TPS', value: number(results.value.output_tps) },
  { name: 'Total TPS', value: number(results.value.total_tps) },
  { name: '总输入 Token', value: number(results.value.total_input_tokens) },
  { name: '总输出 Token', value: number(results.value.total_output_tokens) }
])

const timeseriesOption = computed(() => {
  const data = charts.value.timeseries || []
  return lineOption(
    data.map(item => `${item.time_sec}s`),
    [
      { name: 'QPS', data: data.map(item => item.qps || 0), color: '#2563eb' },
      { name: 'TPM', data: data.map(item => item.tpm || 0), color: '#f97316' }
    ]
  )
})

const latencyHistogramOption = computed(() => histogramOption(charts.value.latency_histogram, 'Latency', '#2563eb'))

const ttftDecodeOption = computed(() => {
  const ttft = charts.value.ttft_histogram || { bins: [], counts: [] }
  const decode = charts.value.decode_histogram || { bins: [], counts: [] }
  const labels = ttft.bins.length >= decode.bins.length ? ttft.bins : decode.bins
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    grid: { left: 48, right: 24, top: 28, bottom: 58 },
    xAxis: { type: 'category', data: labels.map(item => Number(item).toFixed(2)) },
    yAxis: { type: 'value' },
    series: [
      { name: 'TTFT', type: 'bar', data: ttft.counts || [], itemStyle: { color: '#f97316' } },
      { name: 'Decode', type: 'bar', data: decode.counts || [], itemStyle: { color: '#2563eb' } }
    ]
  }
})

const errorOption = computed(() => {
  const counts = charts.value.error_counts || {}
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }))
  return {
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['45%', '72%'],
      data: data.length ? data : [{ name: '无错误', value: 1 }],
      color: data.length ? ['#dc2626', '#f97316', '#64748b', '#2563eb'] : ['#16a34a']
    }]
  }
})

const matrixTpmOption = computed(() => matrixBarOption('total_tpm', 'TPM', '#f97316'))
const matrixLatencyOption = computed(() => matrixBarOption('latency_p95', 'P95 延迟', '#2563eb'))

async function loadReport() {
  loading.value = true
  try {
    report.value = await getReport(props.id)
    if (!report.value?.summary?.matrix) {
      await loadDetails()
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadDetails() {
  detailsLoading.value = true
  try {
    const data = await getDetails(props.id, { page: details.page, page_size: details.pageSize })
    details.total = data.total
    details.page = data.page
    details.pageSize = data.page_size
    details.items = data.items
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    detailsLoading.value = false
  }
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

function histogramOption(histogram, name, color) {
  const data = histogram || { bins: [], counts: [] }
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 24, top: 28, bottom: 44 },
    xAxis: { type: 'category', data: (data.bins || []).map(item => Number(item).toFixed(2)) },
    yAxis: { type: 'value' },
    series: [{ name, type: 'bar', data: data.counts || [], itemStyle: { color } }]
  }
}

function lineOption(labels, series) {
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    grid: { left: 48, right: 24, top: 28, bottom: 58 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value' },
    series: series.map(item => ({
      name: item.name,
      type: 'line',
      smooth: true,
      data: item.data,
      itemStyle: { color: item.color }
    }))
  }
}

function matrixBarOption(field, label, color) {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 54, right: 24, top: 28, bottom: 80 },
    xAxis: {
      type: 'category',
      data: matrixPoints.value.map(item => `${item.input_tokens}/${item.concurrency}`),
      axisLabel: { rotate: 35 }
    },
    yAxis: { type: 'value' },
    series: [{ name: label, type: 'bar', data: matrixPoints.value.map(item => item[field] || 0), itemStyle: { color } }]
  }
}

function openDownload(kind) {
  window.open(downloadUrl(props.id, kind), '_blank')
}

function hasFile(kind) {
  return Boolean(report.value?.files?.[kind])
}

function copyRerun() {
  const copied = { ...config.value, name: `${config.value.name || 'LLM API 性能测试'} - 复跑` }
  delete copied.api_key
  sessionStorage.setItem('rerun_config', JSON.stringify(copied))
  router.push('/tests/new')
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function percent(value) {
  if (value === undefined || value === null) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function seconds(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${Number(value).toFixed(4)}s`
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}

function eventType(level) {
  if (level === 'error') return 'danger'
  if (level === 'warning') return 'warning'
  return 'primary'
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic Messages'
  if (protocol === 'gemini') return 'Gemini API'
  return 'OpenAI-compatible'
}

onMounted(loadReport)
</script>

<style scoped>
.report-grid {
  margin-top: 16px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
