# Deploy on Vercel (Free Tier Friendly)

This project supports Vercel via `api/index.py` + `vercel.json`.

`api/index.py` imports the canonical ASGI app from `app.main`.

## 1) Import project to Vercel

1. Go to https://vercel.com/new
2. Import `Dunrip/dunrip-webhook-bridge`
3. Keep default framework settings (Vercel will detect Python via `api/index.py`)

## 2) Configure Environment Variables

In **Project Settings → Environment Variables**, add at minimum:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GITHUB_WEBHOOK_SECRET`
- `GENERIC_WEBHOOK_TOKEN`
- `ADMIN_API_KEYS` (recommended) or `ADMIN_API_KEY`

Optional but recommended:

- `STORAGE_BACKEND=redis`
- `RATE_LIMIT_BACKEND=redis`
- `REDIS_URL=<Upstash/Redis URL>`

> On serverless, memory backends reset often; Redis gives stable idempotency/replay/rate-limit behavior.

## 3) Deploy

Click **Deploy**. Once complete, your base URL will look like:

`https://<project>.vercel.app`

Webhook endpoint:

`https://<project>.vercel.app/webhook/github`

## 4) Add GitHub Webhook

In your GitHub repo:

- Settings → Webhooks → Add webhook
- Payload URL: your Vercel webhook URL above
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`

## Notes / Limitations

- WebSocket log stream (`/stream/logs`) is not ideal on serverless environments.
- `/metrics` is available but Vercel instances are ephemeral; use external scraping/storage if needed.
- For always-on long-lived ops behavior, VPS/Docker is still the strongest option.
