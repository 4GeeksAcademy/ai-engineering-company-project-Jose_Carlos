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

Optional environment variables: `BACKOFFICE_CORS_ORIGINS` (comma-separated origins allowed to call the API; default `http://localhost:5500,http://127.0.0.1:5500` plus `:3000` for the Next.js app); in GitHub Codespaces, `CODESPACE_NAME` + `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN` add the forwarded `:5500` and `:3000` origins.

### Authentication (JWT)

Before the first run, copy `.env.example` to `.env` and set `JWT_SECRET_KEY` (generate one with `uv run python -c "import secrets; print(secrets.token_urlsafe(64))"`). The API refuses to start without it. `ACCESS_TOKEN_EXPIRE_MINUTES` (default `30`) and `JWT_ALGORITHM` (default `HS256`) are optional. `.env` is git-ignored; variables already set in the environment take precedence.

`User` (credentials only: `id`, `email`, `hashed_password`, `is_active`, `role`, `created_at`) and `Profile` (`id`, `user_id`, `name`, `phone`, `address`) live **only in TinyDB**. The user `id` is a UUID string; it travels in the JWT `sub` claim and is what other modules store as `user_uuid`. Passwords are hashed with bcrypt (libpass). Stateless JWT only — no sessions or cookies.

| Route | Access |
| --- | --- |
| `POST /users` | public — register (role is always `user`; optional `name`, `phone`, `address` create the linked profile) |
| `POST /auth/login` | public — JSON `{email, password}` → `{access_token, token_type, expires_in}` |
| `POST /auth/token` | public — same login as an OAuth2 form (`username` = email); used by the **Authorize** button in `/docs` |
| `GET /auth/me` | token — email, role and linked profile |
| `POST /auth/forgot-password` | public — `{email}`; always `200` with the same message, whether or not the address is registered |
| `POST /auth/reset-password` | public — `{token, new_password}`; `400` if the token is invalid, expired or already used |
| `POST /auth/change-password` | token — `{current_password, new_password}`; `400` if the current password is wrong |
| `GET /users` | token, admin only |
| `GET/PUT/DELETE /users/{id}` | token, the user themself or an admin (`role`/`is_active` changes: admin only). DELETE also removes the profile |
| `GET/PUT /profiles/me` | token — own profile |
| `GET/PUT /profiles/{user_id}` | token, the owner or an admin |
| `POST /analyze`, `GET /api/incidents/results/export`, all `/suppliers` routes | token |

Missing, malformed, expired or invalid tokens get `401`; accessing another user's data gets `403`. `GET /` and `/backoffice/` stay public.

Create the first admin (or promote an existing user): `uv run python -m services.api.create_admin admin@example.com 'long-password' --name "Admin"`.

#### Password reset email (Resend)

`POST /auth/forgot-password` emails a reset link (`FRONTEND_URL/reset-password?token=…`) through [Resend](https://resend.com). Set these in `.env` (names documented in `.env.example`; never put the key in source code):

| Variable | Default | Purpose |
| --- | --- | --- |
| `RESEND_API_KEY` | empty | Resend API key. **If empty, no email is sent**: the reset link is written to the server log instead (development only). |
| `EMAIL_FROM` | `TrackFlow <onboarding@resend.dev>` | Sender. With `onboarding@resend.dev` (no own domain) Resend only delivers to the address of your Resend account. |
| `FRONTEND_URL` | `http://localhost:3000` | Base URL of the Next.js app, used to build the link. |
| `PASSWORD_RESET_EXPIRE_MINUTES` | `30` | Link lifetime, clamped to 15–60 minutes. |
| `PASSWORD_RESET_MAX_PER_HOUR` | `5` | Reset links issued per user per hour; extra requests still answer `200` but send nothing. |

The reset token is a signed JWT (`type: password_reset`) with a `jti` stored in the TinyDB table `password_resets`. Using it, or changing the password, marks every pending link of that user as used, so a link works once. Session tokens carry `type: access`; neither kind is accepted in place of the other.

Manual check in `/docs`: `POST /users` → **Authorize** (email in `username`) → call `GET /auth/me`.

Frontends: the backoffice (`/backoffice/`) redirects to `/backoffice/login.html` without a valid token and sends `Authorization: Bearer` on every call (`uis/backoffice/auth.js`). The Next.js app has `/login`, `/register` and `/account/profile` (see [its README](../uis/talent-pipeline-tracker/README.md)). The two apps keep separate sessions (different origins, separate `localStorage`).

Tests (backend characterization, golden, model and auth checks): `uv run --frozen pytest`. UI baseline: see [tests/ui/README.md](../tests/ui/README.md).

> _Spanish version: [README.es.md](./README.es.md)._
