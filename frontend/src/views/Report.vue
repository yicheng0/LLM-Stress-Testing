<template>
  <div v-loading="loading">
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">报告概览</h2>
        <div class="toolbar">
          <el-button :icon="Monitor" @click="router.push(`/tests/${id}/run`)">运行页</el-button>
          <el-button :icon="CopyDocument" @click="copyRerun">复制配置</el-button>
          <el-button :icon="Delete" type="danger" plain @click="confirmDeleteReport">删除本次数据</el-button>
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
          <el-descriptions-item label="输入 Token 目标">{{ isMatrix ? '-' : number(config.input_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="最大输出 Token">{{ number(config.max_output_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="测试点">{{ isMatrix ? summary.test_points : '-' }}</el-descriptions-item>
          <el-descriptions-item label="Base URL" :span="2">{{ config.base_url || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Endpoint" :span="2">{{ config.endpoint || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <div class="section" v-if="report">
      <div class="section-header">
        <h2 class="section-title">测试结论</h2>
        <el-tag :type="reportConclusion.type" effect="plain">{{ reportConclusion.label }}</el-tag>
      </div>
      <div class="section-body">
        <el-alert
          v-if="hasAuthFailure"
          class="report-alert"
          title="认证失败 / API Key 无效"
          description="本次结果中存在 401/403 响应，说明密钥、权限或接入域名存在问题；请先修正认证后再参考吞吐和容量建议。"
          type="error"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="hasInvalidResponse"
          class="report-alert"
          title="响应格式异常"
          description="本次结果中存在 HTTP 2xx 但无法识别为模型输出的响应；请检查协议类型、Endpoint、接入域名或代理网关返回内容。"
          type="error"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="!config.enable_stream"
          class="report-alert"
          title="非流式模式下 TTFT / Decode 无法准确测量"
          description="当前响应只能在完整返回后计时，首 token 到达时间和逐 token 解码耗时缺少真实观测点；请优先依据总延迟、吞吐和错误分布判断容量，若需要 TTFT 诊断请开启流式模式复测。"
          type="warning"
          show-icon
          :closable="false"
        />
        <div class="conclusion-grid">
          <div v-for="item in conclusionItems" :key="item.label" class="conclusion-card" :class="item.type">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <em>{{ item.hint }}</em>
          </div>
        </div>
        <div class="conclusion-list">
          <el-alert
            v-for="item in conclusionAdvice"
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

    <div class="grid-2 report-grid" v-if="report">
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">容量推荐</h2>
          <el-tag :type="capacityRecommendation.type" effect="plain">{{ capacityRecommendation.label }}</el-tag>
        </div>
        <div class="section-body">
          <div class="recommendation-grid">
            <div v-for="item in capacityCards" :key="item.label" class="recommendation-card" :class="item.type">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <em>{{ item.description }}</em>
            </div>
          </div>
          <el-alert
            class="report-alert"
            :title="capacityRecommendation.title"
            :description="capacityRecommendation.description"
            :type="capacityRecommendation.type"
            show-icon
            :closable="false"
          />
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <h2 class="section-title">客户版摘要</h2>
          <el-button :icon="CopyDocument" @click="copyCustomerSummary">复制摘要</el-button>
        </div>
        <div class="section-body">
          <div class="customer-summary">
            <p v-for="line in customerSummaryLines" :key="line">{{ line }}</p>
          </div>
        </div>
      </div>
    </div>

    <div class="grid-2 report-grid" v-if="report">
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">敏感信息审计</h2>
          <el-tag :type="securityAudit.statusType" effect="plain">{{ securityAudit.status }}</el-tag>
        </div>
        <div class="section-body">
          <div class="audit-list">
            <div v-for="item in securityAudit.items" :key="item.label" class="audit-item" :class="item.type">
              <strong>{{ item.label }}</strong>
              <span>{{ item.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <h2 class="section-title">数据保留策略</h2>
          <el-tag :type="retentionInfo.type" effect="plain">{{ retentionInfo.label }}</el-tag>
        </div>
        <div class="section-body">
          <div class="retention-panel">
            <div>
              <span>保留时长</span>
              <strong>{{ retentionHoursText }}</strong>
            </div>
            <div>
              <span>完成时间</span>
              <strong>{{ report?.completed_at ? formatTime(report.completed_at) : '-' }}</strong>
            </div>
            <div>
              <span>预计过期</span>
              <strong>{{ report?.expires_at ? formatTime(report.expires_at) : '-' }}</strong>
            </div>
          </div>
          <el-alert
            class="report-alert"
            title="报告、明细和事件只用于本次测试诊断"
            :description="retentionInfo.description"
            type="info"
            show-icon
            :closable="false"
          />
        </div>
      </div>
    </div>

    <template v-if="isMatrix">
      <MetricCards :items="matrixMetricItems" />
      <ChartPanel title="矩阵结果热力图" :option="matrixHeatmapOption">
        <template #actions>
          <el-select v-model="matrixHeatmapMetric" class="metric-select" size="small">
            <el-option
              v-for="item in matrixHeatmapMetrics"
              :key="item.field"
              :label="item.label"
              :value="item.field"
            />
          </el-select>
        </template>
      </ChartPanel>
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
            <el-table-column prop="input_tokens" label="输入 Token 目标" />
            <el-table-column prop="concurrency" label="并发" />
            <el-table-column prop="rpm" label="RPM" />
            <el-table-column prop="total_tps" label="TPS" />
            <el-table-column prop="total_tpm" label="TPM" />
            <el-table-column label="成功率">
              <template #default="{ row }">{{ percent(row.success_rate) }}</template>
            </el-table-column>
            <el-table-column label="耗时 Avg">
              <template #default="{ row }">{{ seconds(row.latency_avg) }}</template>
            </el-table-column>
            <el-table-column label="耗时 P50">
              <template #default="{ row }">{{ seconds(row.latency_p50) }}</template>
            </el-table-column>
            <el-table-column label="耗时 P99">
              <template #default="{ row }">{{ seconds(row.latency_p99) }}</template>
            </el-table-column>
            <el-table-column label="TTFT Avg">
              <template #default="{ row }">{{ seconds(row.ttft_avg) }}</template>
            </el-table-column>
            <el-table-column label="TTFT P50">
              <template #default="{ row }">{{ seconds(row.ttft_p50) }}</template>
            </el-table-column>
            <el-table-column label="TTFT P99">
              <template #default="{ row }">{{ seconds(row.ttft_p99) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </template>

    <template v-else>
      <MetricCards :items="metricItems" />

      <div v-if="hasExpectedMetrics" class="section">
        <div class="section-header">
          <h2 class="section-title">预期 vs 实测</h2>
          <el-tag :type="expectationStatus.type" effect="plain">{{ expectationStatus.label }}</el-tag>
        </div>
        <div class="section-body">
          <div class="expectation-grid">
            <div v-for="item in expectationCards" :key="item.label" class="expectation-card" :class="item.type">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <em>{{ item.description }}</em>
            </div>
          </div>
          <div class="expectation-list">
            <el-alert
              v-for="item in expectationAdvice"
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

      <div class="section">
        <div class="section-header">
          <h2 class="section-title">容量与性能诊断</h2>
          <el-tag :type="diagnosticStatus.type" effect="plain">{{ diagnosticStatus.label }}</el-tag>
        </div>
        <div class="section-body">
          <div class="diagnostic-grid">
            <div v-for="item in diagnosticCards" :key="item.label" class="diagnostic-card" :class="item.type">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <em>{{ item.description }}</em>
            </div>
          </div>
        </div>
      </div>

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
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CopyDocument, Delete, Download, Monitor, Refresh } from '@element-plus/icons-vue'
import ChartPanel from '../components/ChartPanel.vue'
import MetricCards from '../components/MetricCards.vue'
import MetricsTable from '../components/MetricsTable.vue'
import { deleteTest, downloadUrl, getDetails, getReport } from '../api/client'

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
const matrixHeatmapMetric = ref('total_tpm')
const matrixHeatmapMetrics = [
  { field: 'total_tpm', label: 'TPM', kind: 'throughput' },
  { field: 'rpm', label: 'RPM', kind: 'throughput' },
  { field: 'total_tps', label: 'TPS', kind: 'throughput' },
  { field: 'ttft_avg', label: 'TTFT Average', kind: 'latency' },
  { field: 'ttft_p50', label: 'TTFT P50', kind: 'latency' },
  { field: 'ttft_p99', label: 'TTFT P99', kind: 'latency' },
  { field: 'latency_avg', label: '耗时 Average', kind: 'latency' },
  { field: 'latency_p50', label: '耗时 P50', kind: 'latency' },
  { field: 'latency_p99', label: '耗时 P99', kind: 'latency' }
]

const summary = computed(() => report.value?.summary || {})
const config = computed(() => report.value?.config || summary.value?.config || {})
const results = computed(() => summary.value?.results || {})
const charts = computed(() => report.value?.charts || {})
const isMatrix = computed(() => Boolean(summary.value?.matrix))
const matrixPoints = computed(() => charts.value.matrix_points || [])
const effectiveDuration = computed(() => config.value.matrix_mode ? config.value.matrix_duration_sec : config.value.duration_sec)
const expectedMetrics = computed(() => config.value.expected_metrics || summary.value?.config?.expected_metrics || null)
const hasExpectedMetrics = computed(() => !isMatrix.value && Boolean(expectedMetrics.value?.expected_rpm || expectedMetrics.value?.expected_tpm))
const resultErrorCounts = computed(() => {
  if (!isMatrix.value) return results.value.error_counts || {}
  const merged = {}
  const points = summary.value.results_matrix || []
  points.forEach((point) => {
    Object.entries(point.results?.error_counts || {}).forEach(([key, value]) => {
      merged[key] = (merged[key] || 0) + Number(value || 0)
    })
  })
  return merged
})
const hasAuthFailure = computed(() => Number(resultErrorCounts.value.HTTP_401 || 0) > 0 || Number(resultErrorCounts.value.HTTP_403 || 0) > 0)
const hasInvalidResponse = computed(() => Number(resultErrorCounts.value.INVALID_RESPONSE || 0) > 0)
const stableMatrixPoints = computed(() => matrixPoints.value.filter((item) => (
  Number(item.success_rate || 0) >= 0.99 && Number(item.latency_p95 || 0) > 0
)))
const bestStableMatrixPoint = computed(() => {
  const candidates = stableMatrixPoints.value.length ? stableMatrixPoints.value : matrixPoints.value
  return [...candidates].sort((a, b) => Number(b.total_tpm || 0) - Number(a.total_tpm || 0))[0] || null
})
const capacityRecommendation = computed(() => {
  if (hasAuthFailure.value) {
    return {
      label: '认证失败',
      title: '当前结果不能作为容量参考',
      description: '本次测试存在 401/403，先修正 API Key、权限或接入域名，再重新测试。',
      type: 'danger'
    }
  }
  if (hasInvalidResponse.value) {
    return {
      label: '响应异常',
      title: '当前结果不能作为容量参考',
      description: '本次测试存在 HTTP 2xx 但响应格式异常的记录，先修正协议、Endpoint 或网关返回内容后再重新测试。',
      type: 'danger'
    }
  }
  if (isMatrix.value) {
    const point = bestStableMatrixPoint.value
    if (!point) {
      return {
        label: '暂无建议',
        title: '缺少矩阵测试点',
        description: '矩阵结果为空，无法给出容量基线。',
        type: 'info'
      }
    }
    const stable = stableMatrixPoints.value.includes(point)
    return {
      label: stable ? '可作为基线' : '需降压复测',
      title: stable ? '推荐使用最佳稳定点作为容量基线' : '最高吞吐点稳定性不足',
      description: stable
        ? `建议以 ${number(point.input_tokens)} 输入 Token 目标、${number(point.concurrency)} 并发作为当前模型容量基线，约 ${number(point.rpm)} RPM / ${number(point.total_tpm)} TPM。`
        : `当前矩阵没有达到 99% 成功率且 P95 可参考的稳定点，建议降低并发或缩短输入 Token 目标后复测。`,
      type: stable ? 'success' : 'warning'
    }
  }
  const successRate = Number(results.value.success_rate || 0)
  const p95 = Number(results.value.latency_sec_p95 || 0)
  const failed = Number(results.value.failed_requests || 0)
  if (successRate < 0.95 || failed > 0 && successRate < 0.98) {
    return {
      label: '不建议参考',
      title: '本次容量结果不适合作为生产参考',
      description: '成功率偏低，优先排查限流、认证、超时或服务端错误；建议降并发复测后再给容量口径。',
      type: 'danger'
    }
  }
  if (successRate < 0.99 || p95 >= 10) {
    return {
      label: '需降压',
      title: '建议降低目标压力后作为基线',
      description: `可先按当前实测的 70% 作为保守目标，即约 ${number(safeRpm.value)} RPM / ${number(safeTpm.value)} TPM，再逐步上探。`,
      type: 'warning'
    }
  }
  return {
    label: '可作为基线',
    title: '当前结果可作为小流量容量基线',
    description: `建议以约 ${number(safeRpm.value)} RPM / ${number(safeTpm.value)} TPM 作为保守起点，并通过矩阵测试继续确认边界。`,
    type: 'success'
  }
})
const safeRpm = computed(() => Number(results.value.rpm || 0) * 0.8)
const safeTpm = computed(() => Number(results.value.total_tpm || 0) * 0.8)
const capacityCards = computed(() => {
  if (isMatrix.value) {
    const point = bestStableMatrixPoint.value
    return [
      { label: '推荐并发', value: number(point?.concurrency), description: `输入 Token 目标 ${number(point?.input_tokens)}`, type: capacityRecommendation.value.type },
      { label: '推荐 RPM', value: number(point?.rpm), description: '优先选择稳定点，不只看峰值', type: 'ok' },
      { label: '推荐 TPM', value: number(point?.total_tpm), description: `成功率 ${percent(point?.success_rate)}`, type: 'ok' },
      { label: '尾延迟 P95', value: seconds(point?.latency_p95), description: '作为容量口径的延迟参考', type: Number(point?.latency_p95 || 0) >= 10 ? 'warning' : 'ok' }
    ]
  }
  return [
    { label: '保守 RPM', value: number(safeRpm.value), description: `实测 ${number(results.value.rpm)} 的 80%`, type: capacityRecommendation.value.type },
    { label: '保守 TPM', value: number(safeTpm.value), description: `实测 ${number(results.value.total_tpm)} 的 80%`, type: capacityRecommendation.value.type },
    { label: '建议并发', value: number(Math.max(1, Math.floor(Number(config.value.concurrency || 1) * 0.8))), description: `本次并发 ${number(config.value.concurrency)}`, type: 'ok' },
    { label: '稳定性', value: percent(results.value.success_rate), description: `P95 ${seconds(results.value.latency_sec_p95)}`, type: Number(results.value.success_rate || 0) >= 0.99 ? 'ok' : 'warning' }
  ]
})
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
const securityAudit = computed(() => {
  const serialized = JSON.stringify({
    config: config.value,
    events: report.value?.events || [],
    summary: summary.value
  })
  const suspicious = /sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|x-api-key["'\s:]+[A-Za-z0-9._-]{12,}/i.test(serialized)
  return {
    status: suspicious ? '需复核' : '已脱敏',
    statusType: suspicious ? 'warning' : 'success',
    items: [
      {
        label: 'API Key',
        description: suspicious ? '检测到疑似密钥片段，请复核导出文件和事件文本。' : '报告配置中不展示 API Key，复跑配置也会移除密钥。',
        type: suspicious ? 'warning' : 'ok'
      },
      {
        label: '事件与明细',
        description: '后端写入结果前会对 Bearer Token、x-api-key 和常见 key 字段做脱敏处理。',
        type: 'ok'
      },
      {
        label: '导出文件',
        description: 'HTML、Markdown、Summary 和 Details 仅保留诊断需要的配置、指标和错误摘要。',
        type: 'ok'
      }
    ]
  }
})
const retentionHoursText = computed(() => {
  const hours = Number(report.value?.retention_hours)
  if (!Number.isFinite(hours)) return '-'
  if (hours <= 0) return '完成后立即可清理'
  if (hours % 24 === 0) return `${hours / 24} 天`
  return `${hours} 小时`
})
const retentionInfo = computed(() => {
  if (!report.value?.expires_at) {
    return {
      label: '等待完成',
      type: 'info',
      description: '任务完成后会根据后端 RESULT_RETENTION_HOURS 计算过期时间。'
    }
  }
  const expired = new Date(report.value.expires_at).getTime() <= Date.now()
  return {
    label: expired ? '已过期' : '保留中',
    type: expired ? 'warning' : 'success',
    description: expired
      ? '这条数据已超过保留时间，可在历史记录页执行清理过期。'
      : `到期后可通过历史记录页的清理过期按钮删除报告、明细和相关文件。`
  }
})
const customerSummaryLines = computed(() => {
  if (isMatrix.value) {
    const point = bestStableMatrixPoint.value
    return [
      `测试目的：评估 ${config.value.model || '-'} 在不同输入 Token 目标和并发组合下的容量边界。`,
      `测试配置：矩阵测试共 ${number(summary.value.test_points)} 个测试点，流式模式${config.value.enable_stream ? '开启' : '关闭'}。`,
      `核心结果：推荐稳定点为 ${number(point?.input_tokens)} 输入 Token 目标 / ${number(point?.concurrency)} 并发，约 ${number(point?.rpm)} RPM / ${number(point?.total_tpm)} TPM。`,
      `瓶颈判断：${capacityRecommendation.value.title}。`,
      `建议动作：以稳定点作为基线，继续围绕更高并发或更长上下文做小步复测。`,
      `风险提示：结果仅代表本次网络、账号配额和模型版本条件下的观测值。`
    ]
  }
  return [
    `测试目的：评估 ${config.value.model || '-'} 在 ${number(config.value.concurrency)} 并发、${number(config.value.input_tokens)} 输入 Token 目标下的吞吐和延迟表现。`,
    `测试配置：持续 ${number(effectiveDuration.value)} 秒，流式模式${config.value.enable_stream ? '开启' : '关闭'}，最大输出 ${number(config.value.max_output_tokens)} Token。`,
    `核心结果：成功率 ${percent(results.value.success_rate)}，实测 ${number(results.value.rpm)} RPM / ${number(results.value.total_tpm)} TPM，P95 延迟 ${seconds(results.value.latency_sec_p95)}。`,
    `瓶颈判断：${bottleneckText.value}；${capacityRecommendation.value.title}。`,
    `建议动作：保守容量可先按 ${number(safeRpm.value)} RPM / ${number(safeTpm.value)} TPM 作为起点。`,
    `风险提示：真实线上容量会受限流、网络、输出长度和模型版本变化影响。`
  ]
})

const rpmAchievement = computed(() => achievementRatio(results.value.rpm, expectedMetrics.value?.expected_rpm))
const tpmAchievement = computed(() => achievementRatio(results.value.total_tpm, expectedMetrics.value?.expected_tpm))
const tpsAchievement = computed(() => achievementRatio(results.value.total_tps, expectedMetrics.value?.expected_tps))
const expectationStatus = computed(() => {
  const ratios = [rpmAchievement.value, tpmAchievement.value].filter((item) => item !== null)
  if (!ratios.length) return { label: '缺少预期', type: 'info' }
  const minRatio = Math.min(...ratios)
  if (minRatio >= 0.9) return { label: '达到预期', type: 'success' }
  if (minRatio >= 0.6) return { label: '部分达成', type: 'warning' }
  return { label: '明显偏低', type: 'danger' }
})
const expectationCards = computed(() => [
  {
    label: 'RPM 达成率',
    value: percentRatio(rpmAchievement.value),
    description: `预期 ${number(expectedMetrics.value?.expected_rpm)} / 实测 ${number(results.value.rpm)}`,
    type: expectationType(rpmAchievement.value)
  },
  {
    label: 'TPM 达成率',
    value: percentRatio(tpmAchievement.value),
    description: `预期 ${number(expectedMetrics.value?.expected_tpm)} / 实测 ${number(results.value.total_tpm)}`,
    type: expectationType(tpmAchievement.value)
  },
  {
    label: 'TPS 达成率',
    value: percentRatio(tpsAchievement.value),
    description: `预期 ${number(expectedMetrics.value?.expected_tps)} / 实测 ${number(results.value.total_tps)}`,
    type: expectationType(tpsAchievement.value)
  },
  {
    label: '预计消耗',
    value: compactNumber(expectedMetrics.value?.expected_total_tokens),
    description: `${number(expectedMetrics.value?.expected_requests)} 请求 / 输入 ${compactNumber(expectedMetrics.value?.expected_input_token_total)} / 输出上限 ${compactNumber(expectedMetrics.value?.expected_output_token_limit)}`,
    type: 'ok'
  }
])
const expectationAdvice = computed(() => {
  const items = []
  const minRatio = Math.min(...[rpmAchievement.value, tpmAchievement.value].filter((item) => item !== null), 1)
  const successRate = Number(results.value.success_rate || 0)
  const p95 = Number(results.value.latency_sec_p95 || 0)
  const avgLatency = Number(results.value.latency_sec_avg || 0)
  const expectedLatency = Number(expectedMetrics.value?.expected_latency_sec || 0)
  if (successRate < 0.99) {
    items.push({
      title: '成功率拉低了吞吐达成率',
      description: '先看错误分布和请求明细，常见原因是限流、超时、认证失败或 5xx。',
      type: 'warning'
    })
  }
  if (expectedLatency && avgLatency > expectedLatency * 1.5) {
    items.push({
      title: '平均耗时假设偏乐观',
      description: `启动前按 ${number(expectedLatency)}s 估算，实测平均 ${seconds(avgLatency)}，因此 RPM/TPM 会低于预期。`,
      type: 'warning'
    })
  }
  if (p95 >= 10) {
    items.push({
      title: '尾延迟偏高',
      description: 'P95/P99 偏高通常代表排队、模型响应慢或网络抖动，建议降低并发或拆分长上下文测试。',
      type: 'warning'
    })
  }
  if (config.value.enable_stream && bottleneckText.value === 'Prefill / 排队') {
    items.push({
      title: 'TTFT 偏高，优先排查排队或输入预填充',
      description: '长输入、高并发或服务端排队都会让首 token 变慢，进而降低请求吞吐。',
      type: 'info'
    })
  }
  if (config.value.enable_stream && bottleneckText.value === 'Decode') {
    items.push({
      title: 'Decode 占比较高，可能受输出生成速度限制',
      description: '可以降低最大输出 Token 或单独测试输出长度对吞吐的影响。',
      type: 'info'
    })
  }
  if (!items.length && minRatio >= 0.9) {
    items.push({
      title: '本次测试基本达到启动前预期',
      description: '可以把当前配置作为基线，再通过矩阵测试探索更高并发或更长上下文。',
      type: 'success'
    })
  }
  if (!items.length) {
    items.push({
      title: '结果低于预期但没有明显错误',
      description: '通常是平均耗时假设过低、服务端限速或模型实际生成速度不足导致。',
      type: 'info'
    })
  }
  return items
})

const diagnosticStatus = computed(() => {
  if (Number(results.value.failed_requests || 0) > 0 || Number(results.value.success_rate || 1) < 0.99) {
    return { label: '先排查错误', type: 'warning' }
  }
  if (bottleneckText.value !== '-' && bottleneckText.value !== '混合瓶颈') {
    return { label: `${bottleneckText.value} 受限`, type: 'warning' }
  }
  return { label: '指标均衡', type: 'success' }
})

const diagnosticCards = computed(() => {
  const errorCounts = isMatrix.value ? resultErrorCounts.value : (charts.value.error_counts || {})
  const topError = Object.entries(errorCounts).sort((a, b) => Number(b[1]) - Number(a[1]))[0]
  return [
    {
      label: '吞吐上限',
      value: `TPM ${number(results.value.total_tpm)}`,
      description: `RPM ${number(results.value.rpm)} / TPS ${number(results.value.total_tps)}`,
      type: 'ok'
    },
    {
      label: '延迟瓶颈',
      value: bottleneckText.value,
      description: `Avg ${seconds(results.value.latency_sec_avg)} / P95 ${seconds(results.value.latency_sec_p95)}`,
      type: Number(results.value.latency_sec_p95 || 0) >= 10 ? 'warning' : 'ok'
    },
    {
      label: '错误分布',
      value: topError ? `${topError[0]} x ${number(topError[1])}` : '无错误',
      description: `失败 ${number(results.value.failed_requests)} / 成功率 ${percent(results.value.success_rate)}`,
      type: topError ? 'warning' : 'ok'
    },
    {
      label: 'TTFT / Decode',
      value: config.value.enable_stream ? `${seconds(results.value.ttft_sec_avg)} / ${seconds(results.value.decode_sec_avg)}` : '不可准确测量',
      description: config.value.enable_stream ? ttftDecodeDescription.value : '非流式响应缺少首 token 到达事件',
      type: config.value.enable_stream ? 'ok' : 'warning'
    }
  ]
})

const matrixMetricItems = computed(() => {
  const bestTpm = Math.max(0, ...matrixPoints.value.map(item => Number(item.total_tpm || 0)))
  const bestRpm = Math.max(0, ...matrixPoints.value.map(item => Number(item.rpm || 0)))
  const minP95 = Math.min(...matrixPoints.value.map(item => Number(item.latency_p95 || Infinity)))
  return [
    { label: '测试点', value: number(summary.value.test_points), sub: '输入 Token 目标 x 并发', color: '#2563eb' },
    { label: '最高 TPM', value: number(bestTpm), sub: '矩阵峰值', color: '#f97316' },
    { label: '最高 RPM', value: number(bestRpm), sub: '矩阵峰值', color: '#16a34a' },
    { label: '最低 P95', value: minP95 === Infinity ? '-' : seconds(minP95), sub: '延迟最优点', color: '#334155' }
  ]
})

const reportConclusion = computed(() => {
  if (hasAuthFailure.value) return { label: '认证失败', type: 'danger' }
  if (isMatrix.value) return matrixConclusion.value
  const successRate = Number(results.value.success_rate || 0)
  const p95 = Number(results.value.latency_sec_p95 || 0)
  if (successRate < 0.95) return { label: '不稳定', type: 'danger' }
  if (successRate < 0.99 || p95 >= 10) return { label: '需要优化', type: 'warning' }
  return { label: '表现稳定', type: 'success' }
})
const matrixConclusion = computed(() => {
  const successRates = matrixPoints.value.map((item) => Number(item.success_rate || 0))
  const minSuccess = Math.min(...successRates, 1)
  const p95Values = matrixPoints.value.map((item) => Number(item.latency_p95 || 0)).filter(Boolean)
  const maxP95 = Math.max(...p95Values, 0)
  if (minSuccess < 0.95) return { label: '部分测试点不稳定', type: 'danger' }
  if (minSuccess < 0.99 || maxP95 >= 10) return { label: '存在优化空间', type: 'warning' }
  return { label: '矩阵表现稳定', type: 'success' }
})
const conclusionItems = computed(() => {
  if (isMatrix.value) {
    const bestTpmPoint = [...matrixPoints.value].sort((a, b) => Number(b.total_tpm || 0) - Number(a.total_tpm || 0))[0]
    const bestLatencyPoint = [...matrixPoints.value]
      .filter((item) => item.latency_p95 !== undefined && item.latency_p95 !== null)
      .sort((a, b) => Number(a.latency_p95 || Infinity) - Number(b.latency_p95 || Infinity))[0]
    return [
      { label: '最佳吞吐点', value: bestTpmPoint ? `${number(bestTpmPoint.input_tokens)} / ${number(bestTpmPoint.concurrency)}` : '-', hint: `TPM ${number(bestTpmPoint?.total_tpm)}`, type: 'ok' },
      { label: '最低 P95 点', value: bestLatencyPoint ? `${number(bestLatencyPoint.input_tokens)} / ${number(bestLatencyPoint.concurrency)}` : '-', hint: seconds(bestLatencyPoint?.latency_p95), type: 'ok' },
      { label: '测试点数', value: number(summary.value.test_points), hint: '矩阵组合数量', type: 'ok' },
      { label: '结论', value: reportConclusion.value.label, hint: '综合成功率和尾延迟', type: reportConclusion.value.type }
    ]
  }
  return [
    { label: '稳定性', value: percent(results.value.success_rate), hint: `失败 ${number(results.value.failed_requests)}`, type: Number(results.value.success_rate || 0) >= 0.99 ? 'ok' : 'warning' },
    { label: '尾延迟', value: seconds(results.value.latency_sec_p95), hint: `P99 ${seconds(results.value.latency_sec_p99)}`, type: Number(results.value.latency_sec_p95 || 0) >= 10 ? 'warning' : 'ok' },
    { label: '吞吐', value: number(results.value.total_tpm), hint: `RPM ${number(results.value.rpm)}`, type: 'ok' },
    { label: '瓶颈判断', value: bottleneckText.value, hint: '由 TTFT/Decode 占比估算', type: 'ok' }
  ]
})
const bottleneckText = computed(() => {
  const latency = Number(results.value.latency_sec_avg || 0)
  const ttft = Number(results.value.ttft_sec_avg || 0)
  const decode = Number(results.value.decode_sec_avg || 0)
  if (!config.value.enable_stream) return 'TTFT 不可测'
  if (!latency) return '-'
  if (ttft / latency >= 0.55) return 'Prefill / 排队'
  if (decode / latency >= 0.55) return 'Decode'
  return '混合瓶颈'
})
const ttftDecodeDescription = computed(() => {
  const latency = Number(results.value.latency_sec_avg || 0)
  const ttft = Number(results.value.ttft_sec_avg || 0)
  const decode = Number(results.value.decode_sec_avg || 0)
  if (!latency) return '缺少有效延迟样本'
  return `TTFT ${percent(ttft / latency)} / Decode ${percent(decode / latency)}`
})
const conclusionAdvice = computed(() => {
  const items = []
  if (hasAuthFailure.value) {
    items.push({
      title: '认证失败',
      description: '本次结果里出现 401/403，请先修正 API Key 和权限，再重新压测。',
      type: 'error'
    })
    return items
  }
  if (isMatrix.value) {
    const unstable = matrixPoints.value.filter((item) => Number(item.success_rate || 0) < 0.99)
    if (unstable.length) {
      items.push({
        title: '矩阵中存在成功率偏低的测试点',
        description: '建议重点对比这些测试点的并发、输入 Token 目标和错误分布，确认是限流还是模型容量不足。',
        type: 'warning'
      })
    }
    items.push({
      title: '优先选择稳定吞吐点作为容量基线',
      description: '不要只看最高 TPM，建议同时要求成功率接近 99% 且 P95/P99 可接受。',
      type: 'info'
    })
    return items
  }
  if (Number(results.value.success_rate || 0) < 0.99) {
    items.push({
      title: '成功率未达到 99%',
      description: '建议查看错误分布和请求明细，优先排查限流、认证、超时和 5xx。',
      type: 'warning'
    })
  }
  if (Number(results.value.latency_sec_p95 || 0) >= 10) {
    items.push({
      title: 'P95 延迟偏高',
      description: '建议结合 TTFT / Decode 图判断是输入预填充、输出解码还是队列等待导致。',
      type: 'warning'
    })
  }
  if (!config.value.enable_stream) {
    items.push({
      title: 'TTFT / Decode 诊断受限',
      description: '非流式模式无法准确测量首 token 和解码阶段耗时，容量判断请以总延迟、吞吐和错误为主。',
      type: 'warning'
    })
  }
  if (!items.length) {
    items.push({
      title: '本次测试结果较稳定',
      description: '可以将当前并发和 Token 配置作为基线，再通过矩阵测试探索容量边界。',
      type: 'success'
    })
  }
  return items
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
  const counts = isMatrix.value ? resultErrorCounts.value : (charts.value.error_counts || {})
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
const selectedHeatmapMetric = computed(() => (
  matrixHeatmapMetrics.find((item) => item.field === matrixHeatmapMetric.value) || matrixHeatmapMetrics[0]
))
const matrixHeatmapOption = computed(() => {
  const inputs = uniqueSorted(matrixPoints.value.map((item) => item.input_tokens))
  const concurrency = uniqueSorted(matrixPoints.value.map((item) => item.concurrency))
  const metric = selectedHeatmapMetric.value
  const values = matrixPoints.value
    .map((item) => Number(item[metric.field]))
    .filter((item) => Number.isFinite(item))
  const max = Math.max(1, ...values)
  const pointMap = new Map(matrixPoints.value.map((item) => [
    `${Number(item.input_tokens)}:${Number(item.concurrency)}`,
    item
  ]))
  const data = []
  inputs.forEach((inputTokens, yIndex) => {
    concurrency.forEach((concurrencyValue, xIndex) => {
      const point = pointMap.get(`${inputTokens}:${concurrencyValue}`)
      const value = point ? Number(point[metric.field]) : null
      data.push([
        xIndex,
        yIndex,
        Number.isFinite(value) ? value : null,
        point || { input_tokens: inputTokens, concurrency: concurrencyValue }
      ])
    })
  })
  const colors = metric.kind === 'latency'
    ? ['#dcfce7', '#facc15', '#dc2626']
    : ['#eff6ff', '#93c5fd', '#16a34a']

  return {
    tooltip: {
      position: 'top',
      formatter(params) {
        const point = params.data?.[3] || {}
        const value = params.data?.[2]
        return [
          `${number(point.input_tokens)} Token / ${number(point.concurrency)} 并发`,
          `${metric.label}: ${formatMetricValue(value, metric.field)}`,
          `TPM: ${number(point.total_tpm)}`,
          `RPM: ${number(point.rpm)}`,
          `TPS: ${number(point.total_tps)}`,
          `成功率: ${percent(point.success_rate)}`,
          `TTFT Avg/P50/P99: ${seconds(point.ttft_avg)} / ${seconds(point.ttft_p50)} / ${seconds(point.ttft_p99)}`,
          `耗时 Avg/P50/P99: ${seconds(point.latency_avg)} / ${seconds(point.latency_p50)} / ${seconds(point.latency_p99)}`
        ].join('<br/>')
      }
    },
    grid: { left: 86, right: 28, top: 24, bottom: 74 },
    xAxis: {
      type: 'category',
      name: '并发',
      nameLocation: 'middle',
      nameGap: 44,
      data: concurrency.map((item) => String(item)),
      splitArea: { show: true }
    },
    yAxis: {
      type: 'category',
      name: '输入 Token 目标',
      nameGap: 54,
      data: inputs.map((item) => compactNumber(item)),
      splitArea: { show: true }
    },
    visualMap: {
      min: 0,
      max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 8,
      inRange: { color: colors }
    },
    series: [{
      name: metric.label,
      type: 'heatmap',
      data,
      label: {
        show: true,
        formatter(params) {
          return formatMetricValue(params.data?.[2], metric.field, true)
        }
      },
      itemStyle: {
        borderColor: '#ffffff',
        borderWidth: 2,
        borderRadius: 4
      },
      emphasis: {
        itemStyle: {
          borderColor: '#1d4ed8',
          shadowBlur: 10,
          shadowColor: 'rgba(15, 23, 42, 0.22)'
        }
      }
    }]
  }
})

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

function uniqueSorted(values) {
  return [...new Set(values
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item)))]
    .sort((a, b) => a - b)
}

function formatMetricValue(value, field, compact = false) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  if (field.startsWith('latency_') || field.startsWith('ttft_')) return seconds(value)
  if (compact) return compactNumber(value)
  return number(value)
}

function achievementRatio(actual, expected) {
  const actualValue = Number(actual)
  const expectedValue = Number(expected)
  if (!Number.isFinite(actualValue) || !Number.isFinite(expectedValue) || expectedValue <= 0) return null
  return actualValue / expectedValue
}

function percentRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function expectationType(value) {
  if (value === null || value === undefined) return 'ok'
  if (value >= 0.9) return 'ok'
  if (value >= 0.6) return 'warning'
  return 'danger'
}

function openDownload(kind) {
  if (kind === 'pdf') {
    const url = router.resolve({
      name: 'test-report-print',
      params: { id: props.id },
      query: { autoprint: '1' }
    }).href
    window.open(url, '_blank')
    return
  }
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

async function copyCustomerSummary() {
  try {
    await navigator.clipboard.writeText(customerSummaryLines.value.join('\n'))
    ElMessage.success('已复制客户版摘要')
  } catch {
    ElMessage.error('复制失败，请检查浏览器剪贴板权限')
  }
}

async function confirmDeleteReport() {
  try {
    await ElMessageBox.confirm('确认删除本次测试数据？删除后报告、明细和导出文件将不可恢复。', '删除本次数据', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteTest(props.id)
    ElMessage.success('已删除本次数据')
    router.push('/history')
  } catch (error) {
    ElMessage.error(error.message)
  }
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

.metric-select {
  width: 180px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.report-alert {
  margin-bottom: 14px;
}

.diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.recommendation-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.recommendation-card,
.audit-item {
  min-height: 96px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-left: 3px solid #2563eb;
  border-radius: 8px;
  background: #ffffff;
}

.recommendation-card.warning,
.audit-item.warning {
  border-left-color: #f97316;
  background: #fff7ed;
}

.recommendation-card.danger {
  border-left-color: #dc2626;
  background: #fef2f2;
}

.recommendation-card span,
.recommendation-card em,
.audit-item span {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.recommendation-card strong {
  display: block;
  margin: 7px 0 5px;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 20px;
  line-height: 1.2;
  word-break: break-word;
}

.customer-summary {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #f8fafc;
}

.customer-summary p {
  margin: 0;
  color: #334155;
  font-size: 13px;
  line-height: 1.65;
}

.audit-list {
  display: grid;
  gap: 10px;
}

.audit-item {
  min-height: auto;
}

.audit-item strong {
  display: block;
  margin-bottom: 5px;
  color: #1e293b;
  font-size: 13px;
}

.retention-panel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.retention-panel > div {
  min-height: 78px;
  padding: 13px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.retention-panel span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.retention-panel strong {
  display: block;
  margin-top: 7px;
  color: #1e293b;
  font-size: 15px;
  line-height: 1.35;
}

.expectation-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.expectation-card {
  min-height: 108px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-left: 3px solid #16a34a;
  border-radius: 8px;
  background: #ffffff;
}

.expectation-card.warning {
  border-left-color: #f97316;
  background: #fff7ed;
}

.expectation-card.danger {
  border-left-color: #dc2626;
  background: #fef2f2;
}

.expectation-card span,
.expectation-card em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.expectation-card strong {
  display: block;
  margin: 8px 0 6px;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 22px;
  line-height: 1.2;
  word-break: break-word;
}

.expectation-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.diagnostic-card {
  min-height: 112px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-left: 3px solid #2563eb;
  border-radius: 8px;
  background: #ffffff;
}

.diagnostic-card.warning {
  border-left-color: #f97316;
  background: #fff7ed;
}

.diagnostic-card span,
.diagnostic-card em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.diagnostic-card strong {
  display: block;
  margin: 8px 0 6px;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 18px;
  line-height: 1.25;
  word-break: break-word;
}

@media (max-width: 720px) {
  .metric-select {
    width: 100%;
  }

  .expectation-grid,
  .diagnostic-grid,
  .recommendation-grid,
  .retention-panel {
    grid-template-columns: 1fr;
  }
}
</style>
