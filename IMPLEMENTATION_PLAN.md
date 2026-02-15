# Webhook Bridge - Implementation Phases

## Phase 1: "Actually Production" (Priority: Critical)

### 1.1 Redis Persistence for Idempotency + Failed Queue ✅ DONE
**Why:** Survives restarts, enables replay
**Files:**
- `storage.py` - Abstract storage interface + Redis implementation
- `config.py` - Add Redis connection settings
- `main.py` - Replace in-memory dict with storage backend
- `docker-compose.yml` - Add Redis service

**Acceptance Criteria:**
- [x] `STORAGE_BACKEND=redis` env var works
- [x] Restarting container doesn't lose idempotency state
- [x] Failed deliveries stored with full payload
- [x] SQLite fallback for simple deployments

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

### 2.2 Failed Delivery Replay API ✅ DONE
**Why:** Retry failed webhooks manually
**Files:**
- `replay.py` - Replay endpoints + logic
- `main.py` - Add `/deliveries`, `/deliveries/{id}/replay`

**Acceptance Criteria:**
- [x] `GET /deliveries` lists failed deliveries with filters
- [x] `POST /deliveries/{id}/replay` retries specific delivery
- [x] `POST /deliveries/replay-all` retries all failed
- [x] Updates delivery status after replay

### 2.3 Jinja2 Template Engine ✅ DONE
**Why:** Custom message formatting
**Files:**
- `templates.py` - Template loader + renderer
- `config.py` - Template directory setting
- `tg_client.py` - Add template-based formatting option
- `templates/default/` - Default templates per event type

**Acceptance Criteria:**
- [x] `TEMPLATE_DIR` env var specifies custom templates
- [x] Falls back to built-in formatters if no template
- [x] `POST /templates/validate` validates custom template
- [x] Hot-reload templates without restart

---

## Phase 3: "Category Leader" (Priority: Medium)

### 3.1 Multi-Destination Routing ✅ DONE
**Why:** One webhook → multiple channels/platforms
**Files:**
- `routing.py` - Route rules engine
- `config.py` - Routes configuration
- `destinations/` - Telegram, Discord, Slack clients
- `main.py` - Apply routing before sending

**Acceptance Criteria:**
- [x] YAML-based routing rules
- [x] Multiple Telegram chats per webhook
- [x] Discord webhook support
- [x] Conditional routing based on payload fields

### 3.2 GitHub App Auto-Discovery ✅ DONE
**Why:** No manual webhook setup per repo
**Files:**
- `github_app.py` - GitHub App integration
- `main.py` - Add `/github/install` endpoint

**Acceptance Criteria:**
- [x] OAuth flow for GitHub App installation
- [x] Auto-registers webhooks on all accessible repos
- [x] Handles new repo creation events
- [x] Stores installation tokens securely

### 3.3 Real-Time Log Stream (WebSocket) ✅ DONE
**Why:** Live debugging without tailing logs
**Files:**
- `websocket.py` - WebSocket endpoint for log streaming
- `main.py` - Add `/stream/logs` endpoint

**Acceptance Criteria:**
- [x] WebSocket connection streams webhook events
- [x] Filter by event type, status, repo
- [x] Web UI for viewing stream
- [x] Connection survives brief disconnects

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
