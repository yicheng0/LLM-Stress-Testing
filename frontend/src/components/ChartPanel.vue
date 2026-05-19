<template>
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">{{ title }}</h2>
      <slot name="actions" />
    </div>
    <div class="section-body">
      <div ref="chartEl" class="chart" />
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { loadEcharts } from '../utils/echarts'

const props = defineProps({
  title: {
    type: String,
    required: true
  },
  option: {
    type: Object,
    required: true
  }
})

const chartEl = ref()
let chart
let visible = false
let observer
let renderFrame = 0

async function render() {
  if (!chartEl.value || !visible) return
  const echarts = await loadEcharts()
  if (!chartEl.value || !visible) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
  }
  chart.setOption(props.option, true)
}

function scheduleRender() {
  if (renderFrame) return
  renderFrame = window.requestAnimationFrame(() => {
    renderFrame = 0
    render()
  })
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  observer = new IntersectionObserver((entries) => {
    visible = entries.some((entry) => entry.isIntersecting)
    if (visible) scheduleRender()
  }, { rootMargin: '120px' })
  if (chartEl.value) observer.observe(chartEl.value)
  window.addEventListener('resize', resize)
})

watch(() => props.option, scheduleRender, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  observer?.disconnect()
  if (renderFrame) window.cancelAnimationFrame(renderFrame)
  chart?.dispose()
})
</script>
