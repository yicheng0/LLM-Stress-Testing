import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/tests/new' },
  { path: '/tests/new', name: 'new-test', component: () => import('../views/NewTest.vue') },
  { path: '/tests/:id/run', name: 'run-test', component: () => import('../views/RunTest.vue'), props: true },
  { path: '/tests/:id/report', name: 'test-report', component: () => import('../views/Report.vue'), props: true },
  { path: '/history', name: 'history', component: () => import('../views/History.vue') },
  { path: '/help/parameters', name: 'parameter-help', component: () => import('../views/ParameterHelp.vue') },
  { path: '/dashboard/realtime', name: 'realtime-dashboard', component: () => import('../views/RealtimeDashboard.vue') }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
