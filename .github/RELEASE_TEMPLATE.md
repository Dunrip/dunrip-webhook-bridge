## Release Summary

- Version: `vX.Y.Z`
- Type: patch/minor/major
- Highlights:
  - 
  - 

## Included Changes

- Core:
- Security:
- Operations:
- Docs:

## Migration / Compatibility Notes

- Breaking changes: yes/no
- Required env/config changes:
- Data migration required: yes/no

## Validation

- [ ] CI green
- [ ] Local tests passed (`PYTHONPATH=. .venv/bin/pytest tests/ -q`)
- [ ] Smoke checks validated in target environment

## Rollback Plan

- Tag to roll back to:
- Steps:

## Post-release Checklist

- [ ] Capture evidence bundle (`BASE_URL=https://<prod-url> RELEASE_VERSION=vX.Y.Z make post-release-verify`)
- [ ] Attach/link `docs/release-evidence/<release-or-date>/summary.md`
- [ ] Monitor alerts and logs for 30-60 minutes
- [ ] Confirm webhook delivery success rate baseline
- [ ] Open follow-up issues for deferred work
