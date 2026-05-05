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
        <el-menu-item index="/help/metrics">
          <el-icon><TrendCharts /></el-icon>
          <span>指标科普</span>
        </el-menu-item>
        <el-menu-item index="/dashboard/realtime">
          <el-icon><DataAnalysis /></el-icon>
          <span>实时面板</span>
        </el-menu-item>
        <el-menu-item index="/docs/curl-to-openapi">
          <el-icon><DocumentAdd /></el-icon>
          <span>文档生成</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-info">
        <div class="info-block">
          <div class="info-title">版本信息</div>
          <div class="info-line"><span>当前</span><strong>v{{ versionState.current_version || appVersion }}</strong></div>
          <div class="info-line"><span>本地引用</span><strong class="mono">{{ shortRef(versionState.current_ref) }}</strong></div>
          <div class="info-line"><span>远端引用</span><strong class="mono">{{ shortRef(versionState.latest_ref) }}</strong></div>
          <div class="info-line">
            <span>状态</span>
            <el-tag :type="versionTagType" effect="plain" size="small">{{ versionStatusText }}</el-tag>
          </div>
          <div v-if="versionState.dirty_paths?.length" class="version-detail">
            <span>阻止更新</span>
            <strong>{{ versionState.dirty_paths.slice(0, 3).join('、') }}{{ versionState.dirty_paths.length > 3 ? ' 等' : '' }}</strong>
          </div>
          <div class="version-actions">
            <el-button :icon="Refresh" :loading="versionChecking" size="small" @click="checkVersion">
              检测版本
            </el-button>
            <el-button
              :icon="Download"
              :disabled="!versionState.update_enabled || !versionState.update_available || !versionState.available || !!versionState.dirty"
              :loading="versionUpdating"
              size="small"
              type="primary"
              @click="confirmUpdate"
            >
              更新
            </el-button>
          </div>
          <div class="version-hint">{{ versionState.message || '点击“检测版本”查看远端更新' }}</div>
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
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, DataAnalysis, Download, Document, DocumentAdd, Plus, Refresh, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import packageInfo from '../package.json'
import { checkVersionInfo, getVersionInfo, updateVersionInfo } from './api/client'

const route = useRoute()
const router = useRouter()
const appVersion = packageInfo.version
const isPrintLayout = computed(() => Boolean(route.meta?.printLayout))
const versionState = ref({
  available: true,
  update_enabled: false,
  current_version: appVersion,
  current_ref: null,
  latest_ref: null,
  branch: null,
  remote_url: null,
  ahead_count: null,
  behind_count: null,
  dirty: null,
  dirty_paths: null,
  update_available: false,
  message: '点击“检测版本”查看远端更新',
  checked_at: null
})
const versionChecking = ref(false)
const versionUpdating = ref(false)

const activePath = computed(() => {
  if (route.path.startsWith('/history')) return '/history'
  if (route.path.startsWith('/compare')) return '/history'
  if (route.path.startsWith('/help/metrics')) return '/help/metrics'
  if (route.path.startsWith('/help')) return '/help/parameters'
  if (route.path.startsWith('/dashboard')) return '/dashboard/realtime'
  if (route.path.startsWith('/docs')) return '/docs/curl-to-openapi'
  return '/tests/new'
})
const routeTitle = computed(() => route.meta?.title || {
  'new-test': '新建测试',
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

const versionStatusText = computed(() => {
  if (!versionState.value.available) return '不可用'
  if (versionState.value.dirty) return '有本地改动'
  if (!versionState.value.update_enabled) return '仅检测'
  if (versionState.value.update_available) return '可更新'
  if (versionState.value.checked_at) return '已最新'
  return '未检测'
})

const versionTagType = computed(() => {
  if (!versionState.value.available) return 'info'
  if (versionState.value.dirty) return 'danger'
  if (!versionState.value.update_enabled) return 'info'
  if (versionState.value.update_available) return 'warning'
  if (versionState.value.checked_at) return 'success'
  return 'info'
})

function reloadRoute() {
  router.go(0)
}

function shortRef(value) {
  if (!value) return '-'
  return value.length > 12 ? value.slice(0, 12) : value
}

async function loadVersionInfo() {
  try {
    const data = await getVersionInfo()
    versionState.value = { ...versionState.value, ...data }
  } catch (error) {
    versionState.value = {
      ...versionState.value,
      available: false,
      dirty_paths: null,
      message: error.message
    }
  }
}

async function checkVersion() {
  versionChecking.value = true
  try {
    const data = await checkVersionInfo()
    versionState.value = { ...versionState.value, ...data }
    ElMessage.success(data.update_available ? '检测到新版本' : '当前已是最新版本')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    versionChecking.value = false
  }
}

async function confirmUpdate() {
  if (!versionState.value.update_available) return
  try {
    await ElMessageBox.confirm('确认执行在线更新？更新过程中服务可能短暂不可用。', '更新版本', {
      type: 'warning',
      confirmButtonText: '更新',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  versionUpdating.value = true
  try {
    const result = await updateVersionInfo({})
    versionState.value = {
      ...versionState.value,
      current_ref: result.current_ref || versionState.value.current_ref,
      latest_ref: result.latest_ref || versionState.value.latest_ref,
      dirty: false,
      dirty_paths: null,
      update_available: false,
      message: result.message || '更新已完成，请刷新页面'
    }
    ElMessage.success(result.message || '更新已完成')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    versionUpdating.value = false
  }
}

onMounted(() => {
  loadVersionInfo()
})
</script>

<style scoped>
.version-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.version-hint {
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.version-detail {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 4px;
  color: #475569;
  font-size: 12px;
}

.version-detail strong {
  font-weight: 600;
  line-height: 1.4;
}
</style>
