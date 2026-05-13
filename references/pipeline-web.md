# inkcal Pipeline and Web UI

## Photo Pipeline

Use when Jerry asks to scan Immich photos or process a day.

1. Run from project root:

```bash
cd ~/Coding/inkcal
inkcal run [--date YYYY-MM-DD]
```

2. The pipeline is idempotent by `asset_id`; previously processed assets are skipped.
3. SigLIP2 food filtering runs locally.
4. Images confirmed as food are sent to the Gemini-compatible vision API.
5. Verify with `inkcal view --date YYYY-MM-DD`.

## Environment Variables

Stored in `~/Coding/inkcal/.env`.

| Variable | Purpose |
|----------|---------|
| `SOURCE` | Comma-separated list of photo sources. e.g. `immich`, `photoprism`, `immich,photoprism`. Backwards-compat: if unset and `IMMICH_API_KEY` exists, defaults to `immich`. |
| `IMMICH_URL` | Immich server URL; code fallback `http://192.168.5.7:2283` |
| `IMMICH_API_KEY` | Immich API key |
| `PHOTOPRISM_URL` | PhotoPrism server URL (only needed if SOURCE includes "photoprism") |
| `PHOTOPRISM_API_KEY` | PhotoPrism app password (only needed if SOURCE includes "photoprism") |
| `GEMINI_API_KEY` | Gemini/OpenAI-compatible API key |
| `GEMINI_BASE_URL` | Optional compatible endpoint |
| `GEMINI_MODEL` | Code fallback `gemini-3-flash-preview` |
| `INKCAL_USER` / `INKCAL_PASS` | Optional web auth — must be set together; server refuses to start otherwise |
| `INKCAL_SECRET` | Flask session signing key (persists login across restarts). Generate via `python -c "import secrets; print(secrets.token_hex(32))"` |
| `INKCAL_HOST` | Web bind address. Default `127.0.0.1` (local only). Set `0.0.0.0` for LAN/external access (prefer reverse proxy) |
| `INKCAL_PORT` | Web server port (default 5800) |
| `INKCAL_HTTPS` | Set `1` when behind HTTPS proxy — adds `Secure` flag to session cookies |
| `INKCAL_DEBUG` | Flask debug mode (default 0) |

## Web Viewer Workflow

Use for browser viewing, visual labels, replacing photos, and mobile UI tweaks.

1. Inspect before editing:

```text
~/Coding/inkcal/web/server.py
~/Coding/inkcal/web/static/index.html
```

2. Start preview from project root with a tracked background process:

```bash
INKCAL_PORT=5800 venv/bin/python web/server.py
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
- Check progress with `inkcal label --status`.
- Labeled records help track classifier accuracy over time.

## Reverse Proxy / FRP

When the web viewer sits behind a reverse proxy (FRP, nginx, Caddy, etc.), login rate limiting relies on the real client IP instead of the proxy's IP.

- The server reads `X-Forwarded-For` and `X-Real-IP` headers **only when the direct connection comes from `127.0.0.1` or `::1`**.
- If FRP runs on the same host, this works automatically.
- If your reverse proxy is on a different machine (e.g., a remote server forwarding to this host), set the proxy IP as trusted via env. Default local-only trust prevents header spoofing from the public internet.

### Cookie security behind HTTPS

If your reverse proxy terminates TLS, set `INKCAL_HTTPS=1` in `.env`. This adds the `Secure` flag to session cookies so browsers won't send them over plain HTTP.

## Album Photo Picker (Recommended)

When a photo is missed by the pipeline (e.g., beverages that SigLIP2 fails to recognize as food), use the **"📷 选择照片"** button. This is the preferred method because it leverages the existing photo library without re-uploading.

### Flow

1. Click "📷 选择照片" in the top-right corner.
2. A modal opens showing unprocessed photos from all configured sources (Immich + PhotoPrism), grouped by date.
3. **Scroll down** to load earlier dates (7 days per page, infinite scroll).
4. Click a thumbnail → the server downloads the original, sends it directly to Gemini (skips food detection because the user already selected it), and saves the record with the original `asset_id`.
5. If Gemini says "not real food", an alert is shown and nothing is saved.
6. After analysis, the view refreshes and opens the new record in the lightbox.
7. If the photo you want isn't in the album (e.g., a screenshot from someone else), click **"📤 从本地上传"** at the bottom of the modal to fall back to the legacy manual upload flow.

### API Endpoints

`GET /api/album-photos?cursor=YYYY-MM-DD&days=N`

- Returns unprocessed photos grouped by date. `cursor` defaults to today; `days` defaults to 7 (max 30).
- Response: `{dates: [{date: "...", photos: [{asset_id, thumbnail_url, photo_time, source}]}], next_cursor: "..."}`
- Photos are filtered against `db.get_processed_asset_ids(date)` and `ignored_assets`.
- Each source is queried independently; one source failing doesn't affect the others.

`POST /api/analyze-album-photo` (requires auth if enabled)

- Body: `application/json` with `asset_id`, `source` (immich/photoprism), `date`, `thumbnail_url`, `photo_time`.
- Downloads the original from the source, runs Gemini analysis (skips food detection), saves the record.
- Returns 409 if the asset was already processed (race condition with cron).
- Returns 422 if Gemini determines the image is not real food.

---

## Manual Photo Upload (Fallback)

Use when the photo is not in the album (e.g., screenshots, images from other apps).

### Flow

1. Click "📷 选择照片", then click **"📤 从本地上传"** at the bottom of the modal.
2. In the upload dialog, choose one of three methods:
   - **Click the drop zone** to open the system file picker
   - **Drag and drop** an image file onto the dashed-border area
   - **Press Ctrl+V** (or ⌘V) to paste an image from the clipboard
3. The client-side EXIF parser tries to extract the date from the image (supports JPEG, PNG, WebP). If found, the date is sent with the upload. If not, the server's Pillow-based EXIF extraction runs as a fallback (supports HEIC too).
4. **Gemini analysis runs first** — if the image is not food, the request returns 422 immediately, skipping the expensive pHash step.
5. If Gemini confirms it's food, the server searches Immich for a matching photo via perceptual hash (±5 min window when EXIF time is available, full-day search otherwise). PhotoPrism has no pHash API, so this step is skipped when only PhotoPrism is configured.
6. If matched in Immich, the record is linked to the real Immich `asset_id` and thumbnail URL — it looks and behaves like any auto-processed record.
7. If no Immich match is found, a `manual-<timestamp>` asset_id is generated and the image is saved to `data/images/`.
8. If the server couldn't determine the date (no EXIF at all), the record is saved to today's date and the date picker appears for post-upload correction.
9. After analysis completes, the view automatically refreshes and opens the new record in the lightbox.

### API Endpoints

`GET /api/album-photos?cursor=YYYY-MM-DD&days=N`

- Returns unprocessed album photos grouped by date. `cursor` defaults to today; `days` defaults to 7 (max 30).
- Response: `{dates: [{date: "...", photos: [{asset_id, thumbnail_url, photo_time, source}]}], next_cursor: "..."}`
- Each source (Immich/PhotoPrism) is queried independently per day; one source failing doesn't affect others.
- Photos are filtered against already-processed (`db.get_processed_asset_ids`) and ignored assets.

`POST /api/analyze-album-photo` (requires auth if enabled)

- Body: `application/json` with `asset_id`, `source` (immich/photoprism), `date`, `thumbnail_url`, `photo_time`.
- Downloads the original from the source, runs Gemini analysis **(skips food detection)**, saves the record.
- Returns 200 `{ok: true, record: {...}, date: "YYYY-MM-DD"}` on success.
- Returns 409 if the asset was already processed (race condition with cron).
- Returns 422 if Gemini determines the image is not real food.
- Returns 500 if downloading the original fails.

`POST /api/manual-upload` (requires auth if enabled)

- Body: `multipart/form-data` with `image` field (JPEG/PNG/HEIC/WebP). Optional `date` field (if client-side EXIF was read).
- Returns 200 `{ok: true, record: {...}, matched: bool, date: "YYYY-MM-DD", _date_source: "exif"|"user"|"fallback"}` on success.
- Returns 422 if Gemini determines the image is not real food.
- Returns 409 if the photo is already recorded for that date (duplicate check by Immich `asset_id`).
- **PhotoPrism note:** When only PhotoPrism is configured (no Immich), pHash matching is skipped and a `manual-` asset_id is generated with the image saved to `data/images/`.

`POST /api/move-record` (requires auth if enabled)

- Body: `application/json` with `asset_id` and `date` (new date YYYY-MM-DD).
- Updates the record's `date` and `photo_time` in SQLite, then re-runs Immich pHash matching on the corrected date.
- If pHash matches on the new date, the record is linked to the Immich asset (updates `asset_id` and `thumbnail_url`) and the local image file is deleted.
- **PhotoPrism note:** When the record has no Immich `asset_id`, only the date is updated (no pHash re-match).
- Returns 200 `{ok: true, asset_id, old_date, new_date, immich_matched: bool}`.

## Desktop Layout

The web UI is fully responsive. At viewport width >= 768px, it switches from single-column mobile layout to a two-panel desktop layout:

- **Left sidebar (280px)**: App header, upload button, quick-link buttons (今日/昨日/本周), always-visible calendar with green dots for dates with data.
- **Right main area**: Date navigation bar, summary stats bar, 2-column meal card grid.
- **Week view**: Day groups span the full width, cards within each day group flow in 2 columns.

All interactions (date switching, calendar clicks, lightbox, upload) work identically across both layouts.

## FRP / Slow Network Optimizations

When accessing via a reverse proxy or tunneled connection:

- Card thumbnails use Immich `size=thumbnail` (~7KB) instead of `size=preview` (~157KB). The lightbox still uses the full preview size.
- API responses include request sequencing (`_loadSeq`) to discard stale responses from rapid date-switching.
- Failed image loads retry once after 1 second.
- Dates with zero records (all deleted) are excluded from the `/api/dates` calendar dots.
- Content area shows a loading spinner immediately on date switch for instant feedback.
