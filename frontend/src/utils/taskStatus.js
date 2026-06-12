export const ACTIVE_TASK_STATUSES = ['queued', 'running', 'stopping']
export const TERMINAL_TASK_STATUSES = ['completed', 'failed', 'cancelled', 'interrupted']

export const TASK_STATUS_META = {
  queued: {
    label: '排队',
    longLabel: '排队中',
    tagType: 'info',
    color: '#64748b'
  },
  running: {
    label: '运行',
    longLabel: '运行中',
    tagType: 'primary',
    color: '#2563eb'
  },
  stopping: {
    label: '停止中',
    longLabel: '停止中',
    tagType: 'warning',
    color: '#f97316'
  },
  completed: {
    label: '完成',
    longLabel: '已完成',
    tagType: 'success',
    color: '#16a34a'
  },
  failed: {
    label: '失败',
    longLabel: '失败',
    tagType: 'danger',
    color: '#dc2626'
  },
  cancelled: {
    label: '取消',
    longLabel: '已取消',
    tagType: 'warning',
    color: '#f59e0b'
  },
  interrupted: {
    label: '中断',
    longLabel: '已中断',
    tagType: 'warning',
    color: '#9333ea'
  }
}

export function taskStatusMeta(status) {
  return TASK_STATUS_META[status] || {
    label: status || '-',
    longLabel: status || '-',
    tagType: 'info',
    color: '#64748b'
  }
}

export function taskStatusLabel(status, { long = false } = {}) {
  const meta = taskStatusMeta(status)
  return long ? meta.longLabel : meta.label
}

export function taskStatusTagType(status) {
  return taskStatusMeta(status).tagType
}

export function taskStatusColor(status) {
  return taskStatusMeta(status).color
}

export function isActiveTaskStatus(status) {
  return ACTIVE_TASK_STATUSES.includes(status)
}

export function isTerminalTaskStatus(status) {
  return TERMINAL_TASK_STATUSES.includes(status)
}
