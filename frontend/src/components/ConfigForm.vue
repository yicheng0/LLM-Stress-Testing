<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">基础配置</h2>
      </div>
      <div class="section-body">
        <el-form-item label="接口协议" prop="api_protocol" class="full-row">
          <div class="provider-grid" role="radiogroup" aria-label="接口协议">
            <button
              v-for="option in protocolOptions"
              :key="option.value"
              type="button"
              role="radio"
              class="provider-card"
              :class="{ active: form.api_protocol === option.value }"
              :aria-checked="form.api_protocol === option.value"
              @click="form.api_protocol = option.value"
            >
              <span class="provider-icon">
                <el-icon><component :is="option.icon" /></el-icon>
              </span>
              <span class="provider-copy">
                <span class="provider-name">{{ option.label }}</span>
                <span class="provider-desc">{{ option.description }}</span>
                <span class="provider-endpoint mono">{{ option.endpoint }}</span>
              </span>
            </button>
          </div>
        </el-form-item>
      </div>
      <div class="section-body section-body-compact grid-2">
        <el-form-item label="测试名称" prop="name">
          <el-input v-model="form.name" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="模型名称" prop="model">
          <el-input v-model="form.model" :placeholder="modelPlaceholder" />
        </el-form-item>
        <el-form-item label="接入域名" prop="base_url">
          <el-select v-model="form.base_url" class="full-select">
            <el-option
              v-for="option in domainOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            >
              <div class="domain-option">
                <span>{{ option.label }}</span>
                <code>{{ option.value }}</code>
              </div>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="Endpoint" prop="endpoint">
          <el-input v-model="form.endpoint" placeholder="/chat/completions" />
        </el-form-item>
        <el-form-item :label="apiKeyLabel" prop="api_key" class="full-row">
          <el-input v-model="form.api_key" type="password" show-password autocomplete="off" />
        </el-form-item>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">负载配置</h2>
      </div>
      <div class="section-body grid-2">
        <el-form-item label="并发数" prop="concurrency">
          <el-input-number v-model="form.concurrency" :min="1" :max="1000" controls-position="right" />
        </el-form-item>
        <el-form-item label="测试时长（秒）" prop="duration_sec">
          <el-input-number v-model="form.duration_sec" :min="1" :max="86400" controls-position="right" />
        </el-form-item>
        <el-form-item label="输入 Token 数" prop="input_tokens">
          <div class="inline-field">
            <el-input-number v-model="form.input_tokens" :min="1" :step="1000" controls-position="right" />
            <el-segmented v-model="tokenPreset" :options="tokenOptions" @change="applyTokenPreset" />
          </div>
        </el-form-item>
        <el-form-item label="最大输出 Token 数" prop="max_output_tokens">
          <el-input-number v-model="form.max_output_tokens" :min="1" :max="65536" controls-position="right" />
        </el-form-item>
        <el-form-item label="预热请求数" prop="warmup_requests">
          <el-input-number v-model="form.warmup_requests" :min="0" :max="10000" controls-position="right" />
        </el-form-item>
        <el-form-item label="流式模式" prop="enable_stream">
          <el-switch v-model="form.enable_stream" active-text="开启" inactive-text="关闭" />
        </el-form-item>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">高级配置</h2>
      </div>
      <div class="section-body">
        <el-collapse>
          <el-collapse-item title="超时、重试和节流" name="advanced">
            <div class="grid-3">
              <el-form-item label="Temperature" prop="temperature">
                <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" controls-position="right" />
              </el-form-item>
              <el-form-item label="请求超时（秒）" prop="timeout_sec">
                <el-input-number v-model="form.timeout_sec" :min="1" controls-position="right" />
              </el-form-item>
              <el-form-item label="连接超时（秒）" prop="connect_timeout_sec">
                <el-input-number v-model="form.connect_timeout_sec" :min="1" controls-position="right" />
              </el-form-item>
              <el-form-item label="最大重试次数" prop="max_retries">
                <el-input-number v-model="form.max_retries" :min="0" controls-position="right" />
              </el-form-item>
              <el-form-item label="重试基础退避" prop="retry_backoff_base">
                <el-input-number v-model="form.retry_backoff_base" :min="0" :step="0.5" controls-position="right" />
              </el-form-item>
              <el-form-item label="重试最大退避" prop="retry_backoff_max">
                <el-input-number v-model="form.retry_backoff_max" :min="0" :step="0.5" controls-position="right" />
              </el-form-item>
              <el-form-item label="请求间隔（毫秒）" prop="think_time_ms">
                <el-input-number v-model="form.think_time_ms" :min="0" controls-position="right" />
              </el-form-item>
              <el-form-item v-if="form.api_protocol === 'anthropic'" label="Anthropic Version" prop="anthropic_version">
                <el-input v-model="form.anthropic_version" />
              </el-form-item>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">矩阵测试</h2>
        <el-switch v-model="form.matrix_mode" active-text="开启" inactive-text="关闭" />
      </div>
      <div v-if="form.matrix_mode" class="section-body grid-3">
        <el-form-item label="输入 Token 列表" prop="input_tokens_list">
          <el-input v-model="form.input_tokens_list" placeholder="1000,10000,100000" />
        </el-form-item>
        <el-form-item label="并发列表" prop="concurrency_list">
          <el-input v-model="form.concurrency_list" placeholder="10,50,100" />
        </el-form-item>
        <el-form-item label="单点时长（秒）" prop="matrix_duration_sec">
          <el-input-number v-model="form.matrix_duration_sec" :min="1" :max="86400" controls-position="right" />
        </el-form-item>
      </div>
    </div>

    <div class="form-actions">
      <el-button type="primary" :icon="VideoPlay" :loading="submitting" @click="submit">
        启动测试
      </el-button>
      <el-button :icon="RefreshLeft" @click="reset">恢复默认</el-button>
    </div>
  </el-form>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ChatLineRound, Connection, Cpu, RefreshLeft, VideoPlay } from '@element-plus/icons-vue'

const emit = defineEmits(['submit'])

const props = defineProps({
  submitting: {
    type: Boolean,
    default: false
  },
  initialConfig: {
    type: Object,
    default: null
  }
})

const defaults = {
  name: 'LLM API 性能测试',
  api_protocol: 'openai',
  anthropic_version: '2023-06-01',
  base_url: 'https://api.wenwen-ai.com',
  api_key: '',
  model: 'glm-5.1',
  endpoint: '/chat/completions',
  concurrency: 10,
  duration_sec: 60,
  input_tokens: 1000,
  max_output_tokens: 128,
  temperature: 0,
  timeout_sec: 600,
  connect_timeout_sec: 30,
  warmup_requests: 0,
  max_retries: 2,
  retry_backoff_base: 1,
  retry_backoff_max: 8,
  think_time_ms: 0,
  enable_stream: true,
  matrix_mode: false,
  input_tokens_list: '1000,10000',
  concurrency_list: '10,50',
  matrix_duration_sec: 60
}

const formRef = ref()
const form = reactive({ ...defaults, ...(props.initialConfig || {}) })
const lastProtocol = ref(form.api_protocol)
const tokenPreset = ref('1000')
const tokenOptions = [
  { label: '1k', value: '1000' },
  { label: '10k', value: '10000' },
  { label: '100k', value: '100000' }
]
const domainOptions = [
  {
    label: '国内节点',
    value: 'https://api.wenwen-ai.com'
  },
  {
    label: '海外节点',
    value: 'https://api.apipro.ai'
  }
]
const protocolDefaults = {
  openai: {
    stream_endpoint: '/chat/completions',
    non_stream_endpoint: '/chat/completions',
    model: defaults.model
  },
  anthropic: {
    stream_endpoint: '/messages',
    non_stream_endpoint: '/messages',
    model: 'claude-sonnet-4-20250514'
  },
  gemini: {
    stream_endpoint: '/models/{model}:streamGenerateContent?alt=sse',
    non_stream_endpoint: '/models/{model}:generateContent',
    model: 'gemini-2.5-pro'
  }
}
const protocolOptions = [
  {
    value: 'openai',
    label: 'OpenAI-compatible',
    description: '适配 GLM、Qwen、DeepSeek、OpenAI 兼容接口',
    endpoint: '/chat/completions',
    icon: Connection
  },
  {
    value: 'anthropic',
    label: 'Anthropic Messages',
    description: '使用 x-api-key 和 anthropic-version 请求头',
    endpoint: '/messages',
    icon: ChatLineRound
  },
  {
    value: 'gemini',
    label: 'Gemini API',
    description: '使用 x-goog-api-key 和 generateContent 协议',
    endpoint: '/models/{model}:generateContent',
    icon: Cpu
  }
]

const rules = {
  name: [{ required: true, message: '请输入测试名称', trigger: 'blur' }],
  api_protocol: [{ required: true, message: '请选择接口协议', trigger: 'change' }],
  base_url: [{ required: true, message: '请选择接入域名', trigger: 'change' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  endpoint: [{ required: true, message: '请输入 Endpoint', trigger: 'blur' }],
  input_tokens_list: [{ required: true, message: '请输入输入 Token 列表', trigger: 'blur' }],
  concurrency_list: [{ required: true, message: '请输入并发列表', trigger: 'blur' }]
}

const apiKeyLabel = computed(() => {
  if (form.api_protocol === 'anthropic') return 'Anthropic API Key'
  if (form.api_protocol === 'gemini') return 'Gemini API Key'
  return 'API Key'
})
const modelPlaceholder = computed(() => (
  protocolDefaults[form.api_protocol]?.model || defaults.model
))

function isKnownBaseUrl(value) {
  return domainOptions.some((item) => item.value === value)
}

function isKnownEndpoint(value) {
  return Object.values(protocolDefaults).some((item) => (
    item.stream_endpoint === value || item.non_stream_endpoint === value
  )) || value === '/responses'
}

function endpointFor(protocol, enableStream = form.enable_stream) {
  const item = protocolDefaults[protocol] || protocolDefaults.openai
  return enableStream ? item.stream_endpoint : item.non_stream_endpoint
}

watch(
  () => form.api_protocol,
  (protocol, previous) => {
    if (!protocol || protocol === previous) return
    const nextDefaults = protocolDefaults[protocol] || protocolDefaults.openai
    const previousDefaults = protocolDefaults[previous] || protocolDefaults[lastProtocol.value]

    if (!form.base_url || !isKnownBaseUrl(form.base_url)) {
      form.base_url = defaults.base_url
    }
    if (!form.endpoint || isKnownEndpoint(form.endpoint)) {
      form.endpoint = endpointFor(protocol)
    }
    if (
      !form.model ||
      form.model === previousDefaults?.model ||
      form.model === defaults.model ||
      form.model.startsWith('claude-') ||
      form.model.startsWith('gemini-')
    ) {
      form.model = nextDefaults.model
    }
    lastProtocol.value = protocol
  }
)

watch(
  () => form.enable_stream,
  (enabled) => {
    if (form.api_protocol !== 'gemini') return
    const gemini = protocolDefaults.gemini
    if (form.endpoint === gemini.stream_endpoint || form.endpoint === gemini.non_stream_endpoint) {
      form.endpoint = endpointFor('gemini', enabled)
    }
  }
)

function applyTokenPreset(value) {
  form.input_tokens = Number(value)
}

async function submit() {
  await formRef.value.validate()
  emit('submit', { ...form })
}

function reset() {
  Object.assign(form, defaults)
  tokenPreset.value = '1000'
  formRef.value?.clearValidate()
}
</script>

<style scoped>
.full-row {
  grid-column: 1 / -1;
}

.section-body-compact {
  padding-top: 0;
}

.inline-field {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  width: 100%;
}

.full-select {
  width: 100%;
}

.domain-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.domain-option code {
  color: #64748b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
}

.form-actions {
  position: sticky;
  bottom: 0;
  z-index: 10;
  display: flex;
  gap: 10px;
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 -10px 24px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(10px);
}

:deep(.el-input-number) {
  width: 100%;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
}

.provider-card {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 12px;
  min-height: 116px;
  padding: 14px;
  border: 1px solid #d8e0ec;
  border-radius: 8px;
  background: #ffffff;
  color: #1e293b;
  text-align: left;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 180ms ease;
}

.provider-card:hover {
  border-color: #93b4e8;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.provider-card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}

.provider-card.active {
  border-color: #2563eb;
  background: #f8fbff;
  box-shadow: 0 0 0 1px #2563eb inset, 0 12px 28px rgba(37, 99, 235, 0.12);
}

.provider-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 20px;
}

.provider-card.active .provider-icon {
  background: #2563eb;
  color: #ffffff;
}

.provider-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.provider-name {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.3;
}

.provider-desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.provider-endpoint {
  margin-top: auto;
  overflow: hidden;
  color: #475569;
  font-size: 11px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .provider-grid {
    grid-template-columns: 1fr;
  }
}
</style>
