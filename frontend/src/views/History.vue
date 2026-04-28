<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">历史记录</h2>
      <div class="toolbar">
        <el-input v-model="store.filters.model" placeholder="模型筛选" clearable style="width: 180px" @keyup.enter="reload" />
        <el-select v-model="store.filters.status" placeholder="状态" clearable style="width: 140px">
          <el-option label="排队" value="queued" />
          <el-option label="运行" value="running" />
          <el-option label="完成" value="completed" />
          <el-option label="失败" value="failed" />
          <el-option label="取消" value="cancelled" />
          <el-option label="中断" value="interrupted" />
        </el-select>
        <el-button :icon="Search" type="primary" @click="reload">筛选</el-button>
      </div>
    </div>
    <div class="section-body">
      <HistoryTable
        :items="store.items"
        :loading="store.loading"
        @run="row => router.push(`/tests/${row.id}/run`)"
        @report="row => router.push(`/tests/${row.id}/report`)"
        @copy="copyRerun"
        @delete="confirmDelete"
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
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import HistoryTable from '../components/HistoryTable.vue'
import { deleteTest } from '../api/client'
import { useTestsStore } from '../stores/tests'

const router = useRouter()
const store = useTestsStore()

function reload() {
  store.page = 1
  store.fetchHistory()
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
</style>
