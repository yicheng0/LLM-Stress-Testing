<template>
  <div class="grid-4">
    <div v-for="item in items" :key="item.label" class="metric-card">
      <div class="metric-label">{{ item.label }}</div>
      <div class="metric-value" :style="{ color: item.color || '#1e293b' }">{{ item.value }}</div>
      <div v-if="item.sub" class="metric-sub">{{ item.sub }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  items: {
    type: Array,
    required: true
  }
})
</script>
