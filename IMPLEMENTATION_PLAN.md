# Webhook Bridge - Implementation Phases

## Phase 1: "Actually Production" (Priority: Critical)

### 1.1 Redis Persistence for Idempotency + Failed Queue
**Why:** Survives restarts, enables replay
**Files:**
- `storage.py` - Abstract storage interface + Redis implementation
- `config.py` - Add Redis connection settings
- `main.py` - Replace in-memory dict with storage backend
- `docker-compose.yml` - Add Redis service

**Acceptance Criteria:**
- [ ] `STORAGE_BACKEND=redis` env var works
- [ ] Restarting container doesn't lose idempotency state
- [ ] Failed deliveries stored with full payload
- [ ] SQLite fallback for simple deployments

### 1.2 Rate Limiting Middleware
**Why:** Prevent DDoS, protect Telegram API
**Files:**
- `middleware.py` - Rate limiting using slowapi or custom
- `config.py` - Rate limit settings
- `main.py` - Apply middleware to webhook endpoints

**Acceptance Criteria:**
- [ ] Per-IP rate limiting (default: 10 req/min)
- [ ] Per-webhook-token rate limiting for generic endpoint
- [ ] Returns 429 with Retry-After header
- [ ] Redis-backed for distributed deployments

### 1.3 GitHub Actions CI/CD
**Why:** Automated testing, releases, Docker builds
**Files:**
- `.github/workflows/ci.yml` - Test on PR/push
- `.github/workflows/release.yml` - Build + push Docker image on tag

**Acceptance Criteria:**
- [ ] Tests run on every PR
- [ ] Docker image pushed to GHCR on release
- [ ] Multi-arch builds (amd64, arm64)
- [ ] Coverage report in PR comments

---

## Phase 2: "Stand Out" (Priority: High)

### 2.1 Webhook Sandbox
**Why:** Test formatting without spamming channels
**Files:**
- `sandbox.py` - Sandbox router + logic
- `main.py` - Add `/webhook/github/sandbox` endpoint
- `templates/sandbox.html` - Simple UI for testing (optional)

**Acceptance Criteria:**
- [ ] POST to `/webhook/github/sandbox` returns formatted message
- [ ] Does NOT send to Telegram
- [ ] Shows parsed payload fields
- [ ] Returns 200 with preview JSON

### 2.2 Failed Delivery Replay API
**Why:** Retry failed webhooks manually
**Files:**
- `replay.py` - Replay endpoints + logic
- `main.py` - Add `/deliveries`, `/deliveries/{id}/replay`

**Acceptance Criteria:**
- [ ] `GET /deliveries` lists failed deliveries with filters
- [ ] `POST /deliveries/{id}/replay` retries specific delivery
- [ ] `POST /deliveries/replay-all` retries all failed
- [ ] Updates delivery status after replay

### 2.3 Jinja2 Template Engine
**Why:** Custom message formatting
**Files:**
- `templates.py` - Template loader + renderer
- `config.py` - Template directory setting
- `tg_client.py` - Add template-based formatting option
- `templates/default/` - Default templates per event type

**Acceptance Criteria:**
- [ ] `TEMPLATE_DIR` env var specifies custom templates
- [ ] Falls back to built-in formatters if no template
- [ ] `POST /templates/validate` validates custom template
- [ ] Hot-reload templates without restart

---

## Phase 3: "Category Leader" (Priority: Medium)

### 3.1 Multi-Destination Routing
**Why:** One webhook → multiple channels/platforms
**Files:**
- `routing.py` - Route rules engine
- `config.py` - Routes configuration
- `destinations/` - Telegram, Discord, Slack clients
- `main.py` - Apply routing before sending

**Acceptance Criteria:**
- [ ] YAML-based routing rules
- [ ] Multiple Telegram chats per webhook
- [ ] Discord webhook support
- [ ] Conditional routing based on payload fields

### 3.2 GitHub App Auto-Discovery
**Why:** No manual webhook setup per repo
**Files:**
- `github_app.py` - GitHub App integration
- `main.py` - Add `/github/install` endpoint

**Acceptance Criteria:**
- [ ] OAuth flow for GitHub App installation
- [ ] Auto-registers webhooks on all accessible repos
- [ ] Handles new repo creation events
- [ ] Stores installation tokens securely

### 3.3 Real-Time Log Stream (WebSocket)
**Why:** Live debugging without tailing logs
**Files:**
- `websocket.py` - WebSocket endpoint for log streaming
- `main.py` - Add `/stream/logs` endpoint

**Acceptance Criteria:**
- [ ] WebSocket connection streams webhook events
- [ ] Filter by event type, status, repo
- [ ] Web UI for viewing stream
- [ ] Connection survives brief disconnects

---

## Implementation Notes

### Tech Stack Decisions
- **Redis:** `redis-py` with asyncio support
- **Rate Limiting:** `slowapi` (FastAPI-native) or custom middleware
- **Templates:** `Jinja2` (standard, well-known)
- **WebSockets:** FastAPI native `WebSocket` class

### Testing Strategy
- Unit tests for each new module
- Integration tests with Redis (testcontainers)
- CI runs full test suite

### Backward Compatibility
- All new features opt-in via env vars
- Default behavior unchanged
- Storage backend defaults to memory (current behavior)
