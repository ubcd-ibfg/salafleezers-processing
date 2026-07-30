import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Mirrors FRONTEND_BASE_PATH from the backend (see
// src/salafleezers/web/app.py's resolve_frontend_base_path) so the built
// SPA's asset/API/WS URLs line up with whatever path prefix the server
// mounts itself under. Unset/blank/"/" means the default root deployment.
function resolveBasePath(raw: string | undefined): string {
  if (!raw) return '/'
  const trimmed = raw.replace(/^\/+|\/+$/g, '')
  return trimmed ? `/${trimmed}/` : '/'
}

const basePath = resolveBasePath(process.env.FRONTEND_BASE_PATH)

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  base: basePath,
  server: {
    proxy: {
      [`${basePath}api`]: {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      [`${basePath}ws`]: {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
})
