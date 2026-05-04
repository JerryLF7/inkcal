# intake Pipeline and Web UI

## Photo Pipeline

Use when Jerry asks to scan Immich photos or process a day.

1. Run from project root:

```bash
cd ~/Coding/intake
intake run [--date YYYY-MM-DD]
```

2. The pipeline is idempotent by `asset_id`; previously processed assets are skipped.
3. SigLIP2 food filtering runs locally.
4. Images confirmed as food are sent to the Gemini-compatible vision API.
5. Verify with `intake view --date YYYY-MM-DD`.

## Environment Variables

Stored in `~/Coding/intake/.env`.

| Variable | Purpose |
|----------|---------|
| `IMMICH_URL` | Immich server URL; code fallback `http://your-immich-host:2283` |
| `IMMICH_API_KEY` | Immich API key |
| `GEMINI_API_KEY` | Gemini/OpenAI-compatible API key |
| `GEMINI_BASE_URL` | Optional compatible endpoint |
| `GEMINI_MODEL` | Code fallback `gemini-3-flash-preview` |
| `INTAKE_USER` / `INTAKE_PASS` | Optional web auth — must be set together; server refuses to start otherwise |
| `INTAKE_SECRET` | Flask session signing key (persists login across restarts). Generate via `python -c "import secrets; print(secrets.token_hex(32))"` |
| `INTAKE_HOST` | Web bind address. Default `127.0.0.1` (local only). Set `0.0.0.0` for LAN/external access (prefer reverse proxy) |
| `INTAKE_PORT` | Web server port (default 5800) |
| `INTAKE_HTTPS` | Set `1` when behind HTTPS proxy — adds `Secure` flag to session cookies |
| `INTAKE_DEBUG` | Flask debug mode (default 0) |

## Web Viewer Workflow

Use for browser viewing, visual labels, replacing photos, and mobile UI tweaks.

1. Inspect before editing:

```text
~/Coding/intake/web/server.py
~/Coding/intake/web/static/index.html
```

2. Start preview from project root with a tracked background process:

```bash
INTAKE_PORT=5800 python3 web/server.py
```

3. Verify readiness:

```bash
curl -sS http://127.0.0.1:5800/api/today
ss -ltnp | grep ':5800'
```

4. Open `http://127.0.0.1:5800/` with browser tools.
5. Test real interactions: today view, specific date view, card lightbox, label button, replacement upload path when relevant.
6. For date UI, use local-date formatting (`getFullYear()`, `getMonth()+1`, `getDate()`) to avoid timezone day shifts.
7. Keep picker value, visible date label, active shortcut chips, and fetched `/api/records?date=YYYY-MM-DD` data synchronized.

## Labeling

- `correct`: classifier/Gemini result is valid food recognition.
- `wrong`: a non-food image or wrong detection slipped through.
- Check progress with `intake label --status`.
- Labeled records help track classifier accuracy over time.

## Reverse Proxy / FRP

When the web viewer sits behind a reverse proxy (FRP, nginx, Caddy, etc.), login rate limiting relies on the real client IP instead of the proxy's IP.

- The server reads `X-Forwarded-For` and `X-Real-IP` headers **only when the direct connection comes from `127.0.0.1` or `::1`**.
- If FRP runs on the same host, this works automatically.
- If your reverse proxy is on a different machine (e.g., a remote server forwarding to this host), set the proxy IP as trusted via env. Default local-only trust prevents header spoofing from the public internet.

### Cookie security behind HTTPS

If your reverse proxy terminates TLS, set `INTAKE_HTTPS=1` in `.env`. This adds the `Secure` flag to session cookies so browsers won't send them over plain HTTP.

## Manual Photo Upload

When a photo is missed by the pipeline (e.g., beverages that SigLIP2 fails to recognize as food), use the web UI's manual upload button.

### Flow

1. Click "📤 上传" in the top-right corner of the web UI.
2. Select a photo from your device. The original file is preferred over screenshots or compressed versions.
3. The server extracts EXIF data for date/time, sends the photo to Gemini for calorie analysis, then searches Immich for a matching photo via perceptual hash.
4. If matched in Immich, the record is linked to the real Immich `asset_id` and thumbnail URL — it looks and behaves like any auto-processed record.
5. If no Immich match is found, a `manual-<timestamp>` asset_id is generated and the image is saved to `data/images/`.

### API Endpoint

`POST /api/manual-upload` (requires auth if enabled)

- Body: `multipart/form-data` with `image` field (JPEG/PNG/HEIC/WebP).
- Returns 200 `{ok: true, record: {...}, matched: bool, date: "YYYY-MM-DD"}` on success.
- Returns 422 if Gemini determines the image is not real food.
- Returns 409 if the photo is already recorded for that date (duplicate check by Immich `asset_id`).
