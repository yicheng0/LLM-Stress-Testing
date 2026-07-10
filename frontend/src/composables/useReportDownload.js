import { downloadUrl } from '../api/client'

export function printableReportUrl(router, id) {
  return router.resolve({
    name: 'test-report-print',
    params: { id },
    query: { autoprint: '1' }
  }).href
}

export function openReportDownload(router, id, kind) {
  window.open(downloadUrl(id, kind), '_blank')
}
