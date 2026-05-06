<template>
  <div class="history-table-wrap">
    <el-table class="history-desktop-table" :data="items" v-loading="loading" border @selection-change="$emit('selection-change', $event)">
      <el-table-column type="selection" width="46" />
      <el-table-column prop="name" label="测试名称" min-width="190" show-overflow-tooltip />
      <el-table-column label="协议" width="150">
        <template #default="{ row }">{{ protocolText(row.api_protocol) }}</template>
      </el-table-column>
      <el-table-column prop="model" label="模型" min-width="120" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="healthStatusType(row)" effect="plain">{{ healthStatusText(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="concurrency" label="并发" width="90" />
      <el-table-column prop="input_tokens" label="输入 Token" width="120" />
      <el-table-column label="成功率" width="110">
        <template #default="{ row }">{{ percent(summaryResults(row).success_rate) }}</template>
      </el-table-column>
      <el-table-column label="TPM" width="130">
        <template #default="{ row }">{{ number(summaryResults(row).total_tpm) }}</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="结果过期时间" min-width="170">
        <template #default="{ row }">
          <div class="expiry-cell">
            <span>{{ formatExpiry(row) }}</span>
            <el-tag v-if="isExpired(row)" size="small" type="danger" effect="plain">已过期</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" :icon="DataAnalysis" @click="$emit('report', row)">报告</el-button>
          <el-dropdown trigger="click" @command="command => handleCommand(command, row)">
            <el-button size="small" :icon="MoreFilled">更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="run" :icon="Monitor">运行页</el-dropdown-item>
                <el-dropdown-item command="copy" :icon="CopyDocument">复跑</el-dropdown-item>
                <el-dropdown-item command="delete" :icon="Delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <div class="mobile-history-list" :class="{ loading }">
      <article v-for="row in items" :key="row.id" class="mobile-history-card">
        <div class="mobile-card-head">
          <label class="mobile-select">
            <input type="checkbox" :checked="isMobileSelected(row)" @change="toggleMobileSelection(row)" />
            <span>{{ row.name }}</span>
          </label>
          <el-tag :type="healthStatusType(row)" effect="plain">{{ healthStatusText(row) }}</el-tag>
        </div>
        <div class="mobile-card-meta">
          <span>{{ protocolText(row.api_protocol) }}</span>
          <span>{{ row.model || '-' }}</span>
          <span>{{ number(row.concurrency) }} 并发</span>
        </div>
        <div class="mobile-card-metrics">
          <div>
            <span>成功率</span>
            <strong>{{ percent(summaryResults(row).success_rate) }}</strong>
          </div>
          <div>
            <span>TPM</span>
            <strong>{{ number(summaryResults(row).total_tpm) }}</strong>
          </div>
          <div>
            <span>输入 Token</span>
            <strong>{{ number(row.input_tokens) }}</strong>
          </div>
        </div>
        <div class="mobile-card-foot">
          <span>{{ formatTime(row.created_at) }}</span>
          <div>
            <el-button size="small" type="primary" :icon="DataAnalysis" @click="$emit('report', row)">报告</el-button>
            <el-dropdown trigger="click" @command="command => handleCommand(command, row)">
              <el-button size="small" :icon="MoreFilled">更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="run" :icon="Monitor">运行页</el-dropdown-item>
                  <el-dropdown-item command="copy" :icon="CopyDocument">复跑</el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { CopyDocument, DataAnalysis, Delete, Monitor, MoreFilled } from '@element-plus/icons-vue'

const props = defineProps({
  items: {
    type: Array,
    default: () => []
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['run', 'report', 'copy', 'delete', 'selection-change'])
const selectedMobileIds = ref([])

const statusNames = {
  queued: '排队',
  running: '运行',
  stopping: '停止中',
  completed: '完成',
  failed: '失败',
  cancelled: '取消',
  interrupted: '中断'
}

function statusText(status) {
  return statusNames[status] || status
}

function statusType(status) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (['stopping', 'cancelled', 'interrupted'].includes(status)) return 'warning'
  if (status === 'running') return 'primary'
  return 'info'
}

function healthStatusText(row) {
  if (hasAuthError(row)) return '认证失败'
  if (hasInvalidResponse(row)) return '响应异常'
  const results = summaryResults(row)
  if (row.status === 'completed' && Number(results.total_requests || 0) > 0 && Number(results.success_rate || 0) < 0.95) {
    return '异常完成'
  }
  return statusText(row.status)
}

function healthStatusType(row) {
  if (hasAuthError(row)) return 'danger'
  if (hasInvalidResponse(row)) return 'danger'
  const results = summaryResults(row)
  if (row.status === 'completed' && Number(results.total_requests || 0) > 0 && Number(results.success_rate || 0) < 0.95) {
    return 'warning'
  }
  return statusType(row.status)
}

function hasAuthError(row) {
  const errorCounts = summaryResults(row).error_counts || {}
  return Number(errorCounts.HTTP_401 || 0) > 0 || Number(errorCounts.HTTP_403 || 0) > 0
}

function hasInvalidResponse(row) {
  const errorCounts = summaryResults(row).error_counts || {}
  return Number(errorCounts.INVALID_RESPONSE || 0) > 0
}

function summaryResults(row) {
  const summary = row.summary || {}
  if (!summary.matrix) return summary.results || {}
  const points = summary.results_matrix || []
  if (!points.length) return {}
  const mergedErrors = {}
  let totalRequests = 0
  let successfulRequests = 0
  let tpm = 0
  points.forEach((point) => {
    const results = point.results || {}
    totalRequests += Number(results.total_requests || 0)
    successfulRequests += Number(results.successful_requests || 0)
    tpm = Math.max(tpm, Number(results.total_tpm || 0))
    Object.entries(results.error_counts || {}).forEach(([key, value]) => {
      mergedErrors[key] = (mergedErrors[key] || 0) + Number(value || 0)
    })
  })
  return {
    total_requests: totalRequests,
    successful_requests: successfulRequests,
    success_rate: totalRequests ? successfulRequests / totalRequests : null,
    total_tpm: tpm,
    error_counts: mergedErrors
  }
}

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic'
  if (protocol === 'gemini') return 'Gemini'
  return 'OpenAI-compatible'
}

function handleCommand(command, row) {
  emit(command, row)
}

function isMobileSelected(row) {
  return selectedMobileIds.value.includes(row.id)
}

function toggleMobileSelection(row) {
  selectedMobileIds.value = isMobileSelected(row)
    ? selectedMobileIds.value.filter((id) => id !== row.id)
    : [...selectedMobileIds.value, row.id]
  const selectedRows = props.items.filter((item) => selectedMobileIds.value.includes(item.id))
  emit('selection-change', selectedRows)
}

watch(
  () => props.items,
  () => {
    selectedMobileIds.value = selectedMobileIds.value.filter((id) => props.items.some((item) => item.id === id))
  }
)

function percent(value) {
  if (value === undefined || value === null) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function number(value) {
  if (value === undefined || value === null) return '-'
  return Number(value).toLocaleString()
}

function formatExpiry(row) {
  if (row.expires_at) return formatTime(row.expires_at)
  if (row.result_expires_at) return formatTime(row.result_expires_at)
  if (row.completed_at) return `${formatTime(addHours(row.completed_at, 24))}（估算）`
  if (row.created_at) return `${formatTime(addHours(row.created_at, 24))}（估算）`
  return '-'
}

function isExpired(row) {
  const value = row.expires_at || row.result_expires_at
  if (!value) return false
  return new Date(value).getTime() < Date.now()
}

function addHours(value, hours) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  date.setHours(date.getHours() + hours)
  return date
}

function formatTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}
</script>

<style scoped>
.expiry-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mobile-history-list {
  display: none;
}

@media (max-width: 768px) {
  .history-desktop-table {
    display: none;
  }

  .mobile-history-list {
    display: grid;
    gap: 12px;
  }

  .mobile-history-card {
    display: grid;
    gap: 12px;
    padding: 14px;
    border: 1px solid #dfe7f2;
    border-radius: 12px;
    background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
  }

  .mobile-card-head,
  .mobile-card-foot {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
  }

  .mobile-select {
    display: grid;
    grid-template-columns: 22px minmax(0, 1fr);
    gap: 8px;
    min-width: 0;
    color: #1e293b;
    font-size: 14px;
    font-weight: 800;
    line-height: 1.35;
  }

  .mobile-select input {
    width: 18px;
    height: 18px;
    margin: 1px 0 0;
    accent-color: #2563eb;
    cursor: pointer;
  }

  .mobile-select span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    color: #64748b;
    font-size: 12px;
  }

  .mobile-card-meta span {
    padding: 4px 7px;
    border-radius: 999px;
    background: #eef6ff;
  }

  .mobile-card-metrics {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .mobile-card-metrics div {
    min-width: 0;
    padding: 9px;
    border-radius: 10px;
    background: #ffffff;
    box-shadow: inset 0 0 0 1px #e5edf6;
  }

  .mobile-card-metrics span,
  .mobile-card-foot > span {
    display: block;
    color: #64748b;
    font-size: 12px;
  }

  .mobile-card-metrics strong {
    display: block;
    margin-top: 5px;
    overflow: hidden;
    color: #2563eb;
    font-family: "Fira Code", Consolas, monospace;
    font-size: 14px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-card-foot {
    align-items: center;
  }

  .mobile-card-foot > div {
    display: flex;
    gap: 8px;
  }
}

@media (max-width: 420px) {
  .mobile-card-metrics {
    grid-template-columns: 1fr;
  }

  .mobile-card-foot {
    align-items: stretch;
    flex-direction: column;
  }

  .mobile-card-foot > div,
  .mobile-card-foot .el-button,
  .mobile-card-foot .el-dropdown {
    width: 100%;
  }
}
</style>
