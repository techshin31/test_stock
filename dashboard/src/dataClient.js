export const MODE = 'PAPER'

export async function requestJson(path, signal) {
  const separator = path.includes('?') ? '&' : '?'
  const response = await fetch(`${path}${separator}mode=${MODE}`, { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `요청 실패 (${response.status})`)
  }
  return response.json()
}
