<template>
  <div>
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">测试对比</h2>
        <div class="toolbar">
          <el-tag effect="plain">{{ reports.length }} 个测试</el-tag>
          <el-tag v-if="isCaseChannelMode" type="success" effect="plain">渠道报告</el-tag>
          <el-button :icon="Clock" @click="router.push('/history')">返回历史</el-button>
        </div>
      </div>
      <div class="section-body">
        <SkeletonLoader v-if="loading" variant="report" />
        <EmptyState
          v-else-if="!ids.length"
          title="请选择历史记录进行对比"
          description="从历史记录中勾选 2-4 条测试后，可以对比吞吐、延迟、成功率和容量结论。"
          action-label="返回历史"
          :action-icon="Clock"
          @action="router.push('/history')"
        />
        <el-alert
          v-else-if="!validCompareCount"
          title="对比数量不符合要求"
          :description="isCaseChannelMode ? '批量渠道报告支持 1-12 条测试。' : '请从历史记录中选择 2-4 条测试。'"
          type="warning"
          show-icon
          :closable="false"
        />
        <template v-else-if="isCaseChannelMode">
          <div class="batch-summary">
            <div>
              <span>批次</span>
              <strong>{{ batchSummary.name }}</strong>
            </div>
            <div>
              <span>Case</span>
              <strong>{{ batchSummary.caseCount }}</strong>
            </div>
            <div>
              <span>渠道</span>
              <strong>{{ batchSummary.channelCount }}</strong>
            </div>
            <div>
              <span>完成/总数</span>
              <strong>{{ batchSummary.completed }}/{{ batchSummary.total }}</strong>
            </div>
          </div>

          <div v-for="group in caseChannelGroups" :key="group.caseName" class="section nested-section">
            <div class="section-header">
              <h2 class="section-title">{{ group.caseName }}</h2>
              <el-tag effect="plain">{{ group.items.length }} 个渠道</el-tag>
            </div>
            <div class="section-body">
              <el-table :data="caseChannelMetricRows" border>
                <el-table-column prop="label" label="指标" width="150" fixed />
                <el-table-column
                  v-for="item in group.items"
                  :key="item.id"
                  :label="item.channelName"
                  min-width="170"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    <span :class="caseChannelRankClass(group.items, item.id, row)">
                      {{ row.format(item[row.field]) }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
              <div class="case-links">
                <el-button
                  v-for="item in group.items"
                  :key="`${item.id}-link`"
                  size="small"
                  @click="router.push(`/tests/${item.id}/report`)"
                >
                  {{ item.channelName }} 明细
                </el-button>
              </div>
            </div>
          </div>

          <div class="section nested-section">
            <div class="section-header">
              <h2 class="section-title">渠道结论</h2>
            </div>
            <div class="section-body">
              <div class="compare-advice">
                <el-alert
                  v-for="item in caseChannelAdvice"
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
import EmptyState from '../components/EmptyState.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { getReport } from '../api/client'
import { isTerminalTaskStatus } from '../utils/taskStatus'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const reports = ref([])
const ids = computed(() => String(route.query.ids || '').split(',').map((item) => item.trim()).filter(Boolean))
const isCaseChannelMode = computed(() => route.query.mode === 'case-channel')
const validCompareCount = computed(() => {
  if (isCaseChannelMode.value) return ids.value.length >= 1 && ids.value.length <= 12
  return ids.value.length >= 2 && ids.value.length <= 4
})
const compareItems = computed(() => reports.value.map(normalizeReport))
const caseChannelItems = computed(() => compareItems.value.filter((item) => item.batchId))
const caseChannelGroups = computed(() => {
  const groups = new Map()
  for (const item of caseChannelItems.value) {
    if (!groups.has(item.caseName)) groups.set(item.caseName, [])
    groups.get(item.caseName).push(item)
  }
  return [...groups.entries()].map(([caseName, items]) => ({
    caseName,
    items: items.sort((a, b) => a.channelIndex - b.channelIndex)
  })).sort((a, b) => {
    const left = a.items[0]?.caseIndex || 0
    const right = b.items[0]?.caseIndex || 0
    return left - right
  })
})
const batchSummary = computed(() => {
  const first = caseChannelItems.value[0] || {}
  return {
    name: first.batchName || '批量渠道诊断',
    total: caseChannelItems.value.length,
    completed: reports.value.filter((report) => isTerminalTaskStatus(report.task_status)).length,
    caseCount: new Set(caseChannelItems.value.map((item) => item.caseName)).size,
    channelCount: new Set(caseChannelItems.value.map((item) => item.channelName)).size
  }
})
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
const caseChannelMetricRows = [
  { label: '成功率', field: 'success_rate', format: percent, higherBetter: true },
  { label: 'TTFT 平均', field: 'ttft_avg', format: seconds, higherBetter: false },
  { label: 'P95 延迟', field: 'latency_p95', format: seconds, higherBetter: false },
  { label: 'P99 延迟', field: 'latency_p99', format: seconds, higherBetter: false },
  { label: 'RPM', field: 'rpm', format: number, higherBetter: true },
  { label: 'Total TPM', field: 'total_tpm', format: number, higherBetter: true },
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
const caseChannelAdvice = computed(() => {
  const items = []
  for (const group of caseChannelGroups.value) {
    const bestTtft = bestFrom(group.items, 'ttft_avg', false)
    const bestSuccess = bestFrom(group.items, 'success_rate', true)
    if (bestTtft) {
      items.push({
        title: `${group.caseName} 最低 TTFT：${bestTtft.channelName}`,
        description: `平均 TTFT 为 ${seconds(bestTtft.ttft_avg)}，同 Case 下首 token 表现最好。`,
        type: 'info'
      })
    }
    if (bestSuccess && Number(bestSuccess.success_rate || 0) < 0.99) {
      items.push({
        title: `${group.caseName} 成功率不足 99%`,
        description: `当前最佳渠道为 ${bestSuccess.channelName}，成功率 ${percent(bestSuccess.success_rate)}，建议查看明细错误。`,
        type: 'warning'
      })
    }
  }
  if (!items.length) {
    items.push({
      title: '暂无渠道结论',
      description: '请等待子任务完成并生成报告后刷新。',
      type: 'info'
    })
  }
  return items.slice(0, 6)
})

async function loadReports() {
  if (!validCompareCount.value) return
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
    batchId: config.batch_id,
    batchName: config.batch_name,
    caseName: config.batch_case_name || config.name || report.test_id,
    caseIndex: Number(config.batch_case_index || 0),
    channelName: config.batch_channel_name || config.base_url || '-',
    channelIndex: Number(config.batch_channel_index || 0),
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

function caseChannelRankClass(items, id, row) {
  const values = items
    .map((item) => ({ id: item.id, value: Number(item[row.field]) }))
    .filter((item) => Number.isFinite(item.value))
  if (values.length < 2) return ''
  const best = values.sort((a, b) => row.higherBetter ? b.value - a.value : a.value - b.value)[0]
  return best.id === id ? 'best-value' : ''
}

function bestBy(field, higherBetter) {
  return [...compareItems.value]
    .filter((item) => Number.isFinite(Number(item[field])))
    .sort((a, b) => higherBetter ? Number(b[field]) - Number(a[field]) : Number(a[field]) - Number(b[field]))[0]
}

function bestFrom(items, field, higherBetter) {
  return [...items]
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

.batch-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.batch-summary > div {
  min-height: 82px;
  padding: 13px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.batch-summary span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.batch-summary strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  margin-top: 8px;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
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
  .compare-cards,
  .batch-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .compare-cards,
  .batch-summary {
    grid-template-columns: 1fr;
  }
}
</style>
