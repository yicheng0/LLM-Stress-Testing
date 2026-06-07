import { defineStore } from 'pinia'
import { getAuthToken, getMe, login, setAuthToken } from '../api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getAuthToken(),
    user: null,
    loading: false
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token && state.user),
    role: (state) => state.user?.role || ''
  },
  actions: {
    async login(username, password) {
      this.loading = true
      try {
        const data = await login({ username, password })
        this.token = data.token
        this.user = data.user
        setAuthToken(data.token)
        return data.user
      } finally {
        this.loading = false
      }
    },
    async restore() {
      if (!this.token) return null
      this.loading = true
      try {
        this.user = await getMe()
        return this.user
      } catch {
        this.logout()
        return null
      } finally {
        this.loading = false
      }
    },
    logout() {
      this.token = ''
      this.user = null
      setAuthToken('')
    }
  }
})
