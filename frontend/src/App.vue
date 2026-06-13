<template>
  <router-view v-if="isStandaloneLayout" />
  <el-container v-else class="app-shell">
    <el-aside class="sidebar desktop-sidebar" width="216px">
      <div class="brand">
        <img class="brand-logo" src="https://wenwen-us.oss-us-west-1.aliyuncs.com/apipro_logo.png" alt="APIPro" />
        <div class="brand-copy">
          <div class="brand-title">APIPro</div>
          <div class="brand-subtitle">LLM Benchmark</div>
        </div>
      </div>

        <el-menu :default-active="activePath" router class="nav-menu">
          <el-menu-item v-for="item in visibleNavItems" :key="item.index" :index="item.index">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-info">
        <div v-if="auth.role === 'root'" class="info-block domain-block">
          <div class="info-title">接入域名</div>
          <div class="domain-line">
            <span>国内</span>
            <code>https://api.wenwen-ai.com</code>
          </div>
          <div class="domain-line">
            <span>海外</span>
            <code>https://api.apipro.ai</code>
          </div>
        </div>

      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div class="topbar-title">
          <el-button
            class="mobile-menu-button"
            :icon="Menu"
            aria-label="打开导航"
            @click="mobileNavOpen = true"
          />
          <div>
            <div class="page-title">{{ routeTitle }}</div>
            <div class="page-meta">{{ today }}</div>
          </div>
        </div>
        <div class="topbar-actions">
          <el-tag v-if="auth.user" effect="plain">{{ auth.user.username }} · {{ auth.user.role }}</el-tag>
          <el-button :icon="Refresh" @click="reloadRoute">刷新</el-button>
          <el-button class="user-avatar-button" circle aria-label="退出登录" @click="logout">
            {{ userInitial }}
          </el-button>
        </div>
      </el-header>

      <el-main class="content">
        <router-view v-slot="{ Component, route: viewRoute }">
          <transition name="route-fade" mode="out-in">
            <div :key="viewRoute.fullPath" class="route-page">
              <component :is="Component" />
            </div>
          </transition>
        </router-view>
      </el-main>
    </el-container>

    <el-drawer
      v-model="mobileNavOpen"
      class="mobile-nav-drawer"
      direction="ltr"
      size="292px"
      :with-header="false"
    >
      <div class="sidebar mobile-sidebar">
        <div class="brand">
          <img class="brand-logo" src="https://wenwen-us.oss-us-west-1.aliyuncs.com/apipro_logo.png" alt="APIPro" />
          <div class="brand-copy">
            <div class="brand-title">APIPro</div>
            <div class="brand-subtitle">LLM Benchmark</div>
          </div>
        </div>

        <el-menu :default-active="activePath" router class="nav-menu" @select="mobileNavOpen = false">
          <el-menu-item v-for="item in visibleNavItems" :key="item.index" :index="item.index">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-info" />
      </div>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, DataAnalysis, Document, DocumentAdd, EditPen, Menu, Plus, Refresh, TrendCharts } from '@element-plus/icons-vue'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isPrintLayout = computed(() => Boolean(route.meta?.printLayout))
const isStandaloneLayout = computed(() => Boolean(route.meta?.printLayout || route.meta?.public))
const mobileNavOpen = ref(false)
const navItems = [
  { index: '/tests/new', label: '新建测试', icon: Plus },
  { index: '/tests/custom-case', label: '自定义 Case', icon: EditPen },
  { index: '/history', label: '历史记录', icon: Clock },
  { index: '/help/parameters', label: '参数说明', icon: Document },
  { index: '/help/metrics', label: '指标科普', icon: TrendCharts },
  { index: '/dashboard/realtime', label: '实时面板', icon: DataAnalysis },
  { index: '/docs/curl-to-openapi', label: '文档生成', icon: DocumentAdd }
]
const visibleNavItems = computed(() => {
  if (auth.role !== 'guest') return navItems
  return navItems.filter((item) => item.index !== '/tests/custom-case')
})
const userInitial = computed(() => (auth.user?.username || 'U').slice(0, 1).toUpperCase())

const activePath = computed(() => {
  if (route.path.startsWith('/history')) return '/history'
  if (route.path.startsWith('/compare')) return '/history'
  if (route.path.startsWith('/help/metrics')) return '/help/metrics'
  if (route.path.startsWith('/help')) return '/help/parameters'
  if (route.path.startsWith('/dashboard')) return '/dashboard/realtime'
  if (route.path.startsWith('/docs')) return '/docs/curl-to-openapi'
  if (route.path.startsWith('/tests/custom-case')) return '/tests/custom-case'
  return '/tests/new'
})
const routeTitle = computed(() => route.meta?.title || {
  'new-test': '新建测试',
  'custom-case': '自定义输入诊断',
  'run-test': '实时运行',
  'test-report': '报告详情',
  history: '历史记录',
  compare: '测试对比',
  'parameter-help': '参数说明',
  'metrics-help': '指标科普',
  'realtime-dashboard': '实时数据面板',
  'curl-to-openapi': '文档生成'
}[route.name] || '性能测试')

const today = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit'
}).format(new Date())

function reloadRoute() {
  router.go(0)
}

function logout() {
  auth.logout()
  router.replace('/login')
}

function handleAuthExpired() {
  auth.logout()
  router.replace('/login')
}

onMounted(() => window.addEventListener('auth-expired', handleAuthExpired))
onUnmounted(() => window.removeEventListener('auth-expired', handleAuthExpired))

watch(
  () => route.fullPath,
  () => {
    mobileNavOpen.value = false
  }
)
</script>
