const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const TOKEN_KEY = 'llm_stress_auth_token'

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAuthToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

async function request(path, options = {}) {
  const token = getAuthToken()
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    },
    ...options
  })

  if (!response.ok) {
    if (response.status === 401) {
      setAuthToken('')
      window.dispatchEvent(new CustomEvent('auth-expired'))
    }
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

export function login(payload) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getMe() {
  return request('/api/auth/me')
}

export function createTest(payload) {
  return request('/api/tests', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function createCustomCaseBatch(payload) {
  return request('/api/tests/custom-case-batch', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function createKimiSuite(payload) {
  return request('/api/kimi-suite', { method: 'POST', body: JSON.stringify(payload) })
}

export function getKimiSuite(id) {
  return request(`/api/kimi-suite/${id}`)
}

export function createCacheDiagnostics(payload) {
  return request('/api/cache-diagnostics', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getCacheDiagnostics(id) {
  return request(`/api/cache-diagnostics/${id}`)
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

export function convertCurlToOpenApi(payload) {
  return request('/api/docs/convert-curl', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getTest(id) {
  return request(`/api/tests/${id}`)
}

export function stopTest(id) {
  return request(`/api/tests/${id}/stop`, { method: 'POST' })
}

export function resumeMatrixTest(id, payload) {
  return request(`/api/tests/${id}/resume-matrix`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function deleteTest(id) {
  return request(`/api/tests/${id}`, { method: 'DELETE' })
}

export function deleteTests(ids) {
  return request('/api/tests/bulk-delete', {
    method: 'POST',
    body: JSON.stringify({ ids })
  })
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
  const token = encodeURIComponent(getAuthToken())
  const suffix = token ? `?token=${token}` : ''
  return `${API_BASE}/api/tests/${id}/download/${kind}${suffix}`
}

export function createProgressSocket(id) {
  if (import.meta.env.VITE_WS_BASE_URL) {
    return new WebSocket(`${import.meta.env.VITE_WS_BASE_URL}/ws/tests/${id}`)
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = encodeURIComponent(getAuthToken())
  return new WebSocket(`${protocol}//${window.location.host}/ws/tests/${id}?token=${token}`)
}

export function getVendorBillingConfig() {
  return request('/api/vendor-billing/config')
}

export function listVendorTemplates(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request(`/api/vendor-templates${suffix}`)
}

export function getVendorTemplate(id) { return request(`/api/vendor-templates/${id}`) }
export function createVendorTemplate(payload) { return request('/api/vendor-templates', { method: 'POST', body: JSON.stringify(payload) }) }
export function updateVendorTemplate(id, payload) { return request(`/api/vendor-templates/${id}`, { method: 'PUT', body: JSON.stringify(payload) }) }
export function setVendorTemplateEnabled(id, enabled) { return request(`/api/vendor-templates/${id}/${enabled ? 'enable' : 'disable'}`, { method: 'POST' }) }
export function createVendorBillingFromTemplate(payload) { return request('/api/vendor-billing/from-template', { method: 'POST', body: JSON.stringify(payload) }) }

export function getVendorBillingPricing() {
  return request('/api/vendor-billing/pricing')
}

export function createVendorBilling(payload) {
  return request('/api/vendor-billing', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getVendorBilling(id) {
  return request(`/api/vendor-billing/${id}`)
}

export function vendorBillingDownloadUrl(id, kind) {
  const token = encodeURIComponent(getAuthToken())
  const suffix = token ? `?token=${token}` : ''
  return `${API_BASE}/api/vendor-billing/${id}/download/${kind}${suffix}`
}
