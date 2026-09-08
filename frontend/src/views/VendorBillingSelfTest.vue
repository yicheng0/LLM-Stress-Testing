<template>
  <div class="vendor-billing-page">
    <div class="section">
      <div class="section-header">
        <div>
          <h2 class="section-title">供应商接入计费自测</h2>
          <p class="subtitle">同一份确定性输入成对请求供应商与官方参考接口，核验 Token 上报并计算应计费用。</p>
        </div>
        <el-tag type="warning" effect="plain">不核验实际账单扣费</el-tag>
      </div>
      <div class="section-body">
        <el-alert title="安全提示" type="info" :closable="false" show-icon>
          API Key 仅用于本次请求，不会写入任务配置、日志、结果文件或报告。
        </el-alert>
      </div>
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="vendor-form">
      <div class="section">
        <div class="section-header"><h2 class="section-title">供应商连接</h2></div>
        <div class="section-body form-grid">
          <el-form-item label="接入模板"><el-select v-model="selectedTemplateId" class="full-width" clearable placeholder="选择模板；不选则使用下方完整配置"><el-option v-for="template in templates" :key="template.id" :label="`${template.config?.name || '-'} · ${template.config?.supplier_name || '-'}`" :value="template.id" /></el-select></el-form-item>
          <el-form-item label="测试名称" prop="name"><el-input v-model="form.name" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="供应商名称" prop="supplier_name"><el-input v-model="form.supplier_name" placeholder="例如：供应商 A" /></el-form-item>
          <el-form-item label="协议" prop="api_protocol">
            <el-select v-model="form.api_protocol" class="full-width" @change="applyProtocolDefaults">
              <el-option label="OpenAI-compatible" value="openai" /><el-option label="Anthropic" value="anthropic" /><el-option label="Gemini" value="gemini" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="供应商 API URL" prop="base_url"><el-input v-model="form.base_url" placeholder="https://provider.example.com" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="供应商 Endpoint" prop="endpoint"><el-input v-model="form.endpoint" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="供应商模型" prop="model"><el-input v-model="form.model" /></el-form-item>
          <el-form-item label="供应商 API Key" prop="api_key"><el-input v-model="form.api_key" type="password" show-password autocomplete="off" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId && form.api_protocol === 'anthropic'" label="Anthropic-Version"><el-input v-model="form.anthropic_version" /></el-form-item>
        </div>
      </div>

      <el-alert v-if="selectedTemplateId" title="已选择接入模板" description="模板中的接口、模型、Token 测试组和价格规则将自动使用；这里只提交本次临时凭证。" type="success" :closable="false" show-icon />

      <div class="section">
        <div class="section-header">
          <div><h2 class="section-title">官方参考连接</h2><p class="subtitle">官方模型是 Token 对照基准；可以与供应商使用不同模型名称，但协议语义保持一致。</p></div>
        </div>
        <div class="section-body form-grid">
          <el-form-item v-if="!selectedTemplateId" label="官方 API URL" prop="reference_base_url"><el-input v-model="form.reference_base_url" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="官方 Endpoint" prop="reference_endpoint"><el-input v-model="form.reference_endpoint" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="官方模型" prop="reference_model"><el-input v-model="form.reference_model" /></el-form-item>
          <el-form-item label="官方 API Key" prop="reference_api_key"><el-input v-model="form.reference_api_key" type="password" show-password autocomplete="off" /></el-form-item>
          <el-form-item v-if="form.api_protocol === 'anthropic'" label="官方 Anthropic-Version"><el-input v-model="form.reference_anthropic_version" /></el-form-item>
        </div>
      </div>

      <div class="section">
        <div class="section-header"><div><h2 class="section-title">输入与计价</h2><p class="subtitle">每组按供应商 → 官方 → 比较顺序执行，输出 Token 差异只展示，不单独判异常。</p></div></div>
        <div class="section-body form-grid">
          <el-form-item v-if="!selectedTemplateId" label="输入 Token 长度（最多 6 组）" prop="input_token_lengths_text"><el-input v-model="inputLengthsText" placeholder="128,1024,4096" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="最大输出 Token"><el-input-number v-model="form.max_output_tokens" :min="1" :max="65536" controls-position="right" class="full-width" /></el-form-item>
          <el-form-item label="Temperature"><el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" controls-position="right" class="full-width" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="价格规则" prop="pricing_rule_id">
            <el-select v-model="form.pricing_rule_id" class="full-width" filterable placeholder="选择官方价格规则">
              <el-option v-for="rule in pricingRules" :key="rule.id" :label="`${rule.id} · ${rule.model}`" :value="rule.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="输入 Token 绝对容差"><el-input-number v-model="form.token_abs_tolerance" :min="0" :max="10000" controls-position="right" class="full-width" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="输入 Token 相对容差"><el-input-number v-model="relativeTolerancePercent" :min="0" :max="100" :step="1" controls-position="right" class="full-width" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="流式响应"><el-switch v-model="form.enable_stream" active-text="开启" inactive-text="关闭" /></el-form-item>
          <el-form-item v-if="!selectedTemplateId" label="请求超时（秒）"><el-input-number v-model="form.timeout_sec" :min="1" :max="3600" controls-position="right" class="full-width" /></el-form-item>
        </div>
        <div class="section-body preview-panel">
          <strong>本次预计检查</strong>
          <span>{{ parsedLengths.length }} 组输入长度，预计 {{ parsedLengths.length * 2 }} 次正式请求（不含预检）</span>
          <span v-if="selectedRule">价格目录 {{ selectedRule.source_version || selectedRule.version || '未标版本' }} · {{ selectedRule.input_mode === 'exclusive' ? '缓存 Token 从普通输入中单列' : '输入价格按 inclusive 口径' }}</span>
          <el-tag :type="selectedRule?.verified ? 'success' : 'warning'" effect="plain">{{ selectedRule?.verified ? '价格来源已标记验证' : '示例价格未验证，仅按目录试算' }}</el-tag>
        </div>
      </div>

      <div class="submit-row"><el-button type="primary" size="large" :loading="submitting" @click="submit">启动供应商接入自测</el-button></div>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createVendorBilling, createVendorBillingFromTemplate, getVendorBillingConfig, listVendorTemplates } from '../api/client'
import { useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const formRef = ref(null)
const submitting = ref(false)
const pricingRules = ref([])
const templates = ref([])
const selectedTemplateId = ref('')
const inputLengthsText = ref('128,1024,4096')
const relativeTolerancePercent = ref(5)
const form = reactive({
  name: '供应商接入计费自测', supplier_name: '', api_protocol: 'openai', anthropic_version: '2023-06-01',
  base_url: '', endpoint: '/v1/chat/completions', api_key: '', model: '',
  reference_base_url: '', reference_endpoint: '/v1/chat/completions', reference_api_key: '', reference_model: '', reference_anthropic_version: '2023-06-01',
  max_output_tokens: 128, temperature: 0, timeout_sec: 120, connect_timeout_sec: 30, enable_stream: false,
  pricing_rule_id: '', token_abs_tolerance: 16, token_relative_tolerance: 0.05
})
const rules = {
  name: [{ required: true, message: '请输入测试名称', trigger: 'blur' }], supplier_name: [{ required: true, message: '请输入供应商名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入供应商 API URL', trigger: 'blur' }], endpoint: [{ required: true, message: '请输入供应商 Endpoint', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入供应商 API Key', trigger: 'blur' }], model: [{ required: true, message: '请输入供应商模型', trigger: 'blur' }],
  reference_base_url: [{ required: true, message: '请输入官方 API URL', trigger: 'blur' }], reference_endpoint: [{ required: true, message: '请输入官方 Endpoint', trigger: 'blur' }],
  reference_api_key: [{ required: true, message: '请输入官方 API Key', trigger: 'blur' }], reference_model: [{ required: true, message: '请输入官方模型', trigger: 'blur' }],
  pricing_rule_id: [{ required: true, message: '请选择价格规则', trigger: 'change' }]
}
const parsedLengths = computed(() => inputLengthsText.value.split(',').map((value) => Number(value.trim())))
const selectedRule = computed(() => pricingRules.value.find((rule) => rule.id === form.pricing_rule_id))

function applyProtocolDefaults(protocol) {
  if (protocol === 'anthropic') { form.endpoint = '/messages'; form.reference_endpoint = '/messages'; form.model = 'claude-sonnet'; form.reference_model = 'claude-sonnet' }
  else if (protocol === 'gemini') { form.endpoint = '/v1beta/models/{model-name}:generateContent'; form.reference_endpoint = '/v1beta/models/{model-name}:generateContent'; form.model = 'gemini-2.5-pro'; form.reference_model = 'gemini-2.5-pro' }
  else { form.endpoint = '/v1/chat/completions'; form.reference_endpoint = '/v1/chat/completions'; form.model = 'gpt-4o-mini'; form.reference_model = 'gpt-4o-mini' }
}
async function submit() {
  if (selectedTemplateId.value && (!form.api_key.trim() || !form.reference_api_key.trim())) { ElMessage.error('请输入本次供应商 API Key 和官方 API Key'); return }
  const valid = selectedTemplateId.value ? true : await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (parsedLengths.value.length < 1 || parsedLengths.value.length > 6 || parsedLengths.value.some((value) => !Number.isInteger(value) || value <= 0 || value > 100000)) { ElMessage.error('输入 Token 长度必须是 1-100000 的 1 到 6 个整数，不能包含非法值'); return }
  if (new Set(parsedLengths.value).size !== parsedLengths.value.length) { ElMessage.error('输入 Token 长度不能重复'); return }
  if (!selectedRule.value || selectedRule.value.protocol !== form.api_protocol) { ElMessage.error('价格规则与 API 协议不匹配'); return }
  const pattern = selectedRule.value.reference_model_pattern || selectedRule.value.model
  if (pattern && form.reference_model !== pattern && !new RegExp(`^${String(pattern).replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\*/g, '.*')}$`).test(form.reference_model)) { ElMessage.error('官方参考模型与价格规则不匹配'); return }
  submitting.value = true
  try {
    const result = selectedTemplateId.value
      ? await createVendorBillingFromTemplate({ template_id: selectedTemplateId.value, api_key: form.api_key, reference_api_key: form.reference_api_key, name: form.name })
      : await createVendorBilling({ ...form, input_token_lengths: parsedLengths.value, token_relative_tolerance: relativeTolerancePercent.value / 100 })
    ElMessage.success('自测任务已启动')
    router.push(`/tests/vendor-billing/${result.test_id}/run`)
  } catch (error) { ElMessage.error(error.message) } finally { submitting.value = false }
}
onMounted(async () => {
  try { const data = await getVendorBillingConfig(); pricingRules.value = data.pricing_rules || []; if (pricingRules.value.length) form.pricing_rule_id = pricingRules.value[0].id; templates.value = (await listVendorTemplates({ enabled: true, page_size: 100 })).items || []; selectedTemplateId.value = route.query.template || '' } catch (error) { ElMessage.error(error.message) }
})
</script>
