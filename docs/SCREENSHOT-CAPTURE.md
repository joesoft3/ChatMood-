# UI screenshot capture

Capture the latest product UI screens locally or in CI.

## Prereqs
- backend running
- frontend running
- Playwright browser installed

## Install browser once

```bash
cd frontend
npx playwright install chromium
```

## Capture screenshots

```bash
WEB_URL=http://127.0.0.1:4100 \
UI_SHOT_EMAIL=owner@example.com \
UI_SHOT_PASSWORD=OwnerPass123! \
node scripts/capture-ui.mjs
```

Screens land in:

```text
artifacts/ui-shots/
```

## Pages captured
- landing
- login
- chat
- files
- plugins
- research
- media lab
- design studio
- films
- voice
- settings
- admin
- mobile login/chat/media/settings
