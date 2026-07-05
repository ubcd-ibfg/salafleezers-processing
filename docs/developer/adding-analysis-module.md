# Adding an analysis module

Worked from the pattern actually used to add the KDE, distribution-comparison, and MSD
analyses in Phase 5/6 — three real modules that existed as pure functions in `analysis/stats.py`
but had no web endpoint until they were needed for the GUI's analysis panels.

## 1. Write the pure function first

It goes in `src/salafleezers/analysis/` (or a new file there), takes and returns plain
`numpy` arrays/dataclasses, and has **zero** imports from `web/` or `cli/`. If you're porting a
MATLAB routine, name it in the docstring (`"""Port of foo.m."""`) and note anywhere your
implementation *deviates* from a literal port — see [MATLAB → Python
mapping](matlab-mapping.md).

```python
# analysis/stats.py (already existed)
def kde(data, n_points=512, bandwidth="scott", x_range=None, weights=None) -> KDEResult: ...
```

Write its unit tests in `tests/test_analysis.py` against synthetic data — these should pass
without any MATLAB/Octave dependency. If a golden MATLAB fixture is feasible, add one too — see
[Testing & golden files](testing-golden-files.md).

## 2. Add request/response schemas

In `web/schemas.py`, a pydantic `Request` and `Result` pair, following the existing naming
convention (`<Name>Request` / `<Name>Result`):

```python
class KDERequest(BaseModel):
    session_id: str
    file_id: str
    channel: str = "extension"
    n_points: int = 512
    bandwidth: float | str = "scott"
    t_start: float | None = None
    t_end: float | None = None

class KDEResult(BaseModel):
    session_id: str
    file_id: str
    x: list[float]
    density: list[float]
    bandwidth: float
```

## 3. Add the route

In `web/api/analysis.py` — the route is a thin wrapper: resolve the session/file/channel
(there are shared `_get_session`/`_get_file`/`_resolve_channel`/`_crop_if_requested` helpers
already in that file), call straight into the pure function, wrap the result:

```python
@router.post("/kde", response_model=KDEResult, status_code=201)
async def run_kde(request: KDERequest):
    from salafleezers.analysis.stats import kde

    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time.astype(np.float64)
    data, _ = _crop_if_requested(data, time, request.t_start, request.t_end)

    r = kde(data, n_points=request.n_points, bandwidth=request.bandwidth)

    out = KDEResult(session_id=request.session_id, file_id=request.file_id,
                     x=r.x.tolist(), density=r.density.tolist(), bandwidth=r.bandwidth)
    session.kde_results[request.file_id] = out.model_dump()  # cache on the session
    return out
```

Add a matching test in `tests/test_web.py` using the `synthetic_session` fixture. Update the
router's module docstring (the `POST /api/...` list at the top of the file) — it's meant to
stay an accurate index of every route in the file.

## 4. Wire it into the CLI (optional)

Not every analysis needs a CLI subcommand — e.g. kinetics fitting currently only exists via the
API/GUI (see [Dwell-time kinetics](../physics/dwell-time-kinetics.md)). If you do want one,
follow the pattern in `cli/main.py`'s `stepfind`/`velocity`/`pwd` commands: a Typer command that
loads a processed file, calls the same pure function, and prints a Rich table or `--json`
output.

## 5. Wire it into the frontend

- Add the request/result TypeScript types to `frontend/src/lib/types.ts`, mirroring the
  pydantic schema field-for-field.
- Add a method to the `api` object in `frontend/src/lib/api.ts`.
- Write a small panel component (see `frontend/src/lib/panels/KdePanel.svelte` for the simplest
  example — params, a run button, a uPlot chart) and add it as a tab in
  `frontend/src/lib/panels/AnalysisPanels.svelte`.

Typecheck (`npm run check`), build (`npm run build`), and — this is the part that actually
catches bugs the typechecker can't — **drive it in a real browser**. See the `verify` skill /
[Testing & golden files](testing-golden-files.md) for why: a clean typecheck doesn't prove the
uPlot series data is shaped right or that the WebSocket messages round-trip correctly.

## 6. Full checklist

- [ ] Pure function in `analysis/`, with a docstring citing the MATLAB source (or explaining
      why there isn't one)
- [ ] Unit test(s) in `tests/test_analysis.py`
- [ ] (Optional but encouraged) golden fixture — see [Testing & golden
      files](testing-golden-files.md)
- [ ] Request/Result schemas in `web/schemas.py`
- [ ] Route in `web/api/analysis.py` + updated module docstring + test in `tests/test_web.py`
- [ ] (Optional) CLI subcommand in `cli/main.py`
- [ ] Frontend types + API client method + panel component, typechecked and built
- [ ] Exercised in a real browser session, not just typechecked
