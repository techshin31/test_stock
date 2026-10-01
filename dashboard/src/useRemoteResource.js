import { useCallback, useEffect, useRef, useState } from 'react'
import { requestJson } from './dataClient.js'

// Each endpoint owns its refresh status. A failed request retains the last
// successful payload but never changes its timestamp or marks it as current.
export function useRemoteResource(path, { enabled = true, refreshMs = 30_000 } = {}) {
  const [resource, setResource] = useState({ data: null, error: '', lastSuccess: null, loading: true })
  const current = useRef({ sequence: 0, controller: null })

  const refresh = useCallback(async () => {
    const sequence = ++current.current.sequence
    current.current.controller?.abort()
    const controller = new AbortController()
    current.current.controller = controller
    let timedOut = false
    const timeout = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 15_000)
    try {
      const data = await requestJson(path, controller.signal)
      if (sequence !== current.current.sequence || controller.signal.aborted) return
      setResource({ data, error: '', lastSuccess: new Date().toISOString(), loading: false })
    } catch (error) {
      if (sequence !== current.current.sequence || (controller.signal.aborted && !timedOut)) return
      setResource((previous) => ({
        ...previous,
        error: timedOut ? '응답 대기 시간이 초과되었습니다.' : error.message || '데이터 요청에 실패했습니다.',
        loading: false,
      }))
    } finally {
      window.clearTimeout(timeout)
    }
  }, [path])

  useEffect(() => {
    if (!enabled) return undefined
    const requestState = current.current
    refresh()
    const interval = refreshMs ? window.setInterval(refresh, refreshMs) : null
    return () => {
      ++requestState.sequence
      requestState.controller?.abort()
      if (interval !== null) window.clearInterval(interval)
    }
  }, [enabled, refresh, refreshMs])

  return { ...resource, refresh }
}
