<template>
  <div class="empty-state-panel">
    <div class="empty-state-icon" aria-hidden="true">
      <el-icon><component :is="icon" /></el-icon>
    </div>
    <div class="empty-state-copy">
      <strong>{{ title }}</strong>
      <span>{{ description }}</span>
    </div>
    <el-button v-if="actionLabel" type="primary" :icon="actionIcon" @click="$emit('action')">
      {{ actionLabel }}
    </el-button>
  </div>
</template>

<script setup>
import { DataAnalysis, Plus } from '@element-plus/icons-vue'

defineProps({
  title: {
    type: String,
    default: '暂无数据'
  },
  description: {
    type: String,
    default: '完成一次测试后，这里会显示可分析的数据。'
  },
  actionLabel: {
    type: String,
    default: ''
  },
  icon: {
    type: Object,
    default: () => DataAnalysis
  },
  actionIcon: {
    type: Object,
    default: () => Plus
  }
})

defineEmits(['action'])
</script>

<style scoped>
.empty-state-panel {
  display: grid;
  place-items: center;
  gap: 14px;
  min-height: 260px;
  padding: 34px 20px;
  border: 1px dashed #d1d5db;
  border-radius: 8px;
  background: #ffffff;
  text-align: center;
}

.empty-state-icon {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border-radius: 8px;
  background: #f2f3f5;
  color: #111827;
  font-size: 28px;
}

.empty-state-copy {
  display: grid;
  gap: 6px;
  max-width: 420px;
}

.empty-state-copy strong {
  color: #111827;
  font-size: 16px;
  line-height: 1.4;
}

.empty-state-copy span {
  color: #6b7280;
  font-size: 13px;
  line-height: 1.6;
}
</style>
