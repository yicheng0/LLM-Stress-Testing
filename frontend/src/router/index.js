import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/', redirect: '/tests/new' },
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/tests/new', name: 'new-test', component: () => import('../views/NewTest.vue') },
  { path: '/tests/custom-case', name: 'custom-case', component: () => import('../views/CustomCase.vue'), meta: { roles: ['root'] } },
  { path: '/tests/:id/run', name: 'run-test', component: () => import('../views/RunTest.vue'), props: true },
  { path: '/tests/:id/report', name: 'test-report', component: () => import('../views/Report.vue'), props: true },
  {
    path: '/tests/:id/report/print',
    name: 'test-report-print',
    component: () => import('../views/PrintableReport.vue'),
    props: true,
    meta: { printLayout: true }
  },
  { path: '/history', name: 'history', component: () => import('../views/History.vue') },
  { path: '/compare', name: 'compare', component: () => import('../views/Compare.vue') },
  { path: '/help/parameters', name: 'parameter-help', component: () => import('../views/ParameterHelp.vue') },
  { path: '/help/metrics', name: 'metrics-help', component: () => import('../views/MetricsHelp.vue') },
  { path: '/dashboard/realtime', name: 'realtime-dashboard', component: () => import('../views/RealtimeDashboard.vue') },
  { path: '/docs/curl-to-openapi', name: 'curl-to-openapi', component: () => import('../views/CurlToOpenApi.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta?.public) {
    if (to.name === 'login' && auth.token && !auth.user) {
      await auth.restore()
    }
    return auth.isAuthenticated && to.name === 'login' ? '/' : true
  }
  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    await auth.restore()
  }
  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta?.roles && !to.meta.roles.includes(auth.role)) {
    return '/'
  }
  return true
})

export default router
