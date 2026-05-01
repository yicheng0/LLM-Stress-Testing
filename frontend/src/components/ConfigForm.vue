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
              <span v-if="form.api_protocol === option.value" class="provider-check">
                <el-icon><Check /></el-icon>
              </span>
              <span class="provider-icon">
                <el-icon><component :is="option.icon" /></el-icon>
              </span>
              <span class="provider-copy">
                <span class="provider-name">{{ option.label }}</span>
                <span class="provider-desc">{{ option.description }}</span>
                <span class="provider-meta">
                  <span class="provider-pill">{{ option.auth }}</span>
                  <span class="provider-endpoint mono">{{ endpointLabel(option.value) }}</span>
                </span>
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
        <div class="protocol-preview full-row" :class="{ warning: endpointMismatch }">
          <div class="preview-head">
            <div>
              <strong>协议请求预览</strong>
              <span>{{ endpointMismatch ? '当前 Endpoint 与所选协议常用路径不一致，请确认是否为自定义兼容接口。' : '启动前请确认 Header 和 Endpoint 是否符合目标服务。' }}</span>
            </div>
            <el-tag :type="endpointMismatch ? 'warning' : 'success'" effect="plain">
              {{ endpointMismatch ? '需要确认' : '配置匹配' }}
            </el-tag>
          </div>
          <div class="preview-grid">
            <div>
              <span>Method</span>
              <code>POST</code>
            </div>
            <div>
              <span>Resolved Endpoint</span>
              <code>{{ resolvedEndpoint }}</code>
            </div>
            <div>
              <span>Auth Header</span>
              <code>{{ selectedProtocol.auth }}</code>
            </div>
            <div v-if="form.api_protocol === 'anthropic'">
              <span>Anthropic Version</span>
              <code>{{ form.anthropic_version }}</code>
            </div>
            <div>
              <span>Stream</span>
              <code>{{ form.enable_stream ? 'enabled' : 'disabled' }}</code>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">负载配置</h2>
      </div>
      <div class="section-body preset-section">
        <div class="preset-head">
          <div>
            <h3>预设模板</h3>
            <p>选择后会更新负载、流式和矩阵参数，接口协议与密钥保持不变。</p>
          </div>
          <el-tag effect="plain">{{ selectedPresetLabel }}</el-tag>
        </div>
        <div class="preset-grid" role="list" aria-label="压测预设模板">
          <button
            v-for="preset in testPresets"
            :key="preset.key"
            type="button"
            class="preset-card"
            :class="{ active: activePresetKey === preset.key }"
            role="listitem"
            @click="applyPreset(preset)"
          >
            <span class="preset-title">{{ preset.label }}</span>
            <span class="preset-desc">{{ preset.description }}</span>
            <span class="preset-meta">
              <span>{{ preset.meta }}</span>
              <strong>{{ preset.matrix_mode ? '矩阵' : '单点' }}</strong>
            </span>
          </button>
        </div>
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
        <div class="matrix-derived-note full-row">
          以下预览根据上方输入 Token 列表、并发列表和单点时长实时计算。
        </div>
        <div class="matrix-preview full-row">
          <div>
            <span>当前组合数</span>
            <strong>{{ matrixPointCount }}</strong>
            <span>组</span>
          </div>
          <div>
            <span>估算总时长</span>
            <strong>{{ matrixEstimatedMinutes }}</strong>
            <span>分钟</span>
          </div>
          <div>
            <span>最高单点压力</span>
            <strong>{{ number(maxMatrixPressure) }}</strong>
            <span>Token x 并发</span>
          </div>
        </div>
        <div class="matrix-heatmap full-row">
          <div class="matrix-heatmap-header">
            <div>
              <h3>实时预览热力图</h3>
              <p>由当前表单自动推导：输入 Token x 并发，颜色越深表示该测试点压力越高。</p>
            </div>
            <el-tag effect="plain">预计压力量</el-tag>
          </div>
          <div class="matrix-heatmap-grid" :style="matrixGridStyle">
            <div class="matrix-corner">Token / 并发</div>
            <div v-for="concurrency in matrixConcurrencyValues" :key="`c-${concurrency}`" class="matrix-axis">
              {{ concurrency }}
            </div>
            <template v-for="inputTokens in matrixInputValues" :key="`row-${inputTokens}`">
              <div class="matrix-axis matrix-axis-y">{{ number(inputTokens) }}</div>
              <div
                v-for="concurrency in matrixConcurrencyValues"
                :key="`${inputTokens}-${concurrency}`"
                class="matrix-cell"
                :style="{
                  backgroundColor: pressureColor(inputTokens * concurrency),
                  color: pressureTextColor(inputTokens * concurrency)
                }"
              >
                <strong>{{ compactNumber(inputTokens * concurrency) }}</strong>
                <span>{{ compactNumber(inputTokens) }} x {{ concurrency }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <div class="form-actions">
      <div class="action-summary">
        <strong>{{ protocolText }} / {{ form.model || '未填写模型' }}</strong>
        <span>{{ form.matrix_mode ? `矩阵 ${matrixPointCount} 组` : `${form.concurrency} 并发 · ${form.duration_sec}s` }}</span>
      </div>
      <div class="action-buttons">
        <el-popover placement="top-end" trigger="click" :width="520">
          <template #reference>
            <el-button :icon="Document">参数预览</el-button>
          </template>
          <div class="config-preview">
            <div class="preview-title">
              <strong>预执行参数总览</strong>
              <span>真实 RPM/TPM/TPS 以完成后的报告为准</span>
            </div>
            <div class="preview-section">
              <h4>接口配置</h4>
              <div><span>协议</span><strong>{{ protocolText }}</strong></div>
              <div><span>认证</span><strong>{{ selectedProtocol.auth }}</strong></div>
              <div><span>Base URL</span><code>{{ form.base_url }}</code></div>
              <div><span>Endpoint</span><code>{{ form.endpoint }}</code></div>
              <div><span>模型</span><strong>{{ form.model || '-' }}</strong></div>
              <div><span>流式</span><strong>{{ form.enable_stream ? '开启' : '关闭' }}</strong></div>
            </div>
            <div class="preview-section">
              <h4>负载配置</h4>
              <div><span>模式</span><strong>{{ form.matrix_mode ? '矩阵测试' : '单点测试' }}</strong></div>
              <div><span>并发</span><strong>{{ form.matrix_mode ? matrixConcurrencyValues.join(', ') : form.concurrency }}</strong></div>
              <div><span>输入 Token</span><strong>{{ form.matrix_mode ? matrixInputValues.map(number).join(', ') : number(form.input_tokens) }}</strong></div>
              <div><span>最大输出</span><strong>{{ number(form.max_output_tokens) }} Token</strong></div>
              <div><span>单点时长</span><strong>{{ form.matrix_mode ? `${form.matrix_duration_sec}s` : `${form.duration_sec}s` }}</strong></div>
              <div><span>预热请求</span><strong>{{ number(form.warmup_requests) }}</strong></div>
            </div>
            <div class="preview-section">
              <h4>理论压力估算</h4>
              <div><span>组合数</span><strong>{{ matrixPointCount }} 组</strong></div>
              <div><span>估算总时长</span><strong>{{ estimatedTotalDurationText }}</strong></div>
              <div><span>理论 RPM</span><strong>{{ estimatedRpmText }}</strong></div>
              <div><span>理论 TPM</span><strong>{{ estimatedTpmText }}</strong></div>
              <div><span>理论 TPS</span><strong>{{ estimatedTpsText }}</strong></div>
              <div><span>单请求 Token</span><strong>{{ number(estimatedTokensPerRequest) }}</strong></div>
            </div>
          </div>
        </el-popover>
        <el-button :icon="RefreshLeft" @click="reset">恢复默认</el-button>
        <el-button type="primary" :icon="VideoPlay" :loading="submitting" @click="submit">
          启动测试
        </el-button>
      </div>
    </div>
  </el-form>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ChatLineRound, Check, Connection, Cpu, Document, RefreshLeft, VideoPlay } from '@element-plus/icons-vue'

const emit = defineEmits(['submit', 'change'])

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
const testPresets = [
  {
    key: 'quick',
    label: '快速验证',
    description: '用于连通性、鉴权和报告链路检查。',
    meta: '5 并发 / 30s / 1k',
    values: {
      name: '快速验证',
      concurrency: 5,
      duration_sec: 30,
      input_tokens: 1000,
      max_output_tokens: 128,
      warmup_requests: 0,
      enable_stream: true,
      matrix_mode: false,
      matrix_duration_sec: 60
    }
  },
  {
    key: 'small',
    label: '小流量',
    description: '低风险观察稳定性，适合作为基线。',
    meta: '20 并发 / 120s / 2k',
    values: {
      name: '小流量稳定性测试',
      concurrency: 20,
      duration_sec: 120,
      input_tokens: 2000,
      max_output_tokens: 256,
      warmup_requests: 2,
      enable_stream: true,
      matrix_mode: false,
      matrix_duration_sec: 60
    }
  },
  {
    key: 'throughput',
    label: '吞吐测试',
    description: '提高并发和持续时间，观察 RPM/TPM 上限。',
    meta: '200 并发 / 300s / 10k',
    values: {
      name: '吞吐上限测试',
      concurrency: 200,
      duration_sec: 300,
      input_tokens: 10000,
      max_output_tokens: 256,
      warmup_requests: 10,
      enable_stream: true,
      matrix_mode: false,
      matrix_duration_sec: 60
    }
  },
  {
    key: 'long-context',
    label: '长上下文测试',
    description: '验证大输入场景下的延迟、TTFT 和错误率。',
    meta: '20 并发 / 180s / 100k',
    values: {
      name: '长上下文测试',
      concurrency: 20,
      duration_sec: 180,
      input_tokens: 100000,
      max_output_tokens: 512,
      warmup_requests: 2,
      enable_stream: true,
      matrix_mode: false,
      matrix_duration_sec: 60
    }
  },
  {
    key: 'matrix',
    label: '矩阵测试',
    description: '组合输入规模和并发，生成容量对比结果。',
    meta: '3 x 3 / 每点 60s',
    values: {
      name: '矩阵容量测试',
      concurrency: 50,
      duration_sec: 60,
      input_tokens: 1000,
      max_output_tokens: 128,
      warmup_requests: 0,
      enable_stream: true,
      matrix_mode: true,
      input_tokens_list: '1000,10000,100000',
      concurrency_list: '10,50,100',
      matrix_duration_sec: 60
    }
  }
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
    auth: 'Authorization: Bearer',
    icon: Connection
  },
  {
    value: 'anthropic',
    label: 'Anthropic Messages',
    description: '使用 x-api-key 和 anthropic-version 请求头',
    endpoint: '/messages',
    auth: 'x-api-key',
    icon: ChatLineRound
  },
  {
    value: 'gemini',
    label: 'Gemini API',
    description: '使用 x-goog-api-key 和 generateContent 协议',
    endpoint: '/models/{model}:generateContent',
    auth: 'x-goog-api-key',
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
const selectedProtocol = computed(() => (
  protocolOptions.find((item) => item.value === form.api_protocol) || protocolOptions[0]
))
const protocolText = computed(() => selectedProtocol.value.label)
const resolvedEndpoint = computed(() => String(form.endpoint || '').replace('{model}', form.model || '{model}'))
const endpointMismatch = computed(() => {
  const expected = endpointFor(form.api_protocol)
  if (!form.endpoint || !expected) return false
  if (form.endpoint === expected) return false
  if (form.api_protocol === 'openai' && form.endpoint === '/responses') return false
  return isKnownEndpoint(form.endpoint)
})
const matrixPointCount = computed(() => {
  if (!form.matrix_mode) return 1
  const inputs = matrixInputValues.value
  const concurrency = matrixConcurrencyValues.value
  return Math.max(0, inputs.length * concurrency.length)
})
const matrixInputValues = computed(() => parseNumberList(form.input_tokens_list))
const matrixConcurrencyValues = computed(() => parseNumberList(form.concurrency_list))
const matrixEstimatedMinutes = computed(() => {
  const seconds = matrixPointCount.value * Number(form.matrix_duration_sec || 0)
  return number(seconds / 60)
})
const maxMatrixPressure = computed(() => Math.max(0, ...matrixInputValues.value.flatMap((inputTokens) => (
  matrixConcurrencyValues.value.map((concurrency) => inputTokens * concurrency)
))))
const matrixGridStyle = computed(() => ({
  gridTemplateColumns: `minmax(92px, 0.8fr) repeat(${Math.max(1, matrixConcurrencyValues.value.length)}, minmax(112px, 1fr))`
}))
const estimatedTokensPerRequest = computed(() => Number(form.input_tokens || 0) + Number(form.max_output_tokens || 0))
const estimatedSingleRpm = computed(() => {
  const duration = Number(form.duration_sec || 0)
  if (duration <= 0) return 0
  return Number(form.concurrency || 0) * 60 / duration
})
const estimatedSingleTpm = computed(() => estimatedSingleRpm.value * estimatedTokensPerRequest.value)
const estimatedSingleTps = computed(() => estimatedSingleTpm.value / 60)
const estimatedMatrixRpmRange = computed(() => {
  const duration = Number(form.matrix_duration_sec || 0)
  if (duration <= 0 || !matrixConcurrencyValues.value.length) return [0, 0]
  const values = matrixConcurrencyValues.value.map((item) => item * 60 / duration)
  return [Math.min(...values), Math.max(...values)]
})
const estimatedMatrixTpmRange = computed(() => {
  const [minRpm, maxRpm] = estimatedMatrixRpmRange.value
  if (!matrixInputValues.value.length) return [0, 0]
  const tokenValues = matrixInputValues.value.map((item) => item + Number(form.max_output_tokens || 0))
  return [minRpm * Math.min(...tokenValues), maxRpm * Math.max(...tokenValues)]
})
const estimatedMatrixTpsRange = computed(() => estimatedMatrixTpmRange.value.map((item) => item / 60))
const estimatedTotalDurationText = computed(() => {
  const seconds = form.matrix_mode
    ? matrixPointCount.value * Number(form.matrix_duration_sec || 0)
    : Number(form.duration_sec || 0)
  return `${number(seconds / 60)} 分钟`
})
const estimatedRpmText = computed(() => (
  form.matrix_mode ? rangeText(estimatedMatrixRpmRange.value) : number(estimatedSingleRpm.value)
))
const estimatedTpmText = computed(() => (
  form.matrix_mode ? rangeText(estimatedMatrixTpmRange.value) : number(estimatedSingleTpm.value)
))
const estimatedTpsText = computed(() => (
  form.matrix_mode ? rangeText(estimatedMatrixTpsRange.value) : number(estimatedSingleTps.value)
))
const activePresetKey = computed(() => {
  const match = testPresets.find((preset) => Object.entries(preset.values).every(([key, value]) => form[key] === value))
  return match?.key || ''
})
const selectedPresetLabel = computed(() => (
  testPresets.find((preset) => preset.key === activePresetKey.value)?.label || '自定义参数'
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

function endpointLabel(protocol) {
  return endpointFor(protocol, protocol === form.api_protocol ? form.enable_stream : true)
}

function parseList(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseNumberList(value) {
  return [...new Set(parseList(value)
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item) && item > 0))]
}

function pressureColor(value) {
  const ratio = pressureRatio(value)
  const lightness = 92 - ratio * 52
  const saturation = 72 + ratio * 10
  return `hsl(217, ${saturation.toFixed(1)}%, ${lightness.toFixed(1)}%)`
}

function pressureTextColor(value) {
  return pressureRatio(value) > 0.48 ? '#ffffff' : '#1e3a8a'
}

function pressureRatio(value) {
  const max = maxMatrixPressure.value || 1
  return Math.min(1, Math.max(0.08, value / max))
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function compactNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))
}

function rangeText(values) {
  const [min, max] = values
  if (!Number.isFinite(min) || !Number.isFinite(max)) return '-'
  if (min === max) return number(min)
  return `${number(min)} - ${number(max)}`
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

watch(
  form,
  () => emit('change', { ...form }),
  { deep: true, immediate: true }
)

function applyTokenPreset(value) {
  form.input_tokens = Number(value)
}

function applyPreset(preset) {
  Object.assign(form, preset.values)
  tokenPreset.value = tokenOptions.some((item) => Number(item.value) === Number(form.input_tokens))
    ? String(form.input_tokens)
    : ''
  formRef.value?.clearValidate([
    'concurrency',
    'duration_sec',
    'input_tokens',
    'max_output_tokens',
    'warmup_requests',
    'input_tokens_list',
    'concurrency_list',
    'matrix_duration_sec'
  ])
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

.preset-section {
  padding-bottom: 0;
}

.preset-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.preset-head h3 {
  margin: 0;
  color: #1e293b;
  font-size: 14px;
  font-weight: 800;
}

.preset-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.preset-card {
  display: flex;
  min-height: 124px;
  flex-direction: column;
  gap: 7px;
  padding: 13px;
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

.preset-card:hover {
  border-color: #93b4e8;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.preset-card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}

.preset-card.active {
  border-color: #2563eb;
  background: #f8fbff;
  box-shadow: 0 0 0 1px #2563eb inset;
}

.preset-title {
  font-size: 14px;
  font-weight: 800;
  line-height: 1.3;
}

.preset-desc {
  flex: 1;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.preset-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #475569;
  font-size: 11px;
  line-height: 1.4;
}

.preset-meta strong {
  flex: 0 0 auto;
  padding: 3px 7px;
  border-radius: 999px;
  background: #eef6ff;
  color: #1d4ed8;
  font-size: 11px;
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

.protocol-preview {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%);
}

.protocol-preview.warning {
  border-color: #fed7aa;
  background: linear-gradient(180deg, #fffaf3 0%, #fff7ed 100%);
}

.preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.preview-head div {
  display: grid;
  gap: 4px;
}

.preview-head strong {
  color: #1e293b;
  font-size: 14px;
}

.preview-head span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.preview-grid > div {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
}

.preview-grid span {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.preview-grid code {
  overflow: hidden;
  color: #1e293b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-actions {
  position: sticky;
  bottom: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 -10px 24px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(10px);
}

.action-summary {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  color: #1e293b;
  font-size: 13px;
}

.action-summary span {
  color: #64748b;
  font-size: 12px;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
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
  position: relative;
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

.provider-check {
  position: absolute;
  top: 10px;
  right: 10px;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #2563eb;
  color: #ffffff;
  font-size: 14px;
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
  overflow: hidden;
  color: #475569;
  font-size: 11px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-meta {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
}

.provider-pill {
  padding: 3px 7px;
  border-radius: 999px;
  background: #eef6ff;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
}

.matrix-preview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  min-height: 40px;
  padding: 10px 12px;
  border: 1px dashed #93b4e8;
  border-radius: 8px;
  background: #f8fbff;
  color: #64748b;
}

.matrix-derived-note {
  margin-top: -2px;
  padding: 9px 12px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}

.matrix-preview > div {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
}

.matrix-preview strong {
  color: #2563eb;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 18px;
}

.matrix-heatmap {
  min-width: 0;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.matrix-heatmap-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.matrix-heatmap-header h3 {
  margin: 0;
  color: #1e293b;
  font-size: 14px;
  font-weight: 800;
}

.matrix-heatmap-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.matrix-heatmap-grid {
  display: grid;
  min-width: 100%;
  overflow-x: auto;
  gap: 6px;
}

.matrix-corner,
.matrix-axis,
.matrix-cell {
  min-height: 44px;
  border-radius: 7px;
}

.matrix-corner,
.matrix-axis {
  display: grid;
  place-items: center;
  padding: 8px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.matrix-axis-y {
  justify-content: end;
  padding-right: 10px;
  font-family: "Fira Code", Consolas, monospace;
}

.matrix-cell {
  display: flex;
  min-width: 112px;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 9px 10px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.28);
}

.matrix-cell strong {
  font-family: "Fira Code", Consolas, monospace;
  font-size: 14px;
  line-height: 1.2;
}

.matrix-cell span {
  font-size: 11px;
  opacity: 0.9;
}

.config-preview {
  display: grid;
  gap: 12px;
}

.preview-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e5edf6;
}

.preview-title strong {
  color: #1e293b;
  font-size: 15px;
}

.preview-title span {
  color: #64748b;
  font-size: 12px;
}

.preview-section {
  display: grid;
  gap: 8px;
}

.preview-section h4 {
  margin: 0;
  color: #334155;
  font-size: 13px;
  font-weight: 800;
}

.preview-section > div {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
}

.preview-section span {
  color: #64748b;
}

.preview-section code,
.preview-section strong {
  min-width: 0;
  overflow: hidden;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .provider-grid {
    grid-template-columns: 1fr;
  }

  .preset-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .preview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .preset-grid {
    grid-template-columns: 1fr;
  }

  .matrix-preview {
    grid-template-columns: 1fr;
  }

  .matrix-heatmap {
    overflow-x: auto;
  }

  .form-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .preview-grid {
    grid-template-columns: 1fr;
  }

  .action-buttons,
  .action-buttons .el-button {
    width: 100%;
  }
}
</style>
