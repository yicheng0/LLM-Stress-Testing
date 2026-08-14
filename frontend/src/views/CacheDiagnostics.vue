<template>
  <div class="section">
    <div class="section-header">
      <div>
        <h2 class="section-title">缓存专项测试</h2>
        <p class="subtitle">独立验证重复请求、多轮对话和尾部变化是否产生真实缓存命中。</p>
      </div>
      <el-tag effect="plain">可配置公共前缀与验证样本量</el-tag>
    </div>
    <div class="section-body">
      <el-alert
        title="判定只依据上游返回的缓存 usage 字段"
        description="缓存字段缺失会显示“无法判定”，不会根据延迟降低或文本重复猜测命中。三个 Case 会严格串行执行。"
        type="info"
        show-icon
        :closable="false"
      />
    </div>
  </div>

  <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
    <div class="section">
      <div class="section-header"><h2 class="section-title">连接配置</h2></div>
      <div class="section-body form-grid">
        <el-form-item label="测试名称" prop="name">
          <el-input v-model="form.name" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="接口协议" prop="api_protocol">
          <el-select v-model="form.api_protocol" @change="applyProtocolDefaults">
            <el-option label="OpenAI-compatible" value="openai" />
            <el-option label="Anthropic" value="anthropic" />
            <el-option label="Gemini" value="gemini" />
          </el-select>
        </el-form-item>
        <el-form-item label="接入域名" prop="base_url">
          <el-select v-if="auth.role === 'root'" v-model="form.base_url">
            <el-option label="国内节点" value="https://api.wenwen-ai.com" />
            <el-option label="海外节点" value="https://api.apipro.ai" />
          </el-select>
          <el-input v-else v-model="form.base_url" placeholder="https://api.example.com" />
        </el-form-item>
        <el-form-item label="模型" prop="model"><el-input v-model="form.model" /></el-form-item>
        <el-form-item label="Endpoint" prop="endpoint"><el-input v-model="form.endpoint" /></el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input v-model="form.api_key" type="password" show-password autocomplete="off" />
        </el-form-item>
      </div>
    </div>

    <div class="section">
      <div class="section-header"><h2 class="section-title">响应配置</h2></div>
      <div class="section-body form-grid">
        <el-form-item label="最大输出 Token" prop="max_output_tokens">
          <el-input-number v-model="form.max_output_tokens" :min="1" :max="65536" controls-position="right" />
        </el-form-item>
        <el-form-item label="公共前缀 Token" prop="input_tokens">
          <el-input-number v-model="form.input_tokens" :min="1" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="每个 Case 请求次数" prop="requests_per_case">
          <el-input-number v-model="form.requests_per_case" :min="2" :max="100" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" controls-position="right" />
        </el-form-item>
        <el-form-item label="请求超时（秒）" prop="timeout_sec">
          <el-input-number v-model="form.timeout_sec" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="连接超时（秒）" prop="connect_timeout_sec">
          <el-input-number v-model="form.connect_timeout_sec" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="失败重试" prop="max_retries">
          <el-input-number v-model="form.max_retries" :min="0" :max="10" controls-position="right" />
        </el-form-item>
        <el-form-item label="流式响应">
          <el-switch v-model="form.enable_stream" active-text="开启" inactive-text="关闭" />
        </el-form-item>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <div>
          <h2 class="section-title">缓存 Case</h2>
          <p class="subtitle">每个 Case 的第 1 次请求建立缓存；后续请求作为验证样本统计命中率。Case 内严格串行执行。</p>
        </div>
        <el-tag :type="form.case_ids.length ? 'success' : 'danger'" effect="plain">已选 {{ form.case_ids.length }} / 3</el-tag>
      </div>
      <div class="section-body case-grid">
        <button
          v-for="item in cases"
          :key="item.id"
          type="button"
          class="case-card"
          :class="{ active: form.case_ids.includes(item.id) }"
          @click="toggleCase(item.id)"
        >
          <strong>{{ item.name }}</strong>
          <span>{{ item.description }}</span>
          <em>{{ form.case_ids.includes(item.id) ? '已选择' : '点击选择' }}</em>
        </button>
      </div>
      <div class="plan-copy">
        已选 {{ form.case_ids.length }} 个 Case × 每 Case {{ form.requests_per_case }} 次 =
        <strong>计划 {{ plannedRequests }} 次业务请求</strong>
        <span>（失败重试不计入计划数）</span>
      </div>
    </div>

    <div class="submit-row">
      <el-button type="primary" size="large" :loading="submitting" @click="submit">启动缓存专项测试</el-button>
    </div>
  </el-form>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createCacheDiagnostics } from '../api/client'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref(null)
const submitting = ref(false)
const cases = [
  { id: 'repeat', name: '缓存命中-重复请求', description: '准备请求与验证请求完全相同。' },
  { id: 'multiturn', name: '缓存命中-多轮对话', description: '保留首轮上下文后新增一轮消息。' },
  { id: 'variable_suffix', name: '缓存命中-尾部变化', description: '公共前缀不变，只改变短尾部。' }
]
const form = reactive({
  name: '缓存专项测试', api_protocol: 'openai', anthropic_version: '2023-06-01',
  base_url: auth.role === 'guest' ? '' : 'https://api.wenwen-ai.com', endpoint: '/v1/chat/completions',
  api_key: '', model: 'gpt-5.5', max_output_tokens: 128, temperature: 0,
  timeout_sec: 600, connect_timeout_sec: 30, max_retries: 2,
  retry_backoff_base: 1, retry_backoff_max: 8, enable_stream: true,
  input_tokens: 4096, requests_per_case: 10,
  case_ids: ['repeat', 'multiturn', 'variable_suffix']
})
const rules = {
  name: [{ required: true, message: '请输入测试名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入接入域名', trigger: 'blur' }],
  endpoint: [{ required: true, message: '请输入 Endpoint', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  input_tokens: [{ validator: validatePositiveInteger, trigger: 'change' }],
  requests_per_case: [{ validator: validateRequestsPerCase, trigger: 'change' }]
}
const plannedRequests = computed(() => form.case_ids.length * form.requests_per_case)

function validatePositiveInteger(_rule, value, callback) {
  if (Number.isInteger(value) && value > 0) callback()
  else callback(new Error('公共前缀 Token 必须为正整数'))
}

function validateRequestsPerCase(_rule, value, callback) {
  if (Number.isInteger(value) && value >= 2 && value <= 100) callback()
  else callback(new Error('每个 Case 请求次数必须是 2 到 100 的整数'))
}

function toggleCase(id) {
  form.case_ids = form.case_ids.includes(id) ? form.case_ids.filter((item) => item !== id) : [...form.case_ids, id]
}

function applyProtocolDefaults(protocol) {
  if (protocol === 'anthropic') {
    form.endpoint = '/messages'
    form.model = 'claude-sonnet-4-6-20260218'
  } else if (protocol === 'gemini') {
    form.endpoint = '/v1beta/models/{model-name}:streamGenerateContent?alt=sse'
    form.model = 'gemini-3.1-pro-preview'
  } else {
    form.endpoint = '/v1/chat/completions'
    form.model = 'gpt-5.5'
  }
}

watch(
  () => form.enable_stream,
  (enabled) => {
    if (form.api_protocol !== 'gemini') return
    form.endpoint = enabled
      ? '/v1beta/models/{model-name}:streamGenerateContent?alt=sse'
      : '/v1beta/models/{model-name}:generateContent'
  }
)

async function submit() {
  if (!form.case_ids.length) {
    ElMessage.warning('至少选择一个缓存 Case')
    return
  }
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const result = await createCacheDiagnostics({ ...form })
    ElMessage.success('缓存专项任务已启动')
    router.push(`/tests/cache-diagnostics/${result.test_id}`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.subtitle { margin: 5px 0 0; color: #6b7280; font-size: 13px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.case-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.case-card { display: grid; gap: 9px; min-height: 150px; padding: 18px; border: 1px solid #d1d5db; border-radius: 10px; background: #fff; color: #111827; text-align: left; cursor: pointer; }
.case-card.active { border-color: #2563eb; box-shadow: inset 0 0 0 1px #2563eb; background: #eff6ff; }
.case-card strong { font-size: 16px; }
.case-card span { color: #6b7280; line-height: 1.6; }
.case-card em { align-self: end; color: #2563eb; font-style: normal; font-weight: 700; }
.plan-copy { margin: 16px 0 0; color: #4b5563; font-size: 14px; }.plan-copy strong { color: #111827; }.plan-copy span { color: #6b7280; }
.submit-row { display: flex; justify-content: flex-end; padding: 8px 0 24px; }
@media (max-width: 768px) { .form-grid, .case-grid { grid-template-columns: 1fr; } }
</style>
