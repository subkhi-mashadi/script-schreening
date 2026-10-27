const KEY = 'sn_theme'

export type Theme = 'light' | 'dark'

export function currentTheme(): Theme {
  const stamped = document.documentElement.dataset.theme
  if (stamped === 'light' || stamped === 'dark') return stamped
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyStoredTheme(): void {
  try {
    const t = localStorage.getItem(KEY)
    if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t
  } catch {
    /* penyimpanan browser tidak tersedia: ikuti pengaturan OS */
  }
}

export function setTheme(t: Theme): void {
  document.documentElement.dataset.theme = t
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* abaikan */
  }
}
