<template>
  <div class="page-stack">
    <div class="section"><div class="section-header"><div><h2 class="section-title">供应商接入模板</h2><p class="subtitle">保存可复用的模型接入参数，API Key 仅在发起测试时填写。</p></div><el-button type="primary" @click="router.push('/vendor-templates/new')">新建模板</el-button></div></div>
    <div class="section"><div class="section-body"><el-table v-loading="loading" :data="items" border>
      <el-table-column prop="config.name" label="模板名称" min-width="180" />
      <el-table-column prop="config.supplier_name" label="供应商" min-width="140" />
      <el-table-column prop="config.model" label="模型" min-width="150" />
      <el-table-column prop="config.api_protocol" label="协议" width="140" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" effect="plain">{{ row.enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column label="价格来源" min-width="150"><template #default="{ row }"><el-tag :type="priceVerified(row) ? 'success' : 'warning'" effect="plain">{{ priceVerified(row) ? '已验证' : '未验证' }}</el-tag></template></el-table-column>
      <el-table-column label="更新时间" min-width="170"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
      <el-table-column label="操作" width="260" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="router.push(`/vendor-templates/${row.id}/edit`)">编辑</el-button><el-button link type="primary" @click="startTest(row)">发起测试</el-button><el-button link @click="toggle(row)">{{ row.enabled ? '停用' : '启用' }}</el-button></template></el-table-column>
    </el-table><el-empty v-if="!loading && !items.length" description="暂无接入模板" /></div></div>
  </div>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listVendorTemplates, setVendorTemplateEnabled } from '../api/client'
const router = useRouter(); const items = ref([]); const loading = ref(false)
async function load() { loading.value = true; try { items.value = (await listVendorTemplates({ page_size: 100 })).items || [] } catch (e) { ElMessage.error(e.message) } finally { loading.value = false } }
function priceVerified(row) { return Boolean(row.config?.pricing_verified) }
async function toggle(row) { try { await ElMessageBox.confirm(`确认${row.enabled ? '停用' : '启用'}模板「${row.config?.name}」？`, '模板状态') } catch { return } try { await setVendorTemplateEnabled(row.id, !row.enabled); ElMessage.success('模板状态已更新'); await load() } catch (e) { ElMessage.error(e.message) } }
function startTest(row) { router.push({ path: '/tests/vendor-billing', query: { template: row.id } }) }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' }).format(new Date(value)) : '-' }
onMounted(load)
</script>
<style scoped>.page-stack{display:grid;gap:16px}.section{background:#fff;border:1px solid #e5e7eb;border-radius:10px}.section-header,.section-body{padding:18px}.section-header{display:flex;justify-content:space-between;align-items:center}.section-title{margin:0}.subtitle{color:#6b7280}</style>
