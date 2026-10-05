export class ApiError extends Error {
  status: number
  constructor(status: number, body: string) {
    super(body || `${status}`)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => '') || res.statusText)
  if (res.status === 204) return undefined as T
  return res.json()
}
