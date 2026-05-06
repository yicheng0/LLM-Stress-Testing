<template>
  <div class="skeleton-loader" :class="variant" aria-live="polite" aria-busy="true">
    <div v-if="variant === 'report'" class="skeleton-report">
      <div class="skeleton-line title"></div>
      <div class="skeleton-grid">
        <div v-for="item in 8" :key="item" class="skeleton-block"></div>
      </div>
    </div>
    <div v-else class="skeleton-table">
      <div class="skeleton-toolbar">
        <div class="skeleton-line medium"></div>
        <div class="skeleton-line short"></div>
      </div>
      <div v-for="row in rows" :key="row" class="skeleton-row">
        <div class="skeleton-line wide"></div>
        <div class="skeleton-line medium"></div>
        <div class="skeleton-line short"></div>
        <div class="skeleton-line medium"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  variant: {
    type: String,
    default: 'table'
  },
  rows: {
    type: Number,
    default: 6
  }
})
</script>

<style scoped>
.skeleton-loader {
  display: grid;
  gap: 14px;
  width: 100%;
}

.skeleton-table,
.skeleton-report {
  display: grid;
  gap: 12px;
}

.skeleton-toolbar,
.skeleton-row,
.skeleton-grid {
  display: grid;
  gap: 12px;
}

.skeleton-toolbar {
  grid-template-columns: minmax(140px, 1fr) 120px;
}

.skeleton-row {
  min-height: 54px;
  align-items: center;
  grid-template-columns: minmax(160px, 1.5fr) minmax(120px, 1fr) 92px minmax(110px, 1fr);
  padding: 10px 12px;
  border: 1px solid #dfe7f2;
  border-radius: 10px;
  background: #ffffff;
}

.skeleton-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.skeleton-block {
  min-height: 86px;
  border: 1px solid #dfe7f2;
  border-radius: 12px;
  background: linear-gradient(90deg, #eef4fb 25%, #f8fbff 37%, #eef4fb 63%);
  background-size: 400% 100%;
  animation: skeleton-wave 1.4s ease infinite;
}

.skeleton-line {
  height: 14px;
  border-radius: 999px;
  background: linear-gradient(90deg, #e5edf6 25%, #f8fbff 37%, #e5edf6 63%);
  background-size: 400% 100%;
  animation: skeleton-wave 1.4s ease infinite;
}

.skeleton-line.title {
  width: 240px;
  height: 22px;
}

.skeleton-line.wide {
  width: 100%;
}

.skeleton-line.medium {
  width: 68%;
}

.skeleton-line.short {
  width: 42%;
}

@keyframes skeleton-wave {
  0% {
    background-position: 100% 50%;
  }

  100% {
    background-position: 0 50%;
  }
}

@media (max-width: 720px) {
  .skeleton-toolbar,
  .skeleton-row,
  .skeleton-grid {
    grid-template-columns: 1fr;
  }

  .skeleton-row {
    min-height: 132px;
    align-items: stretch;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-line,
  .skeleton-block {
    animation: none;
  }
}
</style>
