<template>
  <div v-loading="loading">
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">测试对比</h2>
        <div class="toolbar">
          <el-tag effect="plain">{{ reports.length }} 个测试</el-tag>
          <el-button :icon="Clock" @click="router.push('/history')">返回历史</el-button>
        </div>
      </div>
      <div class="section-body">
        <el-empty v-if="!ids.length" description="请选择 2-4 条历史记录进行对比" />
        <el-alert
          v-else-if="ids.length < 2 || ids.length > 4"
          title="对比数量不符合要求"
          description="请从历史记录中选择 2-4 条测试。"
          type="warning"
          show-icon
          :closable="false"
        />
        <template v-else>
          <div class="compare-cards">
            <div v-for="item in compareItems" :key="item.id" class="compare-card">
              <div class="compare-card-head">
                <strong>{{ item.name }}</strong>
                <el-tag :type="item.matrix ? 'warning' : 'info'" effect="plain">
                  {{ item.matrix ? '矩阵' : '单点' }}
                </el-tag>
              </div>
              <div class="compare-meta">
                <span>{{ protocolText(item.protocol) }}</span>
                <span>{{ item.model }}</span>
                <span>{{ number(item.concurrency) }} 并发</span>
              </div>
              <div class="compare-values">
                <div>
                  <span>成功率</span>
                  <strong :class="rankClass(item.id, 'success_rate', true)">{{ percent(item.success_rate) }}</strong>
                </div>
                <div>
                  <span>TPM</span>
                  <strong :class="rankClass(item.id, 'total_tpm', true)">{{ number(item.total_tpm) }}</strong>
                </div>
                <div>
                  <span>RPM</span>
                  <strong :class="rankClass(item.id, 'rpm', true)">{{ number(item.rpm) }}</strong>
                </div>
                <div>
                  <span>P95</span>
                  <strong :class="rankClass(item.id, 'latency_p95', false)">{{ seconds(item.latency_p95) }}</strong>
                </div>
              </div>
            </div>
          </div>

          <div class="section nested-section">
            <div class="section-header">
              <h2 class="section-title">指标对比表</h2>
            </div>
            <div class="section-body">
              <el-table :data="metricRows" border>
                <el-table-column prop="label" label="指标" width="150" fixed />
                <el-table-column
                  v-for="item in compareItems"
                  :key="item.id"
                  :label="item.name"
                  min-width="160"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    <span :class="rowClass(item.id, row)">{{ row.format(item[row.field]) }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>

          <div class="section nested-section">
            <div class="section-header">
              <h2 class="section-title">差异结论</h2>
            </div>
            <div class="section-body">
              <div class="compare-advice">
                <el-alert
                  v-for="item in advice"
                  :key="item.title"
                  :title="item.title"
                  :description="item.description"
                  :type="item.type"
                  show-icon
                  :closable="false"
                />
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Clock } from '@element-plus/icons-vue'
import { getReport } from '../api/client'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const reports = ref([])
const ids = computed(() => String(route.query.ids || '').split(',').map((item) => item.trim()).filter(Boolean))
const compareItems = computed(() => reports.value.map(normalizeReport))
const metricRows = [
  { label: '成功率', field: 'success_rate', format: percent, higherBetter: true },
  { label: 'Total TPM', field: 'total_tpm', format: number, higherBetter: true },
  { label: 'RPM', field: 'rpm', format: number, higherBetter: true },
  { label: 'P95 延迟', field: 'latency_p95', format: seconds, higherBetter: false },
  { label: 'P99 延迟', field: 'latency_p99', format: seconds, higherBetter: false },
  { label: '平均延迟', field: 'latency_avg', format: seconds, higherBetter: false },
  { label: 'TTFT 平均', field: 'ttft_avg', format: seconds, higherBetter: false },
  { label: '失败请求', field: 'failed_requests', format: number, higherBetter: false }
]
const advice = computed(() => {
  const items = []
  const bestTpm = bestBy('total_tpm', true)
  const bestLatency = bestBy('latency_p95', false)
  const bestSuccess = bestBy('success_rate', true)
  if (bestTpm) {
    items.push({
      title: `最高吞吐：${bestTpm.name}`,
      description: `Total TPM 为 ${number(bestTpm.total_tpm)}，适合作为吞吐上限参考。`,
      type: 'success'
    })
  }
  if (bestLatency) {
    items.push({
      title: `最低 P95：${bestLatency.name}`,
      description: `P95 延迟为 ${seconds(bestLatency.latency_p95)}，适合作为低延迟配置参考。`,
      type: 'info'
    })
  }
  if (bestSuccess && Number(bestSuccess.success_rate || 0) < 0.99) {
    items.push({
      title: '所有测试成功率都低于 99%',
      description: '建议先降低并发或检查错误分布，再把结果作为容量基线。',
      type: 'warning'
    })
  }
  if (!items.length) {
    items.push({
      title: '暂无可对比结论',
      description: '请确认选择的测试已经完成并生成报告。',
      type: 'info'
    })
  }
  return items
})

async function loadReports() {
  if (ids.value.length < 2 || ids.value.length > 4) return
  loading.value = true
  try {
    reports.value = await Promise.all(ids.value.map((id) => getReport(id)))
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function normalizeReport(report) {
  const summary = report.summary || {}
  const config = report.config || summary.config || {}
  const matrix = Boolean(summary.matrix)
  const points = summary.results_matrix || []
  const result = matrix ? aggregateMatrix(points) : (summary.results || {})
  return {
    id: report.test_id,
    name: config.name || report.test_id,
    protocol: config.api_protocol || 'openai',
    model: config.model || '-',
    concurrency: config.concurrency,
    matrix,
    success_rate: result.success_rate,
    total_tpm: result.total_tpm,
    rpm: result.rpm,
    latency_p95: result.latency_sec_p95,
    latency_p99: result.latency_sec_p99,
    latency_avg: result.latency_sec_avg,
    ttft_avg: result.ttft_sec_avg,
    failed_requests: result.failed_requests
  }
}

function aggregateMatrix(points) {
  const results = points.map((item) => item.results || {})
  return {
    success_rate: average(results.map((item) => item.success_rate)),
    total_tpm: Math.max(0, ...results.map((item) => Number(item.total_tpm || 0))),
    rpm: Math.max(0, ...results.map((item) => Number(item.rpm || 0))),
    latency_sec_p95: minFinite(results.map((item) => Number(item.latency_sec_p95))),
    latency_sec_p99: minFinite(results.map((item) => Number(item.latency_sec_p99))),
    latency_sec_avg: average(results.map((item) => item.latency_sec_avg)),
    ttft_sec_avg: average(results.map((item) => item.ttft_sec_avg)),
    failed_requests: results.reduce((sum, item) => sum + Number(item.failed_requests || 0), 0)
  }
}

function rowClass(id, row) {
  return rankClass(id, row.field, row.higherBetter)
}

function rankClass(id, field, higherBetter) {
  const values = compareItems.value
    .map((item) => ({ id: item.id, value: Number(item[field]) }))
    .filter((item) => Number.isFinite(item.value))
  if (values.length < 2) return ''
  const best = values.sort((a, b) => higherBetter ? b.value - a.value : a.value - b.value)[0]
  return best.id === id ? 'best-value' : ''
}

function bestBy(field, higherBetter) {
  return [...compareItems.value]
    .filter((item) => Number.isFinite(Number(item[field])))
    .sort((a, b) => higherBetter ? Number(b[field]) - Number(a[field]) : Number(a[field]) - Number(b[field]))[0]
}

function average(values) {
  const items = values.map(Number).filter(Number.isFinite)
  return items.length ? items.reduce((sum, item) => sum + item, 0) / items.length : null
}

function minFinite(values) {
  const items = values.filter(Number.isFinite)
  return items.length ? Math.min(...items) : null
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic'
  if (protocol === 'gemini') return 'Gemini'
  return 'OpenAI-compatible'
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function percent(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function seconds(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return `${Number(value).toFixed(3)}s`
}

onMounted(loadReports)
</script>

<style scoped>
.compare-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.compare-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.compare-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.compare-card-head strong {
  min-width: 0;
  overflow: hidden;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compare-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}

.compare-values {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.compare-values div {
  padding: 10px;
  border-radius: 8px;
  background: #f8fbff;
}

.compare-values span,
.compare-values strong {
  display: block;
}

.compare-values span {
  color: #64748b;
  font-size: 12px;
}

.compare-values strong,
.best-value {
  margin-top: 5px;
  color: #16a34a;
  font-family: "Fira Code", Consolas, monospace;
  font-weight: 800;
}

.nested-section {
  margin-top: 16px;
  margin-bottom: 0;
  box-shadow: none;
}

.compare-advice {
  display: grid;
  gap: 10px;
}

@media (max-width: 1180px) {
  .compare-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .compare-cards {
    grid-template-columns: 1fr;
  }
}
</style>
