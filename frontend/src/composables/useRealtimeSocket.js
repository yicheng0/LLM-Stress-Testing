import { onBeforeUnmount, ref } from 'vue'

export function useRealtimeSocket({ createSocket, getStatus, isTerminalStatus, onProgress, onStatus, onLog, onFallback }) {
  const socketStatus = ref('connecting')
  let socket = null
  let pingTimer = null

  function close() {
    if (socket) {
      socket.close()
      socket = null
    }
    window.clearInterval(pingTimer)
    pingTimer = null
  }

  function markEnded() {
    socketStatus.value = 'ended'
    close()
  }

  function terminal() {
    return isTerminalStatus(getStatus?.())
  }

  function connect(id) {
    close()
    if (terminal()) {
      socketStatus.value = 'ended'
      return
    }

    socketStatus.value = 'connecting'
    socket = createSocket(id)
    socket.onopen = () => {
      if (!terminal()) socketStatus.value = 'connected'
    }
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'progress') onProgress?.(message.data)
      if (message.type === 'status') onStatus?.(message.data.status)
      if (message.type === 'log') onLog?.(message.data)
    }
    socket.onerror = () => {
      if (!terminal()) {
        socketStatus.value = 'polling'
        onFallback?.()
      }
    }
    socket.onclose = () => {
      socketStatus.value = terminal() ? 'ended' : 'polling'
    }
    pingTimer = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send('ping')
    }, 20000)
  }

  onBeforeUnmount(close)

  return {
    socketStatus,
    connect,
    close,
    markEnded,
  }
}
