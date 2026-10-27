import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { ScreeningRun } from './types'

const RUNNING = new Set(['QUEUED', 'PROCESSING'])
// Screening otomatis dibuat sesaat setelah pembacaan selesai; tunggu sebentar bila belum ada.
const MAX_EMPTY_POLLS = 30

/** Screening terbaru untuk satu versi; dipantau tiap detik selama masih berjalan. */
export function useLatestScreening(versionId: string | null | undefined, enabled = true, scope?: 'isbn' | 'layout', autoCreated = true) {
  const [run, setRun] = useState<ScreeningRun | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const emptyPolls = useRef(0)

  const load = useCallback(() => {
    if (!versionId) return
    api
      .get<ScreeningRun | null>(`/versions/${versionId}/screenings/latest`, scope ? { scope } : undefined)
      .then((r) => {
        emptyPolls.current = r ? 0 : emptyPolls.current + 1
        setRun(r)
        setLoaded(true)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [versionId, scope])

  useEffect(() => {
    if (enabled) load()
  }, [enabled, load])

  const running = !!run && RUNNING.has(run.status)
  useEffect(() => {
    const waitingForAuto = autoCreated && !run && emptyPolls.current < MAX_EMPTY_POLLS
    if (!enabled || (loaded && !running && !waitingForAuto)) return
    const t = setInterval(load, 1000)
    return () => clearInterval(t)
  }, [enabled, loaded, running, run, load, autoCreated])

  const rerun = useCallback(async () => {
    if (!run) return
    try {
      setRun(await api.post<ScreeningRun>(`/screenings/${run.id}/rerun`))
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [run])

  return { run, loaded, error, rerun, reload: load }
}
