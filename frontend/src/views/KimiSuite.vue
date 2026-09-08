<template>
  <div class="section">
    <div class="section-header"><div><h2 class="section-title">Kimi 能力测试集</h2><p class="subtitle">验证 kimi-k3 的参数兼容性、输出约束、工具调用、缓存 usage 与视频理解。</p></div><el-tag effect="plain">{{ selected.length }} / {{ cases.length }} Case</el-tag></div>
    <div class="section-body">
      <el-form :model="form" label-position="top">
        <div class="form-grid">
          <el-form-item label="测试名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="协议"><el-select v-model="form.api_protocol" @change="applyProtocolDefaults"><el-option label="OpenAI-compatible" value="openai" /><el-option label="Anthropic Messages" value="anthropic" /><el-option label="Gemini API" value="gemini" /></el-select></el-form-item>
          <el-form-item label="接入域名"><el-input v-model="form.base_url" /></el-form-item>
          <el-form-item label="Endpoint"><el-input v-model="form.endpoint" /></el-form-item>
          <el-form-item label="模型"><el-input v-model="form.model" /></el-form-item>
          <el-form-item :label="apiKeyLabel"><el-input v-model="form.api_key" type="password" show-password /></el-form-item>
          <el-form-item label="最大输出 Token"><el-input-number v-model="form.max_output_tokens" :min="1" :max="65536" /></el-form-item>
          <el-form-item label="流式响应"><el-switch v-model="form.enable_stream" /></el-form-item>
          <el-form-item label="视频解析样本"><div class="built-in-video"><video controls muted loop preload="metadata" src="/assets/kimi-video-solid.mp4" /><div><strong>系统内置纯色视频</strong><small>选择“视频解析” Case 后自动使用，无需上传本地文件</small></div></div></el-form-item>
        </div>
        <div class="case-section-head">
          <div>
            <h3>测试 Case</h3>
            <p>点击首列复选框选择需要执行的 Case；执行前指标显示为“—”。</p>
          </div>
          <a-tag color="blue">已选择 {{ selected.length }} / {{ cases.length }}</a-tag>
        </div>
        <div class="case-table-wrap">
          <a-table :columns="caseColumns" :data-source="cases" :pagination="false" :scroll="{ x: 1280 }" row-key="id" class="kimi-case-table">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'select'"><a-checkbox :checked="form.case_ids.includes(record.id)" @change="toggle(record.id)" /></template>
              <template v-else-if="column.key === 'endpoint'">{{ form.endpoint || '—' }}</template>
              <template v-else-if="column.key === 'apiKey'">{{ maskedApiKey }}</template>
              <template v-else-if="column.key === 'model'">{{ form.model || '—' }}</template>
              <template v-else-if="column.key === 'status'"><a-tag color="default">待测试</a-tag></template>
              <template v-else-if="['latency', 'ttft'].includes(column.key)">—</template>
              <template v-else-if="['retry', 'rerun'].includes(column.key)">0</template>
            </template>
          </a-table>
        </div>
        <div class="submit-row"><el-button type="primary" :loading="loading" @click="submit">启动 Kimi 测试集（{{ selected.length }} 个 Case）</el-button></div>
      </el-form>
    </div>
  </div>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Checkbox as ACheckbox, Table as ATable, Tag as ATag } from 'ant-design-vue'
import { createKimiSuite } from '../api/client'
const router = useRouter(); const loading = ref(false)
const cases = [
  ['cache_repeat','缓存命中-重复请求','相同消息重复请求'],['cache_multiturn','缓存命中-多轮对话','保留上下文新增一轮'],['cache_variable_suffix','缓存命中-尾部变化','只改变短尾部'],['thinking','思考控制-多场景','开启与关闭 thinking'],['json_output','JSON格式输出校验-多场景','验证 JSON 对象'],['stop','stop参数生效-多场景','数字与中文 stop'],['sampling','采样参数-多场景','temperature 与 top_p'],['tool_call','工具调用-多场景','函数名与参数'],['output_tokens','输出tokens校验-多场景','多个 max_tokens 上限'],['video_parse','视频解析','上传视频并返回内容摘要'],['prompt_token_injection','Prompt Token 注入检测','检测网关是否额外注入提示词']
].map(([id,name,description]) => ({ id, name, description }))
const form = reactive({ name:'Kimi 能力测试集', api_protocol:'openai', base_url:'https://api.wenwen-ai.com', endpoint:'/v1/chat/completions', model:'kimi-k3', api_key:'', max_output_tokens:128, enable_stream:true, case_ids:cases.map(item=>item.id), video_data_url:null, video_mime_type:'video/mp4' })
const videoLabel = ref('')
const selected = computed(() => form.case_ids)
const apiKeyLabel = computed(() => form.api_protocol === 'anthropic' ? 'Anthropic API Key' : form.api_protocol === 'gemini' ? 'Gemini API Key' : 'API Key')
const protocolDefaults = {
  openai: { endpoint: '/v1/chat/completions' },
  anthropic: { endpoint: '/v1/messages' },
  gemini: { endpoint: '/v1beta/models/{model-name}:generateContent' }
}
const caseColumns = [
  { title: '选择', key: 'select', width: 72, align: 'center' },
  { title: 'Case 名称', dataIndex: 'name', key: 'name', width: 260 },
  { title: 'Endpoint', key: 'endpoint', width: 180 },
  { title: 'API Key', key: 'apiKey', width: 180 },
  { title: '供应商模型', key: 'model', width: 150 },
  { title: '状态', key: 'status', width: 110, align: 'center' },
  { title: '耗时', key: 'latency', width: 110, align: 'center' },
  { title: '首 token', key: 'ttft', width: 110, align: 'center' },
  { title: '重试', key: 'retry', width: 82, align: 'center' },
  { title: '人工重跑', key: 'rerun', width: 110, align: 'center' }
]
const maskedApiKey = computed(() => {
  const value = String(form.api_key || '')
  if (!value) return '—'
  if (value.length <= 8) return '••••••••'
  return `${value.slice(0, 4)}••••${value.slice(-4)}`
})
function toggle(id) { form.case_ids = form.case_ids.includes(id) ? form.case_ids.filter(x=>x!==id) : [...form.case_ids,id] }
function applyProtocolDefaults() { form.endpoint = (protocolDefaults[form.api_protocol] || protocolDefaults.openai).endpoint }
async function loadBuiltInVideo() { const response = await fetch('/assets/kimi-video-solid.mp4'); const blob = await response.blob(); form.video_data_url = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(blob) }) }
async function submit() { if (!form.api_key) return ElMessage.error('请输入 API Key'); if (!form.case_ids.length) return ElMessage.error('至少选择一个 Case'); loading.value=true; try { if (form.case_ids.includes('video_parse') && !form.video_data_url) await loadBuiltInVideo(); const result=await createKimiSuite(form); router.push(`/tests/kimi-suite/${result.test_id}`) } catch (e) { const detail = e?.detail || e?.message || '请求失败'; ElMessage.error(typeof detail === 'string' ? detail : (detail?.[0]?.msg || '请求参数校验失败')) } finally { loading.value=false } }
</script>
<style scoped>
.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.case-section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:24px 0 12px}
.case-section-head h3{margin:0 0 5px;font-size:18px}
.case-section-head p{margin:0;color:#6b7280;font-size:13px}
.case-table-wrap{overflow:hidden;border:1px solid #dfe5ec;border-radius:10px;background:#fff}
.kimi-case-table :deep(.ant-table-thead > tr > th){background:#f5f8fc;color:#334155;font-weight:700;white-space:nowrap}
.kimi-case-table :deep(.ant-table-tbody > tr > td){height:58px}
.submit-row{margin-top:22px;text-align:right}
@media(max-width:768px){.form-grid{grid-template-columns:1fr}.case-section-head{align-items:flex-start;flex-direction:column}.submit-row{text-align:left}}
</style>
