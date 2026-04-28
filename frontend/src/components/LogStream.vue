<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">实时日志</h2>
      <el-button size="small" :icon="Delete" @click="$emit('clear')">清空</el-button>
    </div>
    <div class="section-body">
      <div class="log-box">
        <div v-if="!logs.length" class="muted">暂无日志</div>
        <div v-for="(log, index) in logs" :key="index" class="log-line">
          <span>{{ log.level || 'info' }}</span>
          <span>{{ log.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Delete } from '@element-plus/icons-vue'

defineProps({
  logs: {
    type: Array,
    default: () => []
  }
})

defineEmits(['clear'])
</script>
