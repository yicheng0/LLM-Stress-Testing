<template>
  <RiskAssessment :config="draftConfig" />
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
import { ElMessage } from 'element-plus'
import ConfigForm from '../components/ConfigForm.vue'
import RiskAssessment from '../components/RiskAssessment.vue'
import { createTest } from '../api/client'

const router = useRouter()
const submitting = ref(false)
const initialConfig = ref(readInitialConfig())
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
