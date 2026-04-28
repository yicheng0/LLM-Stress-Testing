<template>
  <el-table :data="rows" border>
    <el-table-column prop="name" label="指标" min-width="140" />
    <el-table-column prop="avg" label="平均" min-width="110" />
    <el-table-column prop="p50" label="P50" min-width="110" />
    <el-table-column prop="p90" label="P90" min-width="110" />
    <el-table-column prop="p95" label="P95" min-width="110" />
    <el-table-column prop="p99" label="P99" min-width="110" />
  </el-table>
</template>

<script setup>
defineProps({
  rows: {
    type: Array,
    default: () => []
  }
})
</script>
