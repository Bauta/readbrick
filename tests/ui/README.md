# UI tests

Pure-function unit tests + one end-to-end smoke against the running dev server.

## Prereqs

```bash
cd tests/ui
npm install
npx playwright install chromium
```

## Run

```bash
# Unit tests (pure JS — no browser, no server)
npm run test:unit

# End-to-end smoke (requires `python -m server.app` running on :8000
# and at least one book uploaded for user_id=1)
npm run test:smoke
```
