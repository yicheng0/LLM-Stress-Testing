import { defineStore } from 'pinia'
import { listTests } from '../api/client'

export const useTestsStore = defineStore('tests', {
  state: () => ({
    total: 0,
    page: 1,
    pageSize: 20,
    items: [],
    loading: false,
    filters: {
      status: '',
      model: '',
      api_protocol: '',
      created_from: '',
      created_to: ''
    }
  }),
  actions: {
    async fetchHistory(overrides = {}) {
      this.loading = true
      try {
        const params = {
          page: this.page,
          page_size: this.pageSize,
          ...this.filters,
          ...overrides
        }
        const data = await listTests(params)
        this.total = data.total
        this.page = data.page
        this.pageSize = data.page_size
        this.items = data.items
      } finally {
        this.loading = false
      }
    }
  }
})
