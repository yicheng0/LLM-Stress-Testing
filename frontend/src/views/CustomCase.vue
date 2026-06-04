<template>
  <div>
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">自定义输入 TTFT 诊断</h2>
        <el-tag type="success" effect="plain">单条 Case</el-tag>
      </div>
      <div class="section-body custom-intro">
        <div>
          <strong>用真实输入观察首 token、总延迟和吞吐</strong>
          <span>该页面会直接发送下方 prompt，默认使用 1 并发、10 秒、流式模式，适合快速诊断 TTFT。</span>
        </div>
        <el-alert
          title="自定义输入会保存到历史记录和报告文件"
          description="请确认输入内容不包含不能落盘的敏感信息；API Key 仍会按现有逻辑脱敏保存。"
          type="warning"
          show-icon
          :closable="false"
        />
      </div>
    </div>

    <div class="grid-2 custom-grid">
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">请求配置</h2>
        </div>
        <div class="section-body">
          <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
            <div class="grid-2">
              <el-form-item label="接口协议" prop="api_protocol">
                <el-select v-model="form.api_protocol" class="full-select" @change="applyProtocolDefaults">
                  <el-option label="OpenAI-compatible" value="openai" />
                  <el-option label="Anthropic Messages" value="anthropic" />
                  <el-option label="Gemini API" value="gemini" />
                </el-select>
              </el-form-item>
              <el-form-item label="测试名称" prop="name">
                <el-input v-model="form.name" maxlength="120" show-word-limit />
              </el-form-item>
              <el-form-item label="模型名称" prop="model">
                <el-input v-model="form.model" />
              </el-form-item>
              <el-form-item label="接入域名" prop="base_url">
                <el-select v-model="form.base_url" class="full-select" filterable allow-create>
                  <el-option label="国内节点" value="https://api.wenwen-ai.com" />
                  <el-option label="海外节点" value="https://api.apipro.ai" />
                </el-select>
              </el-form-item>
              <el-form-item label="Endpoint" prop="endpoint">
                <el-input v-model="form.endpoint" />
              </el-form-item>
              <el-form-item :label="apiKeyLabel" prop="api_key">
                <el-input v-model="form.api_key" type="password" show-password autocomplete="off" />
              </el-form-item>
              <el-form-item v-if="form.api_protocol === 'anthropic'" label="Anthropic Version" prop="anthropic_version">
                <el-input v-model="form.anthropic_version" />
              </el-form-item>
            </div>

            <el-form-item label="自定义输入 Prompt" prop="custom_prompt" class="full-row">
              <el-input
                v-model="form.custom_prompt"
                class="prompt-input"
                type="textarea"
                :rows="14"
                maxlength="200000"
                show-word-limit
                placeholder="粘贴要诊断的真实业务输入。系统会用这段内容作为 user prompt 发起请求。"
              />
            </el-form-item>
          </el-form>
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <h2 class="section-title">诊断参数</h2>
          <el-button :icon="RefreshLeft" @click="resetConservative">保守默认</el-button>
        </div>
        <div class="section-body">
          <div class="diagnostic-form">
            <el-form :model="form" label-position="top">
              <div class="grid-2">
                <el-form-item label="并发数">
                  <el-input-number v-model="form.concurrency" :min="1" :max="1000" controls-position="right" />
                </el-form-item>
                <el-form-item label="测试时长（秒）">
                  <el-input-number v-model="form.duration_sec" :min="1" :max="86400" controls-position="right" />
                </el-form-item>
                <el-form-item label="最大输出 Token">
                  <el-input-number v-model="form.max_output_tokens" :min="1" :max="65536" controls-position="right" />
                </el-form-item>
                <el-form-item label="预热请求数">
                  <el-input-number v-model="form.warmup_requests" :min="0" :max="10000" controls-position="right" />
                </el-form-item>
                <el-form-item label="流式模式">
                  <el-switch v-model="form.enable_stream" active-text="开启" inactive-text="关闭" />
                </el-form-item>
                <el-form-item label="Temperature">
                  <el-input-number
                    v-model="form.temperature"
                    :min="0"
                    :max="2"
                    :step="0.1"
                    controls-position="right"
                    placeholder="留空则不发送"
                    clearable
                  />
                </el-form-item>
                <el-form-item label="请求超时（秒）">
                  <el-input-number v-model="form.timeout_sec" :min="1" controls-position="right" />
                </el-form-item>
                <el-form-item label="连接超时（秒）">
                  <el-input-number v-model="form.connect_timeout_sec" :min="1" controls-position="right" />
                </el-form-item>
                <el-form-item label="最大重试次数">
                  <el-input-number v-model="form.max_retries" :min="0" controls-position="right" />
                </el-form-item>
                <el-form-item label="请求间隔（毫秒）">
                  <el-input-number v-model="form.think_time_ms" :min="0" controls-position="right" />
                </el-form-item>
              </div>
            </el-form>
          </div>

          <div class="case-preview">
            <div>
              <span>Prompt 字符数</span>
              <strong>{{ number(promptChars) }}</strong>
            </div>
            <div>
              <span>预估输入 Token</span>
              <strong>{{ number(estimatedInputTokens) }}</strong>
            </div>
            <div>
              <span>单请求 Token 上限</span>
              <strong>{{ number(estimatedTokensPerRequest) }}</strong>
            </div>
            <div>
              <span>预计请求数</span>
              <strong>{{ number(estimatedRequests) }}</strong>
            </div>
            <div>
              <span>预期 RPM</span>
              <strong>{{ number(estimatedRpm) }}</strong>
            </div>
            <div>
              <span>预期 TPM</span>
              <strong>{{ number(estimatedTpm) }}</strong>
            </div>
          </div>

          <el-alert
            v-if="!form.enable_stream"
            class="case-alert"
            title="关闭流式后 TTFT 无法准确测量"
            description="自定义输入诊断建议开启流式模式，报告里的 TTFT 和 Decode 才有真实观测点。"
            type="warning"
            show-icon
            :closable="false"
          />

          <div class="case-actions">
            <div>
              <strong>{{ form.model || '未填写模型' }}</strong>
              <span>{{ form.concurrency }} 并发 · {{ form.duration_sec }}s · 自定义输入</span>
            </div>
            <el-button type="primary" :icon="VideoPlay" :loading="submitting" @click="submit">
              启动诊断
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshLeft, VideoPlay } from '@element-plus/icons-vue'
import { createTest } from '../api/client'

const router = useRouter()
const formRef = ref()
const submitting = ref(false)

const protocolDefaults = {
  openai: {
    endpoint: '/v1/chat/completions',
    model: 'gpt-5.5'
  },
  anthropic: {
    endpoint: '/v1/messages',
    model: 'claude-sonnet-4-6-20260218'
  },
  gemini: {
    endpoint: '/v1beta/models/{model-name}:streamGenerateContent?alt=sse',
    model: 'gemini-3.1-pro-preview'
  }
}

const conservativeDefaults = {
  name: '自定义输入 TTFT 诊断',
  api_protocol: 'openai',
  anthropic_version: '2023-06-01',
  base_url: 'https://api.wenwen-ai.com',
  api_key: '',
  model: 'gpt-5.5',
  endpoint: '/v1/chat/completions',
  concurrency: 1,
  duration_sec: 10,
  input_tokens: 1,
  max_output_tokens: 128,
  temperature: null,
  timeout_sec: 600,
  connect_timeout_sec: 30,
  warmup_requests: 0,
  max_retries: 2,
  retry_backoff_base: 1,
  retry_backoff_max: 8,
  think_time_ms: 0,
  enable_stream: true,
  matrix_mode: false,
  input_tokens_list: '',
  concurrency_list: '',
  matrix_duration_sec: 60,
  prompt_source: 'custom',
  custom_prompt: ''
}

const form = reactive({ ...conservativeDefaults, ...readInitialConfig() })

const rules = {
  name: [{ required: true, message: '请输入测试名称', trigger: 'blur' }],
  api_protocol: [{ required: true, message: '请选择接口协议', trigger: 'change' }],
  base_url: [{ required: true, message: '请输入接入域名', trigger: 'change' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  endpoint: [{ required: true, message: '请输入 Endpoint', trigger: 'blur' }],
  custom_prompt: [
    { required: true, message: '请输入自定义 prompt', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (!String(value || '').trim()) {
          callback(new Error('自定义输入 case 不能为空'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ]
}

const apiKeyLabel = computed(() => {
  if (form.api_protocol === 'anthropic') return 'Anthropic API Key'
  if (form.api_protocol === 'gemini') return 'Gemini API Key'
  return 'API Key'
})
const promptChars = computed(() => form.custom_prompt.length)
const estimatedInputTokens = computed(() => estimateTokens(form.custom_prompt))
const estimatedTokensPerRequest = computed(() => estimatedInputTokens.value + Number(form.max_output_tokens || 0))
const effectiveLatencySec = computed(() => Math.max(0.001, 10 + Number(form.think_time_ms || 0) / 1000))
const estimatedRpm = computed(() => Number(form.concurrency || 0) / effectiveLatencySec.value * 60)
const estimatedRequests = computed(() => estimatedRpm.value * Number(form.duration_sec || 0) / 60)
const estimatedTpm = computed(() => estimatedRpm.value * estimatedTokensPerRequest.value)

function applyProtocolDefaults() {
  const defaults = protocolDefaults[form.api_protocol] || protocolDefaults.openai
  form.endpoint = defaults.endpoint
  form.model = defaults.model
}

function resetConservative() {
  const preserved = {
    api_protocol: form.api_protocol,
    anthropic_version: form.anthropic_version,
    base_url: form.base_url,
    api_key: form.api_key,
    model: form.model,
    endpoint: form.endpoint,
    custom_prompt: form.custom_prompt
  }
  Object.assign(form, conservativeDefaults, preserved, {
    prompt_source: 'custom',
    matrix_mode: false
  })
}

async function submit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const payload = {
      ...form,
      prompt_source: 'custom',
      custom_prompt: form.custom_prompt,
      input_tokens: Math.max(1, estimatedInputTokens.value),
      matrix_mode: false,
      expected_metrics: {
        expected_rpm: estimatedRpm.value,
        expected_tpm: estimatedTpm.value,
        expected_tps: estimatedTpm.value / 60,
        expected_requests: estimatedRequests.value,
        expected_input_token_total: estimatedRequests.value * estimatedInputTokens.value,
        expected_output_token_limit: estimatedRequests.value * Number(form.max_output_tokens || 0),
        expected_latency_sec: 10
      }
    }
    const result = await createTest(payload)
    sessionStorage.removeItem('rerun_config')
    ElMessage.success('自定义输入诊断已启动')
    router.push(`/tests/${result.test_id}/run`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

function readInitialConfig() {
  const raw = sessionStorage.getItem('rerun_config')
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (parsed.prompt_source !== 'custom') return null
    return { ...parsed, api_key: '', matrix_mode: false, prompt_source: 'custom' }
  } catch {
    return null
  }
}

function estimateTokens(text) {
  const value = String(text || '')
  if (!value) return 0
  const cjk = (value.match(/[\u3400-\u9fff]/g) || []).length
  const nonCjk = value.length - cjk
  return Math.max(1, Math.ceil(cjk * 1.1 + nonCjk / 4))
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })
}
</script>

<style scoped>
.custom-intro {
  display: grid;
  gap: 12px;
}

.custom-intro > div:first-child {
  display: grid;
  gap: 5px;
}

.custom-intro strong {
  color: #1e293b;
  font-size: 16px;
}

.custom-intro span {
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.custom-grid {
  align-items: start;
  margin-top: 16px;
}

.full-select {
  width: 100%;
}

.prompt-input :deep(textarea) {
  font-family: "Fira Code", Consolas, monospace;
  line-height: 1.55;
}

.diagnostic-form {
  margin-bottom: 14px;
}

.case-preview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.case-preview > div {
  min-height: 86px;
  padding: 13px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.case-preview span,
.case-actions span {
  display: block;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.case-preview strong {
  display: block;
  margin-top: 8px;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 20px;
  line-height: 1.2;
  word-break: break-word;
}

.case-alert {
  margin-top: 14px;
}

.case-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #e5edf6;
}

.case-actions strong {
  display: block;
  color: #1e293b;
  font-size: 14px;
  line-height: 1.4;
}

@media (max-width: 980px) {
  .custom-grid,
  .case-preview {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .case-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .case-actions .el-button {
    width: 100%;
  }
}
</style>
