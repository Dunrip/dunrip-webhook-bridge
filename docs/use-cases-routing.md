# Routing Use Cases

## Multiple repositories → one chat

Goal: send webhook notifications from many repos into a single Telegram chat.

### Example

```yaml
routes:
  - name: engineering-shared-chat
    match:
      source: github
      repository:
        - org/repo-a
        - org/repo-b
        - org/repo-c
    destination:
      type: telegram
      chat_id: -1001234567890
```

Use this for team-wide visibility where one channel tracks activity across related projects.

## Multi-chat routing

Goal: route different repositories/events to different chats.

### Example

```yaml
routes:
  - name: backend-chat
    match:
      source: github
      repository: org/backend-service
    destination:
      type: telegram
      chat_id: -1001111111111

  - name: mobile-chat
    match:
      source: github
      repository: org/mobile-app
    destination:
      type: telegram
      chat_id: -1002222222222

  - name: releases-chat
    match:
      source: github
      event_type: release
    destination:
      type: telegram
      chat_id: -1003333333333
```

Use this to keep noisy signals scoped to owners while still broadcasting high-signal events (e.g., releases) to a wider audience.

## Notes

- Keep route matching specific to avoid accidental fan-out.
- If no route matches, events are ignored when routing mode is enabled.
- Validate route changes in staging before production rollout.
