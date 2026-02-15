# Webhook-to-Telegram Bridge

A FastAPI service that forwards GitHub and generic JSON webhooks to Telegram.

## Supported Events

- **GitHub**: push, pull request, issue events with formatted messages
- **Generic**: any JSON payload with title/body/url fields

## Setup

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) and get the token.

2. **Get your chat ID** by sending a message to the bot, then visiting:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

4. **Install and run**:
   ```bash
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

## GitHub Webhook Setup

1. Go to your repo **Settings > Webhooks > Add webhook**
2. Set Payload URL to `https://your-domain/webhook/github`
3. Set Content type to `application/json`
4. Set Secret to your `GITHUB_WEBHOOK_SECRET` value
5. Select events: Pushes, Pull requests, Issues

## Generic Webhook

```bash
curl -X POST https://your-domain/webhook/generic \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: your-generic-token" \
  -d '{"title": "Deploy", "body": "v1.2.3 deployed to production", "url": "https://example.com"}'
```

## Health Check

```
GET /health
```
