# Deploy on Vercel (Free Tier Friendly)

This project supports Vercel via `api/index.py` + `vercel.json`. Canonical deployment config is `deploy/vercel.json`.

`api/index.py` imports the canonical ASGI app from `app.main`.

## 1) Import project to Vercel

Use the one-click prefilled link (recommended):

- https://vercel.com/new/clone?repository-url=https://github.com/Dunrip/dunrip-webhook-bridge&env=TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID,GITHUB_WEBHOOK_SECRET,GENERIC_WEBHOOK_TOKEN,ADMIN_API_KEYS,STORAGE_BACKEND,RATE_LIMIT_BACKEND,REDIS_URL&envDescription=Telegram%20bot%20token,Telegram%20destination%20chat%20ID,GitHub%20webhook%20secret,Generic%20webhook%20token,Scoped%20admin%20keys%20CSV,Storage%20backend%20(memory%20or%20redis),Rate-limit%20backend%20(memory%20or%20redis),Redis%20connection%20URL

Or manual flow:
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

Optional but strongly recommended (production):

- `STORAGE_BACKEND=redis`
- `RATE_LIMIT_BACKEND=redis`
- `REDIS_URL=<Upstash/Redis URL>`

If you stay on memory mode (quick tests / low-stakes usage):

- `STORAGE_BACKEND=memory`
- `RATE_LIMIT_BACKEND=memory`
- `REDIS_URL` can be omitted

> Redis edge case: if either backend is set to `redis`, you must set `REDIS_URL` or the app will attempt default local Redis and fall back to memory with degraded durability.
>
> On serverless, use Redis-backed state for production reliability. In-memory state resets between invocations and can break idempotency, replay history, and queue durability.

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

- Request handler path is optimized for fast ingest/ack and deferred processing behavior.
- WebSocket log stream (`/stream/logs`) is best-effort on serverless and should degrade gracefully when upgrades are unsupported.
- `/metrics` is available but Vercel instances are ephemeral; use external scraping/storage if needed.
- For always-on long-lived ops behavior, VPS/Docker is still the strongest option.
