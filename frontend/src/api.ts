const BASE = '/api/v1'
const TOKEN_KEY = 'sn_token'

export class ApiError extends Error {
  status: number
  code: string
  details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

type Query = Record<string, string | number | boolean | null | undefined>

function url(path: string, query?: Query): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const s = qs.toString()
  return `${BASE}${path}${s ? `?${s}` : ''}`
}

async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; json?: unknown; form?: FormData; headers?: Record<string, string> } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...opts.headers }
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  } else if (opts.form) {
    body = opts.form
  }
  const res = await fetch(url(path, opts.query), { method, headers, body })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error ?? {}
    if (res.status === 401 && path !== '/auth/login') {
      tokenStore.clear()
      window.dispatchEvent(new Event('sn:unauthorized'))
    }
    throw new ApiError(res.status, err.code ?? 'HTTP_ERROR', err.message ?? `Permintaan gagal (${res.status}).`, err.details)
  }
  return data as T
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, json?: unknown) => request<T>('POST', path, { json }),
  patch: <T>(path: string, json: unknown) => request<T>('PATCH', path, { json }),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, file: File, idempotencyKey: string) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>('POST', path, { form, headers: { 'Idempotency-Key': idempotencyKey } })
  },
  postForm: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
  download: async (path: string, filename: string) => {
    const token = tokenStore.get()
    const res = await fetch(url(path), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (!res.ok) {
      const data = await res.json().catch(() => null)
      throw new ApiError(res.status, data?.error?.code ?? 'HTTP_ERROR', data?.error?.message ?? 'Unduhan gagal.')
    }
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
  },
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const errors = (e.details as { errors?: { loc: string[]; msg: string }[] } | undefined)?.errors
    if (errors?.length) return `${e.message} ${errors.map((x) => `${x.loc.slice(1).join('.')}: ${x.msg}`).join('; ')}`
    return e.message
  }
  return 'Terjadi kesalahan tak terduga. Muat ulang halaman lalu coba lagi.'
}
