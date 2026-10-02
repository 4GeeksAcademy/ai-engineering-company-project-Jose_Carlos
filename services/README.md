# `services` folder

This folder contains **all the backend services** (APIs and background workers) related to the company for the cross-functional AI Engineering project.

Each subfolder inside `services/` must correspond to **one specific service** (for example: `admin-api`, `data-processor-worker`) and include its own technical and functional documentation.

- **Main purpose**: to centralize all the backend logic, APIs, and queue consumers that support the company's use cases.
- **Recommendation**: document in this file (or in sub-READMEs) the services you add, their objective, the technology used, and how to run them.

## `api/` — incident analysis API (FastAPI)

Requirements: Python >= 3.12 (`pyproject.toml`; uv picks the version in `.python-version` and downloads it if missing) and [uv](https://docs.astral.sh/uv/).

Run every command **from the repository root**: the app is imported as `services.api.main` and imports `scripts.analyze`, both resolved from the current directory (from another directory it fails with `ModuleNotFoundError: No module named 'services'`).

```sh
uv sync --frozen                                                         # create .venv from uv.lock
uv run --locked uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Check it is running: `curl http://127.0.0.1:8000/` returns `{"message":"Bienvenid@ a la API de análisis de incidentes"}`. Interactive docs: http://127.0.0.1:8000/docs. The incident analyzer backoffice is served by the same process at http://127.0.0.1:8000/backoffice/.

Optional environment variables: `BACKOFFICE_CORS_ORIGINS` (comma-separated origins allowed to call the API; default `http://localhost:5500,http://127.0.0.1:5500`); in GitHub Codespaces, `CODESPACE_NAME` + `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN` add the forwarded `:5500` origin.

Tests (backend characterization, golden and model checks): `uv run --frozen pytest`. UI baseline: see [tests/ui/README.md](../tests/ui/README.md).

> _Spanish version: [README.es.md](./README.es.md)._
