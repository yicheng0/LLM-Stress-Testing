<template>
  <div class="doc-page">
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">官方 curl 转内部 curl</h2>
        <div class="toolbar">
          <el-button :icon="Back" @click="router.push('/dashboard/realtime')">返回实时面板</el-button>
          <el-button type="primary" :icon="CopyDocument" :disabled="!result?.sanitized_curl" @click="copyCurl">
            复制转换结果
          </el-button>
        </div>
      </div>
      <div class="section-body">
        <div class="doc-layout">
          <div class="doc-form">
            <div class="grid-2">
              <el-form-item label="目标接入域名">
                <el-select v-if="isRootUser" v-model="form.base_url" class="full-select">
                  <el-option label="国内节点" value="https://api.wenwen-ai.com" />
                  <el-option label="海外节点" value="https://api.apipro.ai" />
                </el-select>
                <el-input
                  v-else
                  v-model="form.base_url"
                  placeholder="请输入第三方域名，如 https://api.example.com"
                  @blur="trimBaseUrl"
                />
              </el-form-item>
              <el-form-item label="文档标题">
                <el-input v-model="form.title" maxlength="120" />
              </el-form-item>
            </div>

            <div class="template-row" role="list" aria-label="curl 模板">
              <button
                v-for="template in templates"
                :key="template.key"
                type="button"
                class="template-card"
                role="listitem"
                @click="applyTemplate(template)"
              >
                <span>{{ template.label }}</span>
                <strong>{{ template.endpoint }}</strong>
              </button>
            </div>

            <el-form-item label="官方 curl">
              <el-input
                v-model="form.curl"
                type="textarea"
                :rows="18"
                resize="vertical"
                spellcheck="false"
                class="curl-input"
                placeholder="粘贴官方 curl，例如 curl https://api.openai.com/v1/chat/completions ..."
              />
            </el-form-item>

            <div class="action-row">
              <el-button :icon="RefreshLeft" @click="reset">清空</el-button>
              <el-button type="primary" :icon="DocumentChecked" :loading="loading" @click="convert">
                生成可复制 curl
              </el-button>
            </div>
          </div>

          <div class="doc-preview">
            <div class="preview-card">
              <div class="preview-title">
                <strong>解析结果</strong>
                <el-tag v-if="result" effect="plain">{{ protocolLabel(result.protocol) }}</el-tag>
                <el-tag v-else effect="plain" type="info">等待生成</el-tag>
              </div>
              <div class="result-grid">
                <div>
                  <span>Method</span>
                  <code>{{ result?.method || '-' }}</code>
                </div>
                <div>
                  <span>Endpoint</span>
                  <code>{{ result?.endpoint || '-' }}</code>
                </div>
                <div>
                  <span>Model</span>
                  <code>{{ result?.model || '-' }}</code>
                </div>
                <div>
                  <span>Auth</span>
                  <code>{{ authLabel(result?.protocol) }}</code>
                </div>
              </div>
            </div>

            <div class="preview-card">
              <div class="preview-title">
                <strong>请求体字段</strong>
                <span class="muted">所有字段会原样保留到转换结果</span>
              </div>
              <div class="param-block">
                <span>Body 顶层字段</span>
                <div class="tag-list">
                  <el-tag v-for="item in result?.recognized_params || []" :key="item" type="success" effect="plain">
                    {{ item }}
                  </el-tag>
                  <em v-if="!result?.recognized_params?.length">生成后展示请求体字段。</em>
                </div>
              </div>
            </div>

            <div class="preview-card">
              <div class="preview-title">
                <strong>保留 Header</strong>
                <span class="muted">鉴权已脱敏，Content-Type 由请求体声明</span>
              </div>
              <div class="header-list">
                <div v-for="header in result?.headers || []" :key="header.name" class="header-row">
                  <code>{{ header.name }}</code>
                  <span>{{ header.value }}</span>
                </div>
                <em v-if="!result?.headers?.length">生成后展示安全保留的请求头。</em>
              </div>
            </div>

            <el-alert
              v-if="result?.warnings?.length"
              class="warning-box"
              title="复制前请确认"
              type="warning"
              :closable="false"
              show-icon
            >
              <ul>
                <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
              </ul>
            </el-alert>

            <div class="preview-card">
              <div class="preview-title">
                <strong>转换结果</strong>
                <el-button size="small" :icon="CopyDocument" :disabled="!result?.sanitized_curl" @click="copyCurl">
                  复制
                </el-button>
              </div>
              <pre class="code-box">{{ result?.sanitized_curl || '生成后展示脱敏 curl，API Key 会替换为 ${API_KEY}。' }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { Back, CopyDocument, DocumentChecked, RefreshLeft } from '@element-plus/icons-vue'
import { convertCurlToOpenApi } from '../api/client'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const result = ref(null)
const builtInDomainValues = ['https://api.wenwen-ai.com', 'https://api.apipro.ai']
const builtInDomainOrigins = new Set(builtInDomainValues.map((value) => normalizeBaseUrlOrigin(value)))
const storedCustomBaseUrl = String(localStorage.getItem('llm_stress_custom_base_url') || '').trim()
const isRootUser = computed(() => auth.role === 'root')

const form = reactive({
  base_url: isRootUser.value ? 'https://api.wenwen-ai.com' : (!isBuiltInDomain(storedCustomBaseUrl) ? storedCustomBaseUrl : ''),
  title: 'LLM API curl 转换',
  curl: ''
})

const templates = [
  {
    key: 'openai',
    label: 'OpenAI-compatible',
    endpoint: '/v1/chat/completions',
    curl: `curl https://api.openai.com/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: Bearer sk-official-demo' \\
  -d '{
    "model": "gpt-5.5",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello"}
    ],
    "temperature": 0.7,
    "max_tokens": 1024,
    "stream": true
  }'`
  },
  {
    key: 'anthropic',
    label: 'Anthropic',
    endpoint: '/messages',
    curl: `curl https://third-party.example.com/v1/messages \\
  -H 'Content-Type: application/json' \\
  -H 'x-api-key: sk-ant-official-demo' \\
  -H 'anthropic-version: 2023-06-01' \\
  -d '{
    "model": "claude-sonnet-4-6-20260218",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello"}
    ],
    "stream": true
  }'`
  },
  {
    key: 'gemini',
    label: 'Gemini',
    endpoint: '/v1beta/models/{model-name}:generateContent',
    curl: `curl https://third-party.example.com/v1beta/models/gemini-3.1-pro-preview:generateContent \\
  -H 'Content-Type: application/json' \\
  -H 'x-goog-api-key: official-demo-key' \\
  -d '{
    "contents": [
      {
        "parts": [{"text": "Hello"}]
      }
    ],
    "generationConfig": {
      "temperature": 0.7,
      "maxOutputTokens": 1024
    }
  }'`
  }
]

function applyTemplate(template) {
  form.curl = template.curl
  result.value = null
}

function reset() {
  form.curl = ''
  result.value = null
}

function trimBaseUrl() {
  form.base_url = String(form.base_url || '').trim()
  if (!isRootUser.value && form.base_url && !isBuiltInDomain(form.base_url)) {
    localStorage.setItem('llm_stress_custom_base_url', form.base_url)
  }
}

function normalizeBaseUrlOrigin(value) {
  const raw = String(value || '').trim()
  try {
    const parsed = new URL(raw)
    return `${parsed.protocol.toLowerCase()}//${parsed.host.toLowerCase()}`.replace(/\/$/, '')
  } catch {
    return raw.replace(/\/$/, '').toLowerCase()
  }
}

function isBuiltInDomain(value) {
  return builtInDomainOrigins.has(normalizeBaseUrlOrigin(value))
}

function validateBaseUrl() {
  trimBaseUrl()
  if (!form.base_url) {
    ElMessage.warning('请填写第三方接入域名')
    return false
  }
  if (!/^https?:\/\//i.test(form.base_url)) {
    ElMessage.warning('接入域名必须以 http:// 或 https:// 开头')
    return false
  }
  if (!isRootUser.value && isBuiltInDomain(form.base_url)) {
    ElMessage.warning('游客模式请填写第三方接入域名，不能使用内置节点')
    return false
  }
  try {
    const parsed = new URL(form.base_url)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) {
      ElMessage.warning('接入域名必须是合法 URL')
      return false
    }
  } catch {
    ElMessage.warning('接入域名必须是合法 URL，例如 https://api.example.com')
    return false
  }
  return true
}

async function convert() {
  if (!form.curl.trim()) {
    ElMessage.warning('请先粘贴官方 curl')
    return
  }
  if (!validateBaseUrl()) return
  loading.value = true
  try {
    result.value = await convertCurlToOpenApi({
      curl: form.curl,
      base_url: form.base_url,
      title: form.title || 'LLM API curl 转换'
    })
    ElMessage.success('可复制 curl 已生成')
  } catch (error) {
    ElMessage.error(error.message || '生成失败')
  } finally {
    loading.value = false
  }
}

function protocolLabel(protocol) {
  return {
    openai: 'OpenAI-compatible',
    anthropic: 'Anthropic Messages',
    gemini: 'Gemini API'
  }[protocol] || '-'
}

function authLabel(protocol) {
  return {
    openai: 'Authorization: Bearer ${API_KEY}',
    anthropic: 'x-api-key: ${API_KEY}',
    gemini: 'x-goog-api-key: ${API_KEY}'
  }[protocol] || '-'
}

async function copyCurl() {
  if (!result.value?.sanitized_curl) return
  await navigator.clipboard.writeText(result.value.sanitized_curl)
  ElMessage.success('已复制转换后的 curl')
}
</script>

<style scoped>
.doc-page {
  max-width: 1520px;
}

.doc-layout {
  display: grid;
  grid-template-columns: minmax(420px, 0.92fr) minmax(0, 1.08fr);
  gap: 16px;
  align-items: start;
}

.doc-form,
.doc-preview {
  min-width: 0;
}

.full-select {
  width: 100%;
}

.template-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.template-card {
  display: flex;
  min-height: 72px;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
  color: #1e293b;
  text-align: left;
}

.template-card:hover,
.template-card:focus-visible {
  border-color: #93b4e8;
  outline: none;
  box-shadow: var(--app-focus);
}

.template-card span {
  font-weight: 800;
}

.template-card strong {
  color: #64748b;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.curl-input :deep(textarea) {
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.preview-card {
  margin-bottom: 12px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.preview-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #edf2f7;
  background: #fbfdff;
}

.preview-title strong {
  font-size: 14px;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 14px;
}

.result-grid > div {
  min-width: 0;
  padding: 10px;
  border: 1px solid #edf2f7;
  border-radius: 8px;
  background: #f8fbff;
}

.result-grid span,
.param-block span {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}

.result-grid code {
  color: #1d4ed8;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.param-block {
  padding: 14px;
}

.header-list {
  display: grid;
  gap: 8px;
  padding: 14px;
}

.header-list em {
  color: #94a3b8;
  font-style: normal;
}

.header-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.38fr) minmax(0, 0.62fr);
  gap: 10px;
  align-items: start;
  padding: 10px;
  border: 1px solid #edf2f7;
  border-radius: 8px;
  background: #f8fbff;
}

.header-row code,
.header-row span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.header-row code {
  color: #1d4ed8;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
}

.header-row span {
  color: #334155;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 28px;
}

.tag-list em {
  color: #94a3b8;
  font-style: normal;
}

.warning-box {
  margin-bottom: 12px;
}

.warning-box ul {
  margin: 6px 0 0;
  padding-left: 18px;
}

.code-box {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  padding: 14px;
  background: #111827;
  color: #e2e8f0;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 1180px) {
  .doc-layout,
  .template-row,
  .result-grid,
  .param-block,
  .header-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .section-header,
  .toolbar,
  .action-row,
  .preview-title {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar,
  .action-row {
    width: 100%;
  }

  .toolbar :deep(.el-button),
  .action-row :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
