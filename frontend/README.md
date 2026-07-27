# SalaFleezer GUI frontend

Svelte 5 + TypeScript + Vite single-page app for `sfz gui`. Talks to the
FastAPI backend in `../src/salafleezers/web/` over REST and one WebSocket
(`/ws/session/{id}`).

## Develop

```sh
npm ci
npm run dev      # Vite dev server on :5173, proxying /api and /ws to :8765
```

Run the backend separately (`uv run sfz gui --no-browser`) so the dev
server has something to proxy to.

## Build

```sh
npm run build     # → dist/, force-included into the Python wheel at build time
npm run check     # svelte-check + tsc, no build output
```

`dist/` is required for `sfz gui` to serve anything — without it the app
mounts a blank page (see `src/salafleezers/web/app.py::_find_spa_dir`).

## Layout

- `src/lib/data/` — upload intake: drag-and-drop / folder picker, the upload
  queue, and the dataset rail.
- `src/lib/ui/` — small shared primitives (`RunButton` + `useRun.svelte.ts`
  for the running/error/elapsed pattern every analysis panel uses, `Card`,
  `Tabs`).
- `src/lib/theme/plot.ts` — the only place chart colors are read from CSS
  custom properties; uPlot draws on canvas, so colors must be resolved to
  concrete strings before reaching it.
- `src/lib/panels/` — the six analysis tabs (velocity, PWD, kinetics, KDE,
  distributions, MSD), each a thin form + `Plot` around one backend endpoint.
- `src/lib/stores/` — `session.svelte.ts` (the active session + loaded
  files), `theme.svelte.ts`, `auth.svelte.ts` (bearer token for shared-lab
  deployments).
- `src/lib/api.ts` / `src/lib/types.ts` — hand-mirrored REST client; keep
  `types.ts` in sync with `src/salafleezers/web/schemas.py`.
