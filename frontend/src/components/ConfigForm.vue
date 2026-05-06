<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
    <div class="section mode-section">
      <div class="section-header">
        <h2 class="section-title">使用模式</h2>
        <el-segmented v-model="usageMode" :options="usageModeOptions" />
      </div>
      <div class="section-body">
        <div class="mode-grid">
          <div class="mode-card" :class="{ active: !isExpertMode }">
            <strong>新手模式</strong>
            <span>围绕目标 RPM 反推配置，只显示启动测试必需参数。</span>
          </div>
          <div class="mode-card" :class="{ active: isExpertMode }">
            <strong>专家模式</strong>
            <span>开放 Endpoint、高级重试、节流和矩阵容量测试参数。</span>
          </div>
        </div>
      </div>
    </div>

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
        <el-form-item v-if="isExpertMode" label="Endpoint" prop="endpoint">
          <el-input v-model="form.endpoint" placeholder="/v1/chat/completions" />
        </el-form-item>
        <el-form-item :label="apiKeyLabel" prop="api_key" class="full-row">
          <el-input v-model="form.api_key" type="password" show-password autocomplete="off" />
        </el-form-item>
        <div v-if="isExpertMode || endpointMismatch" class="protocol-preview full-row" :class="{ warning: endpointMismatch }">
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

    <div v-if="isExpertMode" class="section">
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
            v-for="preset in visibleTestPresets"
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
        <el-form-item label="单请求输入 Token 目标" prop="input_tokens">
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
        <h2 class="section-title">预期吞吐估算</h2>
        <div class="toolbar">
          <span class="muted">假设单请求平均耗时</span>
          <el-segmented v-model="assumedLatencySec" :options="latencyAssumptionOptions" />
        </div>
      </div>
      <div class="section-body">
        <div class="estimate-panel">
          <div class="estimate-cards">
            <div>
              <span>预期 RPM</span>
              <strong>{{ estimatedRpmText }}</strong>
              <em>{{ form.matrix_mode ? '矩阵区间' : '每分钟成功请求数' }}</em>
            </div>
            <div>
              <span>预期 TPM</span>
              <strong>{{ estimatedTpmText }}</strong>
              <em>{{ form.matrix_mode ? '矩阵区间' : '每分钟总 Token' }}</em>
            </div>
            <div>
              <span>预期 TPS</span>
              <strong>{{ estimatedTpsText }}</strong>
              <em>{{ form.matrix_mode ? '矩阵区间' : '每秒总 Token' }}</em>
            </div>
            <div>
              <span>单请求总 Token</span>
              <strong>{{ form.matrix_mode ? estimatedMatrixTokenRangeText : number(estimatedTokensPerRequest) }}</strong>
              <em>输入 + 最大输出</em>
            </div>
            <div>
              <span>预计请求数</span>
              <strong>{{ estimatedRequestCountText }}</strong>
              <em>{{ form.matrix_mode ? '矩阵所有测试点' : '当前测试时长内' }}</em>
            </div>
            <div>
              <span>预计总 Token</span>
              <strong>{{ estimatedTotalTokensText }}</strong>
              <em>{{ form.matrix_mode ? '按矩阵区间粗估' : '请求数 x 单请求 Token' }}</em>
            </div>
            <div>
              <span>预计输入 Token</span>
              <strong>{{ estimatedInputTokensText }}</strong>
              <em>{{ form.matrix_mode ? '矩阵所有测试点' : '系统自动生成测试 prompt' }}</em>
            </div>
            <div>
              <span>预计输出 Token 上限</span>
              <strong>{{ estimatedOutputTokensText }}</strong>
              <em>按最大输出 Token 粗估</em>
            </div>
          </div>
          <div class="consumption-panel" :class="consumptionRisk.type">
            <div>
              <span>启动前消耗风险</span>
              <strong>{{ consumptionRisk.label }}</strong>
              <em>{{ consumptionRisk.description }}</em>
            </div>
            <el-tag :type="consumptionRisk.tagType" effect="plain">{{ consumptionRisk.level }}</el-tag>
          </div>
          <el-alert
            class="estimate-note"
            title="这是启动前预期，不是服务承诺"
            :description="estimateFormulaText"
            type="info"
            show-icon
            :closable="false"
          />
          <div class="target-estimator" :class="{ disabled: form.matrix_mode }">
            <div class="target-head">
              <div>
                <h3>按预期反推测试参数</h3>
                <p>{{ isExpertMode ? '选择目标模式和 Token 规模，点击应用后会同步修改上方真实测试参数。' : '填写目标 RPM、单请求输入 Token 目标和预计耗时，系统会反推并发与预期 TPM。' }}</p>
              </div>
              <el-tag :type="form.matrix_mode ? 'warning' : 'success'" effect="plain">
                {{ form.matrix_mode ? '矩阵模式不可用' : '单点测试可同步' }}
              </el-tag>
            </div>
            <div class="target-presets" role="list" aria-label="预期吞吐目标模板">
              <button
                v-for="preset in visibleThroughputTargets"
                :key="preset.key"
                type="button"
                class="target-preset"
                :class="{ active: activeTargetKey === preset.key }"
                :disabled="form.matrix_mode"
                role="listitem"
                @click="applyThroughputTarget(preset)"
              >
                <span>{{ preset.label }}</span>
                <strong>{{ targetPresetMainText(preset) }}</strong>
                <em>{{ preset.input_tokens.toLocaleString() }} in / {{ preset.max_output_tokens }} out / {{ preset.assumed_latency_sec }}s</em>
              </button>
            </div>
            <div v-if="isExpertMode" class="target-mode-row">
              <span>反推模式</span>
              <el-segmented
                v-model="targetEstimate.mode"
                :options="targetModeOptions"
                :disabled="form.matrix_mode"
              />
            </div>
            <div class="target-grid">
              <el-form-item v-if="targetEstimate.mode === 'rpm'" label="目标 RPM">
                <el-input-number
                  v-model="targetEstimate.rpm"
                  :min="1"
                  :max="1000000"
                  :step="100"
                  controls-position="right"
                  :disabled="form.matrix_mode"
                />
              </el-form-item>
              <el-form-item v-else label="目标 TPM">
                <el-input-number
                  v-model="targetEstimate.tpm"
                  :min="1"
                  :max="10000000000"
                  :step="100000"
                  controls-position="right"
                  :disabled="form.matrix_mode"
                />
              </el-form-item>
              <el-form-item label="假设单请求耗时">
                <el-segmented
                  v-model="targetEstimate.latencySec"
                  :options="latencyAssumptionOptions"
                  :disabled="form.matrix_mode"
                />
              </el-form-item>
              <el-form-item label="单请求输入 Token 目标">
                <el-input-number
                  v-model="targetEstimate.inputTokens"
                  :min="1"
                  :step="1000"
                  controls-position="right"
                  :disabled="form.matrix_mode"
                />
              </el-form-item>
              <el-form-item label="最大输出 Token">
                <el-input-number
                  v-model="targetEstimate.outputTokens"
                  :min="1"
                  :max="65536"
                  :step="128"
                  controls-position="right"
                  :disabled="form.matrix_mode"
                />
              </el-form-item>
              <el-form-item label="应用后测试时长">
                <el-input-number
                  v-model="targetEstimate.durationSec"
                  :min="1"
                  :max="86400"
                  :step="30"
                  controls-position="right"
                  :disabled="form.matrix_mode"
                />
              </el-form-item>
            </div>
            <div class="target-summary-grid">
              <div>
                <span>目标 RPM</span>
                <strong>{{ targetRpmText }}</strong>
                <em>反推后的每分钟请求数</em>
              </div>
              <div>
                <span>目标 TPM</span>
                <strong>{{ targetTpmText }}</strong>
                <em>目标 RPM x 单请求总 Token</em>
              </div>
              <div>
                <span>目标 TPS</span>
                <strong>{{ targetTpsText }}</strong>
                <em>目标 TPM / 60</em>
              </div>
              <div>
                <span>预计总 Token</span>
                <strong>{{ estimatedTotalTokensText }}</strong>
                <em>{{ estimatedRequestCountText }} 请求，跟随上方真实配置</em>
              </div>
            </div>
            <div class="target-result">
              <div>
                <span>将同步并发数</span>
                <strong>{{ targetConcurrencyText }}</strong>
                <em>并发 ≈ 目标 RPM x 单请求耗时 / 60</em>
              </div>
              <div>
                <span>配置解释</span>
                <strong>{{ targetExplanation }}</strong>
                <em>真实结果会受限流、重试、网络和模型速度影响</em>
              </div>
              <el-button
                type="primary"
                :disabled="form.matrix_mode"
                @click="applyTargetEstimate"
              >
                应用到测试参数
              </el-button>
            </div>
            <div v-if="targetRiskItems.length" class="target-risk-list">
              <el-alert
                v-for="item in targetRiskItems"
                :key="item.title"
                :title="item.title"
                :description="item.description"
                :type="item.type"
                show-icon
                :closable="false"
              />
            </div>
            <el-alert
              v-if="form.matrix_mode"
              title="矩阵测试请使用下方输入 Token 列表和并发列表"
              description="反推配置只面向单点测试，避免覆盖矩阵里的多组测试组合。"
              type="warning"
              show-icon
              :closable="false"
            />
          </div>
        </div>
      </div>
    </div>

    <div v-if="isExpertMode || form.matrix_mode" class="section">
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

    <div v-if="isExpertMode" class="section">
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
              <div><span>输入 Token 目标</span><strong>{{ form.matrix_mode ? matrixInputValues.map(number).join(', ') : number(form.input_tokens) }}</strong></div>
              <div><span>最大输出</span><strong>{{ number(form.max_output_tokens) }} Token</strong></div>
              <div><span>单点时长</span><strong>{{ form.matrix_mode ? `${form.matrix_duration_sec}s` : `${form.duration_sec}s` }}</strong></div>
              <div><span>预热请求</span><strong>{{ number(form.warmup_requests) }}</strong></div>
            </div>
            <div class="preview-section">
              <h4>预期吞吐估算</h4>
              <div><span>组合数</span><strong>{{ matrixPointCount }} 组</strong></div>
              <div><span>估算总时长</span><strong>{{ estimatedTotalDurationText }}</strong></div>
              <div><span>假设耗时</span><strong>{{ assumedLatencySec }}s / 请求</strong></div>
              <div><span>预期 RPM</span><strong>{{ estimatedRpmText }}</strong></div>
              <div><span>预期 TPM</span><strong>{{ estimatedTpmText }}</strong></div>
              <div><span>预期 TPS</span><strong>{{ estimatedTpsText }}</strong></div>
              <div><span>单请求 Token</span><strong>{{ number(estimatedTokensPerRequest) }}</strong></div>
              <div><span>预计输入</span><strong>{{ estimatedInputTokensText }}</strong></div>
              <div><span>预计输出上限</span><strong>{{ estimatedOutputTokensText }}</strong></div>
              <div><span>消耗风险</span><strong>{{ consumptionRisk.label }}</strong></div>
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
import { ElMessage } from 'element-plus'

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
  model: 'gpt-5.5',
  endpoint: '/v1/chat/completions',
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
const assumedLatencySec = ref(10)
const usageMode = ref('beginner')
const targetEstimate = reactive({
  mode: 'rpm',
  rpm: 300,
  tpm: 338400,
  latencySec: 10,
  inputTokens: 1000,
  outputTokens: 128,
  durationSec: 120
})
const tokenOptions = [
  { label: '1k', value: '1000' },
  { label: '10k', value: '10000' },
  { label: '100k', value: '100000' }
]
const latencyAssumptionOptions = [
  { label: '2s', value: 2 },
  { label: '5s', value: 5 },
  { label: '10s', value: 10 },
  { label: '30s', value: 30 },
  { label: '60s', value: 60 }
]
const targetModeOptions = [
  { label: '按 RPM 目标', value: 'rpm' },
  { label: '按 TPM 目标', value: 'tpm' }
]
const usageModeOptions = [
  { label: '新手模式', value: 'beginner' },
  { label: '专家模式', value: 'expert' }
]
const throughputTargets = [
  {
    key: 'connectivity',
    label: '连通性验证',
    mode: 'rpm',
    target_rpm: 60,
    target_tpm: null,
    assumed_latency_sec: 5,
    input_tokens: 1000,
    max_output_tokens: 128,
    duration_sec: 30
  },
  {
    key: 'small-observe',
    label: '小流量观察',
    mode: 'rpm',
    target_rpm: 300,
    target_tpm: null,
    assumed_latency_sec: 10,
    input_tokens: 2000,
    max_output_tokens: 256,
    duration_sec: 120
  },
  {
    key: 'throughput-probe',
    label: '请求吞吐摸底',
    mode: 'rpm',
    target_rpm: 1200,
    target_tpm: null,
    assumed_latency_sec: 10,
    input_tokens: 10000,
    max_output_tokens: 256,
    duration_sec: 300
  },
  {
    key: 'token-throughput',
    label: 'Token 吞吐摸底',
    mode: 'tpm',
    target_rpm: null,
    target_tpm: 10000000,
    assumed_latency_sec: 10,
    input_tokens: 10000,
    max_output_tokens: 256,
    duration_sec: 300
  },
  {
    key: 'long-context',
    label: '长上下文稳定性',
    mode: 'rpm',
    target_rpm: 120,
    target_tpm: null,
    assumed_latency_sec: 30,
    input_tokens: 100000,
    max_output_tokens: 512,
    duration_sec: 300
  }
]
const testPresets = [
  {
    key: 'quick',
    label: '快速验证',
    description: '用于连通性和报告链路检查。',
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
    stream_endpoint: '/v1/chat/completions',
    non_stream_endpoint: '/v1/chat/completions',
    model: defaults.model
  },
  anthropic: {
    stream_endpoint: '/v1/messages',
    non_stream_endpoint: '/v1/messages',
    model: 'claude-sonnet-4-6-20260218'
  },
  gemini: {
    stream_endpoint: '/v1beta/models/{model-name}:streamGenerateContent?alt=sse',
    non_stream_endpoint: '/v1beta/models/{model-name}:generateContent',
    model: 'gemini-3.1-pro-preview'
  }
}
const protocolOptions = [
  {
    value: 'openai',
    label: 'OpenAI-compatible',
    description: '适配 GLM、Qwen、DeepSeek、OpenAI 兼容接口',
    endpoint: '/v1/chat/completions',
    auth: 'Authorization: Bearer',
    icon: Connection
  },
  {
    value: 'anthropic',
    label: 'Anthropic Messages',
    description: '使用 x-api-key 和 anthropic-version 请求头',
    endpoint: '/v1/messages',
    auth: 'x-api-key',
    icon: ChatLineRound
  },
  {
    value: 'gemini',
    label: 'Gemini API',
    description: '使用 x-goog-api-key 和 generateContent 协议',
    endpoint: '/v1beta/models/{model-name}:generateContent',
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
const isExpertMode = computed(() => usageMode.value === 'expert')
const visibleTestPresets = computed(() => (
  isExpertMode.value ? testPresets : testPresets.filter((preset) => preset.key !== 'matrix')
))
const visibleThroughputTargets = computed(() => (
  isExpertMode.value ? throughputTargets : throughputTargets.filter((preset) => preset.mode === 'rpm')
))
const protocolText = computed(() => selectedProtocol.value.label)
const resolvedEndpoint = computed(() => String(form.endpoint || '')
  .replace('{model-name}', form.model || '{model-name}')
  .replace('{model}', form.model || '{model}'))
const endpointMismatch = computed(() => {
  const expected = endpointFor(form.api_protocol)
  if (!form.endpoint || !expected) return false
  if (form.endpoint === expected) return false
  if (form.api_protocol === 'openai' && ['/responses', '/v1/responses'].includes(form.endpoint)) return false
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
const effectiveAssumedLatencySec = computed(() => (
  Math.max(0.001, Number(assumedLatencySec.value || 10) + Number(form.think_time_ms || 0) / 1000)
))
const estimatedSingleRpm = computed(() => {
  return Number(form.concurrency || 0) / effectiveAssumedLatencySec.value * 60
})
const estimatedSingleTpm = computed(() => estimatedSingleRpm.value * estimatedTokensPerRequest.value)
const estimatedSingleTps = computed(() => estimatedSingleTpm.value / 60)
const estimatedSingleRequestCount = computed(() => (
  estimatedSingleRpm.value * Number(form.duration_sec || 0) / 60
))
const estimatedSingleTotalTokens = computed(() => estimatedSingleRequestCount.value * estimatedTokensPerRequest.value)
const estimatedSingleInputTokens = computed(() => estimatedSingleRequestCount.value * Number(form.input_tokens || 0))
const estimatedSingleOutputTokenLimit = computed(() => estimatedSingleRequestCount.value * Number(form.max_output_tokens || 0))
const estimatedMatrixRpmRange = computed(() => {
  if (!matrixConcurrencyValues.value.length) return [0, 0]
  const values = matrixConcurrencyValues.value.map((item) => item / effectiveAssumedLatencySec.value * 60)
  return [Math.min(...values), Math.max(...values)]
})
const estimatedMatrixTpmRange = computed(() => {
  const [minRpm, maxRpm] = estimatedMatrixRpmRange.value
  if (!matrixInputValues.value.length) return [0, 0]
  const tokenValues = matrixInputValues.value.map((item) => item + Number(form.max_output_tokens || 0))
  return [minRpm * Math.min(...tokenValues), maxRpm * Math.max(...tokenValues)]
})
const estimatedMatrixTpsRange = computed(() => estimatedMatrixTpmRange.value.map((item) => item / 60))
const estimatedMatrixRequestCount = computed(() => (
  matrixConcurrencyValues.value.reduce((sum, concurrency) => (
    sum + (concurrency / effectiveAssumedLatencySec.value * 60) * Number(form.matrix_duration_sec || 0) / 60 * matrixInputValues.value.length
  ), 0)
))
const estimatedMatrixTotalTokens = computed(() => {
  if (!matrixInputValues.value.length || !matrixConcurrencyValues.value.length) return 0
  return matrixInputValues.value.reduce((sum, inputTokens) => (
    sum + matrixConcurrencyValues.value.reduce((innerSum, concurrency) => {
      const rpm = concurrency / effectiveAssumedLatencySec.value * 60
      const requests = rpm * Number(form.matrix_duration_sec || 0) / 60
      return innerSum + requests * (inputTokens + Number(form.max_output_tokens || 0))
    }, 0)
  ), 0)
})
const estimatedMatrixInputTokens = computed(() => {
  if (!matrixInputValues.value.length || !matrixConcurrencyValues.value.length) return 0
  return matrixInputValues.value.reduce((sum, inputTokens) => (
    sum + matrixConcurrencyValues.value.reduce((innerSum, concurrency) => {
      const rpm = concurrency / effectiveAssumedLatencySec.value * 60
      const requests = rpm * Number(form.matrix_duration_sec || 0) / 60
      return innerSum + requests * inputTokens
    }, 0)
  ), 0)
})
const estimatedMatrixOutputTokenLimit = computed(() => (
  estimatedMatrixRequestCount.value * Number(form.max_output_tokens || 0)
))
const estimatedMatrixTokenRange = computed(() => {
  if (!matrixInputValues.value.length) return [0, 0]
  const tokenValues = matrixInputValues.value.map((item) => item + Number(form.max_output_tokens || 0))
  return [Math.min(...tokenValues), Math.max(...tokenValues)]
})
const estimatedMatrixTokenRangeText = computed(() => rangeText(estimatedMatrixTokenRange.value))
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
const estimatedRequestCountText = computed(() => (
  number(form.matrix_mode ? estimatedMatrixRequestCount.value : estimatedSingleRequestCount.value)
))
const estimatedTotalTokensText = computed(() => (
  compactNumber(form.matrix_mode ? estimatedMatrixTotalTokens.value : estimatedSingleTotalTokens.value)
))
const estimatedInputTokens = computed(() => (
  form.matrix_mode ? estimatedMatrixInputTokens.value : estimatedSingleInputTokens.value
))
const estimatedOutputTokenLimit = computed(() => (
  form.matrix_mode ? estimatedMatrixOutputTokenLimit.value : estimatedSingleOutputTokenLimit.value
))
const estimatedInputTokensText = computed(() => compactNumber(estimatedInputTokens.value))
const estimatedOutputTokensText = computed(() => compactNumber(estimatedOutputTokenLimit.value))
const consumptionRisk = computed(() => {
  const totalTokens = Number(form.matrix_mode ? estimatedMatrixTotalTokens.value : estimatedSingleTotalTokens.value)
  const concurrency = Number(form.matrix_mode ? Math.max(0, ...matrixConcurrencyValues.value) : form.concurrency || 0)
  if (totalTokens >= 100000000 || concurrency >= 500) {
    return {
      level: '极高消耗',
      label: '建议先降压验证',
      description: '预计消耗或并发很高，启动前请确认配额、预算和目标 API 限流。',
      type: 'danger',
      tagType: 'danger'
    }
  }
  if (totalTokens >= 10000000 || concurrency >= 200) {
    return {
      level: '高消耗',
      label: '需要确认配额',
      description: '适合正式压测，建议先完成小流量验证再启动。',
      type: 'warning',
      tagType: 'warning'
    }
  }
  if (totalTokens >= 1000000 || concurrency >= 50) {
    return {
      level: '注意消耗',
      label: '适合小流量观察',
      description: '预计消耗可控，但仍建议关注实时成功率和延迟。',
      type: 'info',
      tagType: 'info'
    }
  }
  return {
    level: '低风险',
    label: '适合快速验证',
    description: '预计 Token 和并发较低，适合先验证连通性和报告链路。',
    type: 'ok',
    tagType: 'success'
  }
})
const targetRpm = computed(() => {
  if (targetEstimate.mode === 'tpm') {
    const tokens = targetTokensPerRequest.value || 1
    return Number(targetEstimate.tpm || 0) / tokens
  }
  return Number(targetEstimate.rpm || 0)
})
const targetConcurrency = computed(() => {
  const rpm = targetRpm.value
  const latency = Number(targetEstimate.latencySec || 0)
  if (!Number.isFinite(rpm) || !Number.isFinite(latency) || rpm <= 0 || latency <= 0) return 1
  return Math.min(1000, Math.max(1, Math.ceil((rpm * latency) / 60)))
})
const targetRawConcurrency = computed(() => {
  const rpm = targetRpm.value
  const latency = Number(targetEstimate.latencySec || 0)
  if (!Number.isFinite(rpm) || !Number.isFinite(latency) || rpm <= 0 || latency <= 0) return 1
  return Math.max(1, Math.ceil((rpm * latency) / 60))
})
const targetTokensPerRequest = computed(() => (
  Number(targetEstimate.inputTokens || 0) + Number(targetEstimate.outputTokens || 0)
))
const targetTpm = computed(() => (
  targetEstimate.mode === 'tpm'
    ? Number(targetEstimate.tpm || 0)
    : targetRpm.value * targetTokensPerRequest.value
))
const targetTps = computed(() => targetTpm.value / 60)
const targetRpmText = computed(() => number(targetRpm.value))
const targetConcurrencyText = computed(() => {
  const concurrency = targetConcurrency.value
  const suffix = targetRawConcurrency.value > 1000 ? '（已按表单上限截断）' : ''
  return `${number(concurrency)}${suffix}`
})
const targetTpmText = computed(() => number(targetTpm.value))
const targetTpsText = computed(() => number(targetTps.value))
const targetExplanation = computed(() => (
  `${number(targetConcurrency.value)} 并发打 ${number(targetRpm.value)} RPM`
))
const targetRiskItems = computed(() => {
  if (form.matrix_mode) return []
  const items = []
  if (targetRawConcurrency.value > 1000) {
    items.push({
      title: '目标超过表单并发上限',
      description: `按当前目标需要约 ${number(targetRawConcurrency.value)} 并发，应用时会按 1000 并发截断，真实 RPM/TPM 可能达不到预期。`,
      type: 'warning'
    })
  }
  if (targetConcurrency.value >= 500) {
    items.push({
      title: '目标并发较高',
      description: '建议先用较低目标确认成功率和延迟，再逐步提高吞吐目标。',
      type: 'warning'
    })
  }
  if (targetTpm.value >= 10000000) {
    items.push({
      title: '目标 TPM 较高',
      description: 'Token 吞吐目标越高，越容易受到模型速度、配额和网关限流影响。',
      type: 'warning'
    })
  }
  if (Number(targetEstimate.inputTokens || 0) >= 50000) {
    items.push({
      title: '输入 Token 很大',
      description: '长上下文会显著拉高 TTFT 和成本，建议保持较长测试时长观察稳定性。',
      type: 'info'
    })
  }
  const estimatedTotalTokens = form.matrix_mode ? estimatedMatrixTotalTokens.value : estimatedSingleTotalTokens.value
  if (estimatedTotalTokens >= 100000000) {
    items.push({
      title: '预计总 Token 消耗较大',
      description: '启动前请确认账号配额、预算和目标 API 的限流策略。',
      type: 'warning'
    })
  }
  return items
})
const expectedMetrics = computed(() => {
  const rpm = form.matrix_mode ? null : estimatedSingleRpm.value
  const tpm = form.matrix_mode ? null : estimatedSingleTpm.value
  const tps = form.matrix_mode ? null : estimatedSingleTps.value
  const duration = form.matrix_mode
    ? matrixPointCount.value * Number(form.matrix_duration_sec || 0)
    : Number(form.duration_sec || 0)
  const requests = form.matrix_mode ? estimatedMatrixRequestCount.value : estimatedSingleRequestCount.value
  const tokens = form.matrix_mode ? estimatedMatrixTotalTokens.value : estimatedSingleTotalTokens.value
  return {
    mode: form.matrix_mode ? 'matrix_estimate' : targetEstimate.mode,
    expected_rpm: rpm,
    expected_tpm: tpm,
    expected_tps: tps,
    expected_latency_sec: Number(assumedLatencySec.value || 10),
    expected_requests: requests,
    expected_total_tokens: tokens,
    expected_input_token_total: estimatedInputTokens.value,
    expected_output_token_limit: estimatedOutputTokenLimit.value,
    expected_consumption_risk: consumptionRisk.value.level,
    expected_tokens_per_request: form.matrix_mode ? null : estimatedTokensPerRequest.value,
    expected_input_tokens: form.matrix_mode ? null : Number(form.input_tokens || 0),
    expected_output_tokens: form.matrix_mode ? null : Number(form.max_output_tokens || 0),
    expected_duration_sec: duration,
    source: 'web_config_estimator'
  }
})
const estimateFormulaText = computed(() => {
  const base = `按 ${assumedLatencySec.value}s 平均请求耗时`
  const thinkTime = Number(form.think_time_ms || 0)
  const suffix = thinkTime > 0 ? ` + ${thinkTime}ms 请求间隔` : ''
  return `${base}${suffix} 估算：RPM ≈ 并发 / 单请求耗时 x 60；TPM ≈ RPM x 单请求总 Token。真实值会受模型速度、限流、重试、网络和输出长度影响。`
})
const activePresetKey = computed(() => {
  const match = testPresets.find((preset) => Object.entries(preset.values).every(([key, value]) => form[key] === value))
  return match?.key || ''
})
const selectedPresetLabel = computed(() => (
  testPresets.find((preset) => preset.key === activePresetKey.value)?.label || '自定义参数'
))
const activeTargetKey = computed(() => {
  const match = throughputTargets.find((preset) => (
    targetEstimate.mode === preset.mode &&
    (preset.mode === 'tpm' || Number(targetEstimate.rpm) === preset.target_rpm) &&
    (preset.mode !== 'tpm' || Number(targetEstimate.tpm) === preset.target_tpm) &&
    Number(targetEstimate.latencySec) === preset.assumed_latency_sec &&
    Number(targetEstimate.inputTokens) === preset.input_tokens &&
    Number(targetEstimate.outputTokens) === preset.max_output_tokens &&
    Number(targetEstimate.durationSec) === preset.duration_sec
  ))
  return match?.key || ''
})

function isKnownBaseUrl(value) {
  return domainOptions.some((item) => item.value === value)
}

function isKnownEndpoint(value) {
  return Object.values(protocolDefaults).some((item) => (
    item.stream_endpoint === value || item.non_stream_endpoint === value
  )) || ['/responses', '/v1/responses'].includes(value)
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

function targetPresetMainText(preset) {
  if (preset.mode === 'tpm') return `${number(preset.target_tpm)} TPM`
  return `${number(preset.target_rpm)} RPM`
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
  usageMode,
  (mode) => {
    if (mode !== 'beginner') return
    form.matrix_mode = false
    targetEstimate.mode = 'rpm'
  }
)

watch(
  () => form.duration_sec,
  (value) => {
    if (form.matrix_mode) return
    targetEstimate.durationSec = Number(value || 60)
  },
  { immediate: true }
)

watch(
  () => form.input_tokens,
  (value) => {
    if (form.matrix_mode) return
    targetEstimate.inputTokens = Number(value || 1)
    syncTokenPreset()
  },
  { immediate: true }
)

watch(
  () => form.max_output_tokens,
  (value) => {
    if (form.matrix_mode) return
    targetEstimate.outputTokens = Number(value || 1)
  },
  { immediate: true }
)

watch(
  estimatedSingleRpm,
  (value) => {
    if (form.matrix_mode || targetEstimate.mode !== 'rpm') return
    targetEstimate.rpm = Math.max(1, Math.round(Number(value || 1)))
  },
  { immediate: true }
)

watch(
  estimatedSingleTpm,
  (value) => {
    if (form.matrix_mode || targetEstimate.mode !== 'tpm') return
    targetEstimate.tpm = Math.max(1, Math.round(Number(value || 1)))
  },
  { immediate: true }
)

watch(
  form,
  () => emit('change', { ...form }),
  { deep: true, immediate: true }
)

function applyTokenPreset(value) {
  form.input_tokens = Number(value)
}

function syncTokenPreset() {
  tokenPreset.value = tokenOptions.some((item) => Number(item.value) === Number(form.input_tokens))
    ? String(form.input_tokens)
    : ''
}

function applyPreset(preset) {
  Object.assign(form, preset.values)
  syncTokenPreset()
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

function applyThroughputTarget(preset) {
  Object.assign(targetEstimate, {
    mode: preset.mode,
    rpm: preset.target_rpm || targetEstimate.rpm,
    tpm: preset.target_tpm || targetEstimate.tpm,
    latencySec: preset.assumed_latency_sec,
    inputTokens: preset.input_tokens,
    outputTokens: preset.max_output_tokens,
    durationSec: preset.duration_sec
  })
}

function applyTargetEstimate() {
  if (form.matrix_mode) return
  form.concurrency = targetConcurrency.value
  form.duration_sec = Number(targetEstimate.durationSec || 60)
  form.input_tokens = Number(targetEstimate.inputTokens || 1)
  form.max_output_tokens = Number(targetEstimate.outputTokens || 1)
  assumedLatencySec.value = Number(targetEstimate.latencySec || 10)
  syncTokenPreset()
  ElMessage.success('已同步并发、时长、Token 和耗时假设到测试参数')
  formRef.value?.clearValidate([
    'concurrency',
    'duration_sec',
    'input_tokens',
    'max_output_tokens'
  ])
}

async function submit() {
  await formRef.value.validate()
  emit('submit', { ...form, expected_metrics: expectedMetrics.value })
}

function reset() {
  Object.assign(form, defaults)
  tokenPreset.value = '1000'
  usageMode.value = 'beginner'
  Object.assign(targetEstimate, {
    mode: 'rpm',
    rpm: 300,
    tpm: 338400,
    latencySec: 10,
    inputTokens: 1000,
    outputTokens: 128,
    durationSec: 120
  })
  assumedLatencySec.value = 10
  formRef.value?.clearValidate()
}
</script>

<style scoped>
.full-row {
  grid-column: 1 / -1;
}

.mode-section {
  border-color: #bfdbfe;
  background:
    linear-gradient(135deg, rgba(59, 130, 246, 0.08), rgba(255, 255, 255, 0.96)),
    #f8fbff;
}

.mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.mode-card {
  display: grid;
  gap: 6px;
  min-height: 76px;
  padding: 13px;
  border: 1px solid #d8e0ec;
  border-radius: 12px;
  background:
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  transition:
    border-color 0.3s ease,
    box-shadow 0.3s ease,
    transform 0.3s ease;
}

.mode-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.09);
  transform: translateY(-2px);
}

.mode-card.active {
  border-color: #2563eb;
  box-shadow:
    0 0 0 1px #2563eb inset,
    0 16px 34px rgba(37, 99, 235, 0.16);
}

.mode-card strong {
  color: #1e293b;
  font-size: 14px;
}

.mode-card span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
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
  border-radius: 12px;
  background:
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  color: #1e293b;
  text-align: left;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 0.3s ease;
}

.preset-card:hover {
  border-color: #93b4e8;
  box-shadow: 0 16px 32px rgba(15, 23, 42, 0.11);
  transform: translateY(-2px);
}

.preset-card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}

.preset-card.active {
  border-color: #2563eb;
  background:
    linear-gradient(180deg, #f8fbff 0%, #eff6ff 100%);
  box-shadow:
    0 0 0 1px #2563eb inset,
    0 18px 36px rgba(37, 99, 235, 0.16);
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
  border-radius: 12px;
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
  border-radius: 10px;
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
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 -10px 24px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(10px);
}

.estimate-panel {
  display: grid;
  gap: 12px;
}

.estimate-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.estimate-cards > div {
  min-height: 92px;
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 12px;
  background:
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  transition:
    border-color 0.3s ease,
    box-shadow 0.3s ease,
    transform 0.3s ease;
}

.estimate-cards > div:hover {
  border-color: #bfdbfe;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.09);
  transform: translateY(-2px);
}

.estimate-cards span,
.estimate-cards em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.estimate-cards strong {
  display: block;
  margin: 7px 0 4px;
  overflow: hidden;
  color: #2563eb;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 22px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.estimate-note {
  margin-top: 2px;
}

.consumption-panel {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border: 1px solid #dbeafe;
  border-left: 3px solid #2563eb;
  border-radius: 12px;
  background: #ffffff;
}

.consumption-panel.warning {
  border-color: #fed7aa;
  border-left-color: #f97316;
  background: #fff7ed;
}

.consumption-panel.danger {
  border-color: #fecaca;
  border-left-color: #dc2626;
  background: #fef2f2;
}

.consumption-panel > div {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.consumption-panel span,
.consumption-panel em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.consumption-panel strong {
  color: #1e293b;
  font-size: 15px;
}

.target-estimator {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  background: #f8fbff;
}

.target-estimator.disabled {
  border-color: #fed7aa;
  background: #fffaf3;
}

.target-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.target-head h3 {
  margin: 0;
  color: #1e293b;
  font-size: 14px;
  font-weight: 800;
}

.target-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.target-presets {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.target-preset {
  display: flex;
  min-height: 92px;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid #d8e0ec;
  border-radius: 12px;
  background:
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  color: #1e293b;
  text-align: left;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 0.3s ease;
}

.target-preset:hover:not(:disabled) {
  border-color: #93b4e8;
  box-shadow: 0 16px 30px rgba(15, 23, 42, 0.11);
  transform: translateY(-2px);
}

.target-preset:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}

.target-preset.active {
  border-color: #2563eb;
  background: #ffffff;
  box-shadow:
    0 0 0 1px #2563eb inset,
    0 16px 32px rgba(37, 99, 235, 0.15);
}

.target-preset:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.target-preset span,
.target-preset em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}

.target-preset span {
  color: #1e293b;
  font-weight: 800;
}

.target-preset strong {
  color: #2563eb;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 17px;
  line-height: 1.2;
}

.target-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.target-mode-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: #ffffff;
}

.target-mode-row span {
  color: #475569;
  font-size: 12px;
  font-weight: 800;
}

.target-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.target-summary-grid > div {
  min-height: 86px;
  padding: 12px;
  border: 1px solid #dfe7f2;
  border-radius: 12px;
  background: #ffffff;
}

.target-summary-grid span,
.target-summary-grid em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.target-summary-grid strong {
  display: block;
  margin: 6px 0 4px;
  overflow: hidden;
  color: #2563eb;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 19px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-result {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)) auto;
  gap: 12px;
  align-items: stretch;
}

.target-result > div {
  min-width: 0;
  padding: 12px;
  border: 1px solid #dfe7f2;
  border-radius: 12px;
  background: #ffffff;
}

.target-result span,
.target-result em {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.target-result strong {
  display: block;
  margin: 6px 0 4px;
  overflow: hidden;
  color: #0f766e;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-result .el-button {
  align-self: stretch;
  min-height: 72px;
}

.target-risk-list {
  display: grid;
  gap: 10px;
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
  border-radius: 12px;
  background:
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  color: #1e293b;
  text-align: left;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 0.3s ease;
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
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.24);
}

.provider-card:hover {
  border-color: #93b4e8;
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.11);
  transform: translateY(-2px);
}

.provider-card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}

.provider-card.active {
  border-color: #2563eb;
  background:
    radial-gradient(circle at 18% 0%, rgba(59, 130, 246, 0.18), transparent 11rem),
    linear-gradient(180deg, #f8fbff 0%, #eff6ff 100%);
  box-shadow:
    0 0 0 1px #2563eb inset,
    0 0 0 4px rgba(37, 99, 235, 0.08),
    0 18px 38px rgba(37, 99, 235, 0.18);
}

.provider-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 20px;
}

.provider-card.active .provider-icon {
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  color: #ffffff;
  box-shadow: 0 12px 22px rgba(37, 99, 235, 0.24);
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
  border-radius: 12px;
  background: #f8fbff;
  color: #64748b;
}

.matrix-derived-note {
  margin-top: -2px;
  padding: 9px 12px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
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
  border-radius: 12px;
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

  .estimate-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .target-presets,
  .target-grid,
  .target-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .target-result {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .mode-grid {
    grid-template-columns: 1fr;
  }

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

  .estimate-cards {
    grid-template-columns: 1fr;
  }

  .target-head {
    flex-direction: column;
  }

  .consumption-panel {
    flex-direction: column;
  }

  .target-mode-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .target-presets,
  .target-grid,
  .target-summary-grid {
    grid-template-columns: 1fr;
  }

  .action-buttons,
  .action-buttons .el-button {
    width: 100%;
  }
}
</style>
