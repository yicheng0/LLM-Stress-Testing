<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">历史记录</h2>
      <div class="toolbar">
        <el-input v-model="store.filters.model" placeholder="模型筛选" clearable style="width: 180px" @keyup.enter="reload" />
        <el-select v-model="store.filters.api_protocol" placeholder="协议" clearable style="width: 170px">
          <el-option label="OpenAI-compatible" value="openai" />
          <el-option label="Anthropic" value="anthropic" />
          <el-option label="Gemini" value="gemini" />
        </el-select>
        <el-select v-model="store.filters.status" placeholder="状态" clearable style="width: 140px">
          <el-option label="排队" value="queued" />
          <el-option label="运行" value="running" />
          <el-option label="完成" value="completed" />
          <el-option label="失败" value="failed" />
          <el-option label="取消" value="cancelled" />
          <el-option label="中断" value="interrupted" />
        </el-select>
        <el-date-picker
          v-model="createdRange"
          type="daterange"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 250px"
          @change="syncDateRange"
        />
        <el-button :icon="Search" type="primary" @click="reload">筛选</el-button>
        <el-button :icon="RefreshLeft" @click="resetFilters">重置</el-button>
        <el-button :icon="DataAnalysis" :disabled="!canCompare" @click="goCompare">
          对比 {{ selectedRows.length || '' }}
        </el-button>
        <el-button
          :icon="Delete"
          type="danger"
          plain
          :disabled="!canBulkDelete"
          :loading="bulkDeleting"
          @click="confirmBulkDelete"
        >
          删除选中 {{ selectedRows.length || '' }}
        </el-button>
        <el-dropdown trigger="click" :disabled="!canExport" @command="exportSelectedReport">
          <el-button type="primary" :icon="Download">
            导出报告
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="pdf">PDF 报告</el-dropdown-item>
              <el-dropdown-item command="html">HTML 可视化报告</el-dropdown-item>
              <el-dropdown-item command="markdown">Markdown 报告</el-dropdown-item>
              <el-dropdown-item command="summary">Summary JSON</el-dropdown-item>
              <el-dropdown-item command="details">Details JSONL</el-dropdown-item>
              <el-dropdown-item command="matrix_csv">Matrix CSV</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <div class="section-body">
      <div class="retention-banner">
        <div>
          <strong>结果保留策略</strong>
          <span>{{ retentionSummary }}</span>
        </div>
        <el-tag :type="expiredCount ? 'warning' : 'success'" effect="plain">
          {{ expiredCount ? `${expiredCount} 条已过期` : '当前无过期数据' }}
        </el-tag>
      </div>
      <HistoryTable
        :items="store.items"
        :loading="store.loading"
        @run="row => router.push(`/tests/${row.id}/run`)"
        @report="row => router.push(`/tests/${row.id}/report`)"
        @copy="copyRerun"
        @delete="confirmDelete"
        @selection-change="handleSelectionChange"
      />
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="store.page"
          v-model:page-size="store.pageSize"
          :total="store.total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="store.fetchHistory()"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, DataAnalysis, Delete, Download, RefreshLeft, Search } from '@element-plus/icons-vue'
import HistoryTable from '../components/HistoryTable.vue'
import { deleteTest, deleteTests, downloadUrl } from '../api/client'
import { useTestsStore } from '../stores/tests'

const router = useRouter()
const store = useTestsStore()
const createdRange = ref([])
const selectedRows = ref([])
const bulkDeleting = ref(false)
const canCompare = computed(() => selectedRows.value.length >= 2 && selectedRows.value.length <= 4)
const canExport = computed(() => selectedRows.value.length === 1)
const canBulkDelete = computed(() => selectedRows.value.length > 0)
const expiredCount = computed(() => store.items.filter((item) => isExpired(item)).length)
const retentionSummary = computed(() => {
  const nextExpiry = store.items
    .map((item) => item.expires_at || item.result_expires_at)
    .filter(Boolean)
    .map((value) => new Date(value))
    .filter((value) => Number.isFinite(value.getTime()) && value.getTime() > Date.now())
    .sort((a, b) => a.getTime() - b.getTime())[0]
  if (nextExpiry) {
    return `报告、明细和事件按后端保留策略自动到期；最近一条将在 ${formatTime(nextExpiry)} 过期。`
  }
  return '报告、明细和事件仅用于测试诊断；需要删除时请勾选记录后点击“删除选中”。'
})

function reload() {
  store.page = 1
  store.fetchHistory()
}

function syncDateRange(value) {
  const [from, to] = value || []
  store.filters.created_from = from ? `${from}T00:00:00` : ''
  store.filters.created_to = to ? `${to}T23:59:59` : ''
}

function resetFilters() {
  store.filters.model = ''
  store.filters.status = ''
  store.filters.api_protocol = ''
  store.filters.created_from = ''
  store.filters.created_to = ''
  createdRange.value = []
  reload()
}

async function confirmDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.name}」？`, '删除记录', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteTest(row.id)
    ElMessage.success('已删除')
    store.fetchHistory()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function confirmBulkDelete() {
  const ids = selectedRows.value.map((row) => row.id).filter(Boolean)
  if (!ids.length) {
    ElMessage.warning('请选择要删除的记录')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${ids.length} 条记录？删除后报告、明细、事件和结果文件将不可恢复。`,
      '删除选中记录',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }

  bulkDeleting.value = true
  try {
    const result = await deleteTests(ids)
    selectedRows.value = []
    const deleted = result.deleted || 0
    const notFound = result.not_found?.length || 0
    if (notFound) {
      ElMessage.warning(`已删除 ${deleted} 条，${notFound} 条记录不存在或已被删除`)
    } else {
      ElMessage.success(`已删除 ${deleted} 条记录`)
    }
    await store.fetchHistory()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    bulkDeleting.value = false
  }
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

function copyRerun(row) {
  const copied = {
    name: `${row.name} - 复跑`,
    base_url: row.base_url,
    api_protocol: row.api_protocol || 'openai',
    endpoint: row.endpoint,
    model: row.model,
    concurrency: row.concurrency,
    duration_sec: row.duration_sec,
    input_tokens: row.input_tokens,
    max_output_tokens: row.max_output_tokens,
    enable_stream: row.enable_stream,
    matrix_mode: row.matrix_mode
  }
  sessionStorage.setItem('rerun_config', JSON.stringify(copied))
  router.push('/tests/new')
}

function goCompare() {
  if (!canCompare.value) {
    ElMessage.warning('请选择 2-4 条记录进行对比')
    return
  }
  router.push(`/compare?ids=${selectedRows.value.map((item) => item.id).join(',')}`)
}

function exportSelectedReport(kind) {
  if (!canExport.value) {
    ElMessage.warning('请选择 1 条记录导出报告')
    return
  }
  const row = selectedRows.value[0]
  if (kind === 'pdf') {
    const url = router.resolve({
      name: 'test-report-print',
      params: { id: row.id },
      query: { autoprint: '1' }
    }).href
    window.open(url, '_blank')
    return
  }
  window.open(downloadUrl(row.id, kind), '_blank')
}

function isExpired(row) {
  const value = row.expires_at || row.result_expires_at
  if (!value) return false
  return new Date(value).getTime() <= Date.now()
}

function formatTime(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

onMounted(() => {
  store.fetchHistory()
})
</script>

<style scoped>
.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.retention-banner {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #f8fbff;
}

.retention-banner div {
  display: grid;
  gap: 5px;
}

.retention-banner strong {
  color: #1e293b;
  font-size: 14px;
}

.retention-banner span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 720px) {
  .retention-banner {
    flex-direction: column;
  }
}
</style>
