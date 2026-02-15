# Migration Notes: v1.2 (Track B - Network Boundary Controls)

## New environment variables

- `ADMIN_IP_ALLOWLIST`
  - Comma-separated IPv4/IPv6 addresses and/or CIDRs.
  - Enforced on all `/deliveries*` admin/replay endpoints.
  - Empty value disables admin allowlist checks.

- `WS_IP_ALLOWLIST`
  - Optional websocket-specific allowlist for `/stream/logs`.
  - If empty, falls back to `ADMIN_IP_ALLOWLIST`.

## Existing variable interaction

- `TRUSTED_PROXIES` continues to control whether `X-Forwarded-For` is trusted.
- Allowlist decisions use the effective client IP from trusted-proxy-aware extraction logic.

## Enforcement behavior

- **Fail-open only when allowlist is empty**.
- **Fail-closed when allowlist is configured**:
  - HTTP admin/replay endpoints return `403` with structured error and `request_id`.
  - WebSocket `/stream/logs` closes with code `1008` (policy violation).

## Audit reason codes

Allowlist denials are logged via admin audit logs with reason codes:

- `admin_allowlist_denied` (HTTP `/deliveries*`)
- `ws_allowlist_denied` (WebSocket `/stream/logs`)

## Example configurations

```env
# Behind reverse proxy
TRUSTED_PROXIES=10.0.0.0/24
ADMIN_IP_ALLOWLIST=203.0.113.10,203.0.113.0/24
WS_IP_ALLOWLIST=198.51.100.0/24
```

```env
# Single allowlist for both admin and websocket
ADMIN_IP_ALLOWLIST=203.0.113.0/24
WS_IP_ALLOWLIST=
```
