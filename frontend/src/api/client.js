const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })

  if (!response.ok) {
    let message = `请求失败：${response.status}`
    try {
      const body = await response.json()
      message = body.detail || message
    } catch {
      // Keep the status based message.
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return null
  }
  return response.json()
}

export function createTest(payload) {
  return request('/api/tests', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function listTests(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value)
    }
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request(`/api/tests${suffix}`)
}

export function getRealtimeDashboard() {
  return request('/api/tests/dashboard/realtime')
}

export function getTest(id) {
  return request(`/api/tests/${id}`)
}

export function stopTest(id) {
  return request(`/api/tests/${id}/stop`, { method: 'POST' })
}

export function deleteTest(id) {
  return request(`/api/tests/${id}`, { method: 'DELETE' })
}

export function cleanupExpiredTests() {
  return request('/api/tests/cleanup/expired', { method: 'POST' })
}

export function getReport(id) {
  return request(`/api/tests/${id}/report`)
}

export function getDetails(id, params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value)
    }
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request(`/api/tests/${id}/details${suffix}`)
}

export function downloadUrl(id, kind) {
  return `${API_BASE}/api/tests/${id}/download/${kind}`
}

export function createProgressSocket(id) {
  if (import.meta.env.VITE_WS_BASE_URL) {
    return new WebSocket(`${import.meta.env.VITE_WS_BASE_URL}/ws/tests/${id}`)
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return new WebSocket(`${protocol}//${window.location.host}/ws/tests/${id}`)
}
