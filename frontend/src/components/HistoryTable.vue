<template>
  <el-table :data="items" v-loading="loading" border @selection-change="$emit('selection-change', $event)">
    <el-table-column type="selection" width="46" />
    <el-table-column prop="name" label="测试名称" min-width="190" show-overflow-tooltip />
    <el-table-column label="协议" width="150">
      <template #default="{ row }">{{ protocolText(row.api_protocol) }}</template>
    </el-table-column>
    <el-table-column prop="model" label="模型" min-width="120" show-overflow-tooltip />
    <el-table-column prop="status" label="状态" width="110">
      <template #default="{ row }">
        <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="concurrency" label="并发" width="90" />
    <el-table-column prop="input_tokens" label="输入 Token" width="120" />
    <el-table-column label="成功率" width="110">
      <template #default="{ row }">{{ percent(row.summary?.results?.success_rate) }}</template>
    </el-table-column>
    <el-table-column label="TPM" width="130">
      <template #default="{ row }">{{ number(row.summary?.results?.total_tpm) }}</template>
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
</template>

<script setup>
import { CopyDocument, DataAnalysis, Delete, Monitor, MoreFilled } from '@element-plus/icons-vue'

defineProps({
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

function protocolText(protocol) {
  if (protocol === 'anthropic') return 'Anthropic'
  if (protocol === 'gemini') return 'Gemini'
  return 'OpenAI-compatible'
}

function handleCommand(command, row) {
  emit(command, row)
}

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
</style>
