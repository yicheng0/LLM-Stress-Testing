<template>
  <router-view v-if="isPrintLayout" />
  <el-container v-else class="app-shell">
    <el-aside class="sidebar" width="236px">
      <div class="brand">
        <img class="brand-logo" src="https://wenwen-us.oss-us-west-1.aliyuncs.com/apipro_logo.png" alt="APIPro" />
        <div>
          <div class="brand-title">APIPro LLM Benchmark Studio</div>
          <div class="brand-subtitle">Performance Intelligence Console</div>
        </div>
      </div>

      <el-menu :default-active="activePath" router class="nav-menu">
        <el-menu-item index="/tests/new">
          <el-icon><Plus /></el-icon>
          <span>新建测试</span>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><Clock /></el-icon>
          <span>历史记录</span>
        </el-menu-item>
        <el-menu-item index="/help/parameters">
          <el-icon><Document /></el-icon>
          <span>参数说明</span>
        </el-menu-item>
        <el-menu-item index="/dashboard/realtime">
          <el-icon><DataAnalysis /></el-icon>
          <span>实时面板</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-info">
        <div class="info-block">
          <div class="info-title">版本信息</div>
          <div class="info-line"><span>版本</span><strong>v{{ appVersion }}</strong></div>
          <div class="info-line"><span>开发</span><strong>APIPro 团队</strong></div>
        </div>

        <div class="info-block">
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

        <div class="info-block qr-block">
          <div class="qr-copy">
            <div class="info-title">扫码联系</div>
            <div class="qr-caption">APIPro 技术支持</div>
          </div>
          <img class="sidebar-qr" src="/assets/apipro-qrcode.png" alt="APIPro 技术支持二维码" />
        </div>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <div class="page-title">{{ routeTitle }}</div>
          <div class="page-meta">{{ today }}</div>
        </div>
        <el-button :icon="Refresh" @click="reloadRoute">刷新</el-button>
      </el-header>

      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, DataAnalysis, Document, Plus, Refresh } from '@element-plus/icons-vue'
import packageInfo from '../package.json'

const route = useRoute()
const router = useRouter()
const appVersion = packageInfo.version
const isPrintLayout = computed(() => Boolean(route.meta?.printLayout))

const activePath = computed(() => {
  if (route.path.startsWith('/history')) return '/history'
  if (route.path.startsWith('/compare')) return '/history'
  if (route.path.startsWith('/help')) return '/help/parameters'
  if (route.path.startsWith('/dashboard')) return '/dashboard/realtime'
  return '/tests/new'
})
const routeTitle = computed(() => route.meta?.title || {
  'new-test': '新建测试',
  'run-test': '实时运行',
  'test-report': '报告详情',
  history: '历史记录',
  compare: '测试对比',
  'parameter-help': '参数说明',
  'realtime-dashboard': '实时数据面板'
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
</script>
