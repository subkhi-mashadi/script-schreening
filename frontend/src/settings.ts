import { useEffect, useState } from 'react'
import { api } from './api'

let cache: { auto_mode: boolean } | null = null

/** Pengaturan tampilan dari server; mode otomatis menyembunyikan verifikasi manual & keputusan manajer. */
export function useSettings() {
  const [s, setS] = useState(cache ?? { auto_mode: true })
  useEffect(() => {
    if (cache) return
    api
      .get<{ auto_mode: boolean }>('/settings')
      .then((x) => {
        cache = x
        setS(x)
      })
      .catch(() => undefined)
  }, [])
  return s
}
