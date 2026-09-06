# Deploying to Railway

The same containers that run locally (`docker compose up`) deploy to Railway
unchanged. Railway provides the persistent process the backend needs (SSE, the
30 s Monte Carlo compute, the in-process event bus + process pool) — no
serverless reshaping. Three services + one plugin:

## 1. Postgres (plugin)
Add the **Postgres** plugin. Railway injects `DATABASE_URL` — but it uses the
`postgresql://` scheme, and this app uses async `asyncpg`. Set a service
variable on the backend:
```
DATABASE_URL = ${{Postgres.DATABASE_URL}}   # then ensure the scheme is
                                             # postgresql+asyncpg://
```
If Railway's value is `postgresql://…`, override to
`postgresql+asyncpg://…` (same host/creds). Alembic's async env handles it.

## 2. Backend service
- **Source:** this repo, root `backend/` (Dockerfile detected).
- `backend/railway.json` runs `alembic upgrade head` before uvicorn, so the
  schema is migration-managed in prod.
- **Variables:**
  ```
  ENVIRONMENT=production
  AUTO_CREATE_TABLES=false          # Alembic owns the schema in prod
  JWT_SECRET=<32+ byte random>
  COOKIE_SECURE=true                # HTTPS
  COOKIE_SAMESITE=lax
  FRONTEND_ORIGIN=https://<frontend-domain>
  ARTIFACTS_DIR=/srv/data/artifacts
  USE_PROCESS_POOL=true             # numpy off the event loop in prod
  MARKET_DATA_PROVIDER=synthetic
  ACTIVE_SNAPSHOT_ID=synthetic-2024-12-31
  ```
- **Volume:** mount one at `/srv/data/artifacts` for the memory-mapped
  snapshot artifacts (persists across restarts).

## 3. Frontend service
- **Source:** repo root `frontend/` (Dockerfile detected).
- **Build variable:** `NEXT_PUBLIC_API_URL=https://<backend-domain>` — it is
  inlined into the client bundle at build time, so it must be the browser-
  reachable backend URL, and a change requires a rebuild.

## Cross-origin notes
- The frontend and backend are different origins in prod. `COOKIE_SECURE=true`
  + `SameSite=Lax` works when both are HTTPS on the same site; if they are on
  unrelated domains, set `COOKIE_SAMESITE=none` (requires Secure) so the
  session cookie and `EventSource` SSE flow cross-site.
- `FRONTEND_ORIGIN` must exactly match the frontend URL (CORS with credentials
  cannot use `*`).

## Email
No mail provider is wired yet — verification/reset tokens are logged. Before a
real launch, implement `on_after_request_verify` / `on_after_forgot_password`
in `backend/app/auth/users.py` to send email, and point the verify link at
`https://<frontend-domain>/verify?token=…`.
