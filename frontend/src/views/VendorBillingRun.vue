<template>
  <div v-loading="loading" class="section">
    <div class="section-header"><div><h2 class="section-title">供应商接入自测运行中</h2><p class="subtitle">{{ data?.config?.supplier_name || '供应商' }} · {{ data?.config?.model || '-' }}</p></div><el-button v-if="running" type="danger" plain :loading="stopping" @click="stop">停止</el-button></div>
    <div class="section-body">
      <el-progress :percentage="percent" :status="terminal ? 'success' : undefined" />
      <div class="progress-copy"><span>当前输入：{{ progress?.input_tokens || '等待开始' }}</span><span>组进度：{{ progress?.current_index || 0 }} / {{ progress?.total || data?.config?.input_token_lengths?.length || 0 }}</span><span>状态：{{ statusText }}</span></div>
    </div>
    <div v-if="data?.summary" class="section-body"><el-alert :title="`总体结论：${statusLabel(data.summary.status)}`" :type="summaryType(data.summary.status)" :closable="false" show-icon /><div class="submit-row"><el-button type="primary" @click="router.replace(`/tests/vendor-billing/${id}/result`)">查看自测结果</el-button></div></div>
  </div>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getVendorBilling, stopTest } from '../api/client'
const route = useRoute(); const router = useRouter(); const id = route.params.id
const data = ref(null); const loading = ref(true); const stopping = ref(false); let timer = null
const progress = computed(() => data.value?.progress || {})
const terminal = computed(() => ['completed', 'failed', 'cancelled', 'interrupted'].includes(data.value?.task_status))
const running = computed(() => !terminal.value && Boolean(data.value))
const percent = computed(() => { const total = Number(progress.value.total || data.value?.config?.input_token_lengths?.length || 0); const current = Number(progress.value.current_index || 0); return total ? Math.min(100, Math.round(current / total * 100)) : 0 })
const statusText = computed(() => terminal.value ? (data.value?.summary ? statusLabel(data.value.summary.status) : data.value?.task_status) : '执行中')
function statusLabel(value) { return ({ passed: '通过', token_anomaly: 'Token 异常', pricing_unverifiable: '计价规则缺失', failed: '接口执行失败', unverifiable: '无法核验', cancelled: '已取消' }[value] || value || '-') }
function summaryType(value) { return value === 'passed' ? 'success' : value === 'failed' || value === 'token_anomaly' ? 'error' : 'warning' }
async function load() { try { data.value = await getVendorBilling(id); if (terminal.value) router.replace(`/tests/vendor-billing/${id}/result`) } catch (error) { ElMessage.error(error.message) } finally { loading.value = false } }
async function stop() { stopping.value = true; try { await stopTest(id); await load() } catch (error) { ElMessage.error(error.message) } finally { stopping.value = false } }
onMounted(() => { load(); timer = window.setInterval(load, 1500) }); onUnmounted(() => window.clearInterval(timer))
</script>
