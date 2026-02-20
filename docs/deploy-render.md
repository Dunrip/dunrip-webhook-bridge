# Deploy to Render

This project includes a Render blueprint (`deploy/render.yaml`) and is optimized for web-service deployment from Docker.

## Steps

1. Push repository to GitHub.
2. In Render, create a **Blueprint** service from this repo.
3. Confirm `deploy/Dockerfile` is detected (Render reads this from `deploy/render.yaml`).
4. Set required environment variables (Render blueprint prompts these):
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GITHUB_WEBHOOK_SECRET`
   - `GENERIC_WEBHOOK_TOKEN`
   - `ADMIN_API_KEYS` (supports single key or scoped CSV)
     - single key example: `ADMIN_API_KEYS=my-admin-key`
     - scoped example: `ADMIN_API_KEYS=read-key:read,replay-key:replay,admin-key:admin`
   - `STORAGE_BACKEND` (`memory` or `redis`)
   - `RATE_LIMIT_BACKEND` (`memory` or `redis`)
   - `REDIS_URL` (required if either backend is `redis`)
5. Deploy and wait until health check `/health` is green.

## Configure GitHub webhook

In your GitHub repo:
- Settings -> Webhooks -> Add webhook
- Payload URL: `https://<render-service>/webhook/github`
- Content type: `application/json`
- Secret: same as `GITHUB_WEBHOOK_SECRET`
- Events: Pushes, Pull requests, Issues, Releases, Workflow runs

## Verify deployment

```bash
BASE_URL="https://<render-service>" ./scripts/smoke-test.sh
```

## Redis prompt handling

When Render asks for backend mode and URL, use one of these profiles:

### Profile A — Simple / single instance (memory)
- `STORAGE_BACKEND=memory`
- `RATE_LIMIT_BACKEND=memory`
- `REDIS_URL=redis://redis:6379/0` (ignored in memory mode)

### Profile B — Production durability (Redis)
- `STORAGE_BACKEND=redis`
- `RATE_LIMIT_BACKEND=redis`
- `REDIS_URL=<render-redis-url>`

If either backend is set to `redis` but `REDIS_URL` is invalid/missing, runtime will degrade to memory fallback and durability guarantees are reduced.
