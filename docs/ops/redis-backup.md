# Redis Backup & Restore (VPS)

This guide covers simple Redis backup/restore procedures for webhook-bridge deployments on a VPS.

## Scope

Back up Redis data used by:
- idempotency keys
- failed delivery queue (replay)
- rate-limit state (if Redis backend enabled)

## Prerequisites

- SSH access to VPS
- Docker Compose deployment or host Redis access
- Enough disk space for `.rdb` snapshots

## Option A: Docker Compose Redis (recommended)

### 1) Trigger save and copy snapshot

```bash
docker compose -f deploy/docker-compose.yml exec redis redis-cli BGSAVE
docker compose -f deploy/docker-compose.yml exec redis ls -lh /data/dump.rdb
docker compose -f deploy/docker-compose.yml cp redis:/data/dump.rdb ./backups/dump-$(date +%F-%H%M).rdb
```

### 2) Verify backup file

```bash
ls -lh ./backups/
redis-check-rdb ./backups/dump-YYYY-MM-DD-HHMM.rdb
```

### 3) Restore from snapshot

```bash
docker compose -f deploy/docker-compose.yml down
cp ./backups/dump-YYYY-MM-DD-HHMM.rdb ./redis-data/dump.rdb
docker compose -f deploy/docker-compose.yml up -d redis
```

> Ensure your Redis volume/path maps to where `dump.rdb` is loaded.

## Option B: Host-managed Redis

### Backup

```bash
redis-cli -h 127.0.0.1 -p 6379 BGSAVE
sudo cp /var/lib/redis/dump.rdb /var/backups/redis/dump-$(date +%F-%H%M).rdb
```

### Restore

```bash
sudo systemctl stop redis-server
sudo cp /var/backups/redis/dump-YYYY-MM-DD-HHMM.rdb /var/lib/redis/dump.rdb
sudo chown redis:redis /var/lib/redis/dump.rdb
sudo systemctl start redis-server
```

## Suggested Retention

- Daily snapshots for 7 days
- Weekly snapshots for 4 weeks
- Monthly snapshots for 3 months

## Post-restore Checks

- `docker compose -f deploy/docker-compose.yml logs redis --tail=100` (or `journalctl -u redis-server`)
- Verify webhook-bridge can read/write keys
- Run `make smoke`
- Confirm `/health/deep` and replay endpoints behave normally
