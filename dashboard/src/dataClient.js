export const MODE = 'PAPER'

export async function requestJson(path, signal, mode = MODE) {
  const separator = path.includes('?') ? '&' : '?'
  const scoped = /[?&]mode=/.test(path) ? path : `${path}${separator}mode=${encodeURIComponent(mode)}`
  const response = await fetch(scoped, { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `요청 실패 (${response.status})`)
  }
  return response.json()
}
