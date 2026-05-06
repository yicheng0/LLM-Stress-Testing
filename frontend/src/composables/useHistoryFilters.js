import { ref } from 'vue'

export function useHistoryFilters(store) {
  const createdRange = ref([])

  function reload() {
    store.page = 1
    return store.fetchHistory()
  }

  function syncDateRange(value) {
    const [from, to] = value || []
    store.filters.created_from = from ? `${from}T00:00:00` : ''
    store.filters.created_to = to ? `${to}T23:59:59` : ''
  }

  function resetFilters() {
    store.filters.model = ''
    store.filters.status = ''
    store.filters.api_protocol = ''
    store.filters.created_from = ''
    store.filters.created_to = ''
    createdRange.value = []
    return reload()
  }

  return {
    createdRange,
    reload,
    syncDateRange,
    resetFilters,
  }
}
