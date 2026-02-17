# Deploy to Render

This project includes a Render blueprint (`deploy/render.yaml`) and is optimized for web-service deployment from Docker.

## Steps

1. Push repository to GitHub.
2. In Render, create a **Blueprint** service from this repo.
3. Confirm `deploy/Dockerfile` is detected (Render reads this from `deploy/render.yaml`).
4. Set required environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GITHUB_WEBHOOK_SECRET`
   - `GENERIC_WEBHOOK_TOKEN`
   - `ADMIN_API_KEYS` (recommended; supports single key or scoped CSV)
     - single key example: `ADMIN_API_KEYS=my-admin-key`
     - scoped example: `ADMIN_API_KEYS=read-key:read,replay-key:replay,admin-key:admin`
   - optional legacy fallback: `ADMIN_API_KEY`
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

## Optional Redis

Render can provision a Redis service. If enabled:
- Set `STORAGE_BACKEND=redis`
- Set `RATE_LIMIT_BACKEND=redis`
- Set `REDIS_URL=<render-redis-url>`

If Redis is not configured, defaults (`memory`) still work for a single instance.
