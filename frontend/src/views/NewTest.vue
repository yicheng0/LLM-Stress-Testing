<template>
  <RiskAssessment :config="draftConfig" @summary-change="riskSummary = $event" />
  <ConfigForm
    :submitting="submitting"
    :initial-config="initialConfig"
    @change="draftConfig = $event"
    @submit="handleSubmit"
  />
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import ConfigForm from '../components/ConfigForm.vue'
import RiskAssessment from '../components/RiskAssessment.vue'
import { createTest } from '../api/client'

const router = useRouter()
const submitting = ref(false)
const initialConfig = ref(readInitialConfig())
const riskSummary = ref(null)
const draftConfig = ref(initialConfig.value || {
  concurrency: 10,
  duration_sec: 60,
  input_tokens: 1000,
  max_output_tokens: 128,
  enable_stream: true,
  matrix_mode: false,
  input_tokens_list: '1000,10000',
  concurrency_list: '10,50',
  matrix_duration_sec: 60
})

async function handleSubmit(payload) {
  if (!(await confirmRiskBeforeSubmit())) return
  submitting.value = true
  try {
    const result = await createTest(payload)
    sessionStorage.removeItem('rerun_config')
    ElMessage.success('测试任务已启动')
    router.push(`/tests/${result.test_id}/run`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

async function confirmRiskBeforeSubmit() {
  const summary = riskSummary.value
  if (!summary) return true

  const details = [
    `预计请求规模：${number(summary.estimatedRequestCount)} 次（不含重试与预热）`,
    `最大并发：${number(summary.maxConcurrency)}`,
    `输入 Token 规模：${number(summary.maxInputTokens)}`,
    `矩阵测试点：${number(summary.matrixPointCount)} 组`,
    `后端限制：${summary.backendLimitText}`
  ].join('\n')

  if (summary.exceedsBackendLimits) {
    await ElMessageBox.alert(details, '配置超过后端限制', {
      type: 'error',
      confirmButtonText: '返回修改',
      customClass: 'risk-confirm-dialog'
    })
    return false
  }

  if (summary.levelType === 'danger' || summary.levelType === 'warning') {
    try {
      await ElMessageBox.confirm(details, `启动前风险摘要：${summary.level}`, {
        type: summary.levelType,
        confirmButtonText: '确认启动',
        cancelButtonText: '返回修改',
        customClass: 'risk-confirm-dialog'
      })
    } catch {
      return false
    }
  }

  return true
}

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })
}

function readInitialConfig() {
  const raw = sessionStorage.getItem('rerun_config')
  if (!raw) return null
  try {
    return { ...JSON.parse(raw), api_key: '' }
  } catch {
    return null
  }
}
</script>
