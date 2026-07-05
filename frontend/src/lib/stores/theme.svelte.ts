type Theme = 'light' | 'dark'

function initial(): Theme {
  const saved = localStorage.getItem('sfz.theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

class ThemeStore {
  current = $state<Theme>(initial())

  toggle() {
    this.current = this.current === 'dark' ? 'light' : 'dark'
    this.apply()
  }

  apply() {
    document.documentElement.dataset.theme = this.current
    localStorage.setItem('sfz.theme', this.current)
  }
}

export const theme = new ThemeStore()
