# inkcal — Automated Food Calorie Tracker

## Project Overview

Photo → Immich / PhotoPrism → SigLIP2 (local CPU, food detection) → Gemini (cloud, calorie analysis) → `data/inkcal.db` (SQLite).

Privacy-first: only photos passing the local food filter are sent to the cloud API. Pipeline is idempotent by `asset_id`. Multiple photo sources can be enabled simultaneously via `SOURCE=immich,photoprism`.

**Core Value Proposition — "Zero-Friction"**: The user does nothing except take a photo before eating. The mobile Immich app auto-backs up photos in the background. The inkcal cron job polls Immich every 20 minutes, runs food detection locally, sends only food photos to Gemini for calorie analysis, and writes results to SQLite. The next time the user opens the web UI, the day's stats are already there. No manual upload, no meal description, no app switching.

## Project Layout

```
inkcal/
├── main.py                    # CLI entry point (argparse, 6 subcommands)
├── src/
│   ├── immich_client.py       # Immich REST API client (httpx, pHash matching, timezone-aware photo_time formatting)
│   ├── photoprism_client.py   # PhotoPrism REST API client (httpx, cookie-free thumbnails, timezone parsing)
│   ├── food_detector.py       # SigLIP2 lazy-load wrapper (auto-loads finetuned-model if present)
│   ├── calorie_analyzer.py    # Gemini-compatible vision API (OpenAI format, JSON structured output, retry)
│   └── db.py                  # SQLite data layer (records, reanalysis_history, ignored_assets tables)
├── web/
│   ├── server.py              # Flask app (auth, image proxy, records API)
│   └── static/index.html      # SPA (vanilla JS, dark theme, localStorage cache-first, responsive mobile/desktop layout, calendar sidebar, lightbox, drag-and-drop upload, refresh button)
├── references/
│   ├── cli-workflows.md       # CLI commands, natural-language meal logging, estimation rules
│   └── pipeline-web.md        # Photo pipeline steps, env vars, web UI workflow, labeling, reverse proxy
├── setup.sh                   # Creates ~/.local/bin/inkcal bash wrapper + cron (every 20 min)
├── scripts/inkcal             # Bash wrapper: calls venv/bin/python main.py "$@"
├── data/                      # gitignored — inkcal.db (SQLite), finetuned-model/, images/
├── SKILL.md                   # Claude skill definition (when to use, core rules, quick reference)
├── DEVELOPMENT.md             # Project timeline, architecture decisions, lessons learned
└── README.md                  # User-facing docs
```

## Key Conventions

- **Timezone**: All dates are Asia/Hong_Kong (UTC+8). Date boundaries follow HKT.
- **Idempotency**: `already_processed()` queries SQLite for existing `asset_id`s by date; pipeline skips processed photos.
- **Manual records**: Generated `manual-<timestamp>` as asset_id, same schema as Immich records.
- **Data format**: `data/inkcal.db` — SQLite with `records`, `reanalysis_history`, and `ignored_assets` tables. See `src/db.py` for schema.
- **CLI only**: Never edit the database directly. Use `inkcal add/view/label/replace/migrate`.
- **Commit style**: Short imperative messages, `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- **Commit scope**: Commit specific files by name, never `git add -A` or `git add .`. Never commit `.env`.

## Environment Variables

All in `.env` at project root. See `references/pipeline-web.md` for the full table.

Critical ones: `IMMICH_URL`, `IMMICH_API_KEY`, `GEMINI_API_KEY`, `INKCAL_SECRET` (fixed value for session persistence), `INKCAL_USER`/`INKCAL_PASS` (must be set together or both empty).

## Web Server (`web/server.py`)

- **Port**: 5800 (default, overridable via `INKCAL_PORT`)
- **Auth**: Optional. `INKCAL_USER` + `INKCAL_PASS` both set → login required. Both empty → no auth. Mismatch → crashes at startup.
- **Session**: HTTP-only, SameSite=Lax, Secure if `INKCAL_HTTPS=1`, permanent (30 days). `INKCAL_SECRET` fixes session key across restarts.
- **Rate limiting**: In-memory, 5 attempts / 300s per IP. Cleared on successful login.
- **Trusted proxies**: `X-Forwarded-For` / `X-Real-IP` only read when `request.remote_addr` is `127.0.0.1` or `::1`. IPs validated with `ipaddress.ip_address()`.
- **Image proxy**: `/api/image?url=` validates URL starts with `IMMICH_URL` or `PHOTOPRISM_URL`, adds API key header (Immich only), streams response. `/api/local-image` has path traversal guard via `Path.is_relative_to()`.
- **Album photo picker**: "📷 选择照片" button opens a modal showing unprocessed photos from all configured sources (Immich/PhotoPrism), grouped by date with infinite-scroll pagination (7 days per page). Clicking a thumbnail downloads the original, sends directly to Gemini (skips food detection since the user already selected it), and saves the record. "📤 从本地上传" button falls back to the legacy manual upload flow. Backend: `GET /api/album-photos?cursor=YYYY-MM-DD&days=N` returns paginated unprocessed photos; `POST /api/analyze-album-photo` downloads original + Gemini analysis + save (no food detection).
- **Manual upload**: `/api/manual-upload` accepts an image file, runs Gemini analysis first, then matches against Immich via pHash (skip wasteful pHash when Gemini rejects non-food images). Returns 422 if Gemini says "not food", 409 if already processed. Client-side EXIF parser supports JPEG/PNG/WebP for instant date detection; server-side Pillow handles HEIC as fallback. Web UI offers drag-and-drop, clipboard paste (Ctrl+V), file picker, and post-upload date correction via `/api/move-record`.
- **Responsive layout**: Mobile (<768px) preserves the original single-column 480px layout. Desktop (>=768px) uses CSS Grid with a 280px sidebar (always-visible calendar, quick links) and a 2-column meal card grid.
- **FRP optimization**: Card thumbnails use Immich `size=thumbnail` (7KB, not 157KB `preview`) for faster loading over tunneled connections. Request sequencing prevents stale responses from overwriting the current view. Images auto-retry on load failure. `apiFetch()` wraps all API calls with 10s timeout via AbortController and one automatic retry on timeout. Cross-request abort (`_abortController`) cancels in-flight requests when the user navigates to a new date. `_fetchId` dedup prevents stale retries from contaminating newer views.
- **localStorage cache-first**: All date/day views use cache-first strategy — render from cache instantly, background fetch for updates. Week view cached by Monday-based key. Dates list cached with 5-minute TTL. Cache invalidated on manual upload and image replacement. Private browsing degrades gracefully (try/catch on all localStorage calls).
- **Refresh button**: ↻ button next to the date label clears the current day's cache and re-fetches from the server. Spins during the request. Only affects the currently loaded date.
- **Start with**: `INKCAL_PORT=5800 venv/bin/python web/server.py` from project root, or `inkcal run --command serve`. Must use venv Python (not system) — `imagehash` and `pillow-heif` live there. Use `fuser -k 5800/tcp` to stop.
- **Login page**: Hardcoded inline HTML in server.py (not served from static/).

## CLI (`main.py`)

6 subcommands: `run`, `view`, `add`, `label`, `replace`, `migrate`. The `inkcal` command in PATH is a bash wrapper at `~/.local/bin/inkcal` that calls `~/Coding/inkcal/venv/bin/python ~/Coding/inkcal/main.py "$@"`. Cron uses this wrapper.

Always verify mutations with `inkcal view [--date]` or `inkcal label --status`.

## Natural Language Meal Logging

See `references/cli-workflows.md` for full workflow. Key points:
- Extract meal description, calories, macros, date, time from user messages.
- Default date is today HKT. Use `--date` and `--time` when implied.
- Confidence: `high` (exact numbers), `medium` (default), `low` (estimates).
- Multiple meals → one `inkcal add` per meal.
- Verify with `inkcal view` after logging.

## Known Gotchas

1. **Cron**: Must use venv Python. The `scripts/inkcal` bash wrapper handles this.
2. **Session loss on restart**: If `INKCAL_SECRET` is not set in `.env`, Flask generates a random key on each restart, invalidating all sessions.
3. **Login behind FRP**: Without `X-Forwarded-For` handling, all users share the same IP (the reverse proxy's). The trusted proxy logic in `_client_ip()` fixes this.
4. **Port already in use after kill**: `pkill -f web/server.py` sometimes leaves the port bound. Use `fuser -k <port>/tcp` instead.
5. **Gemini rejection**: Gemini may return `meal: "not real food"` for screenshots/menus/packaging. The pipeline now checks this and skips those records.
6. **SigLIP2 blind spot — drinks**: The base `prithivMLmods/Food-or-Not-SigLIP2` model systematically under-detects handheld beverages (milk tea, coffee, bottled drinks in transparent cups). Its "food" concept skews toward plated meals. Missed photos can be picked from the album via the "选择照片" modal (skips food detection, goes straight to Gemini) or manually uploaded as fallback.
7. **FRP / slow network**: Over tunneled connections, large thumbnail images (157KB `preview` size) can cause broken images and slow loads. The frontend now requests `size=thumbnail` (7KB) for cards. Rapid date-switching can cause out-of-order API responses — request sequencing (`_loadSeq`) and cross-request abort (`_abortController`) prevent this. All API calls go through `apiFetch()` with 10s timeout + one retry. localStorage cache-first eliminates redundant fetches for revisited dates. A manual refresh button (↻) lets users force-refresh without full browser reload.
8. **Clipboard/PNG images lack EXIF**: When pasting from clipboard or uploading screenshots, the image is typically PNG with no EXIF metadata. Client-side EXIF parser (JPEG/PNG/WebP) and server-side Pillow both fail, falling back to today's date. The post-upload date picker then lets the user correct the date, and `/api/move-record` re-runs pHash matching on the corrected date. Always upload the original camera JPEG/HEIC when possible — the pipeline relies on EXIF for date/time and for precise ±5 min Immich pHash search windows.
9. **Restart without venv → upload fails**: Server must start from project root using `venv/bin/python web/server.py` (not system `python`). System Python lacks `pillow-heif`, `google-genai`, and other venv-only dependencies — the server starts but image upload (Gemini analysis, HEIC decoding) silently fails with "上传失败，请检查网络连接". Always check you're in the inkcal project's venv before restarting.
10. **Timezone — use Immich `exifInfo`, not thumbnail EXIF**: Immich already parses EXIF server-side into `exifInfo.timeZone` and `exifInfo.dateTimeOriginal`. Do NOT re-download thumbnails to parse EXIF tags for timezone conversion — thumbnails may have EXIF stripped during processing, causing incorrect `+00:00` timestamps. The pipeline uses `format_photo_time()` which reads `asset["exifInfo"]` directly. Note: Immich's `timeZone` format is `UTC+8` (not `+08:00`), and some photos return IANA names like `Asia/Shanghai` — the parser handles both and falls back to HKT for unknown formats.
11. **SQLite WAL mode concurrency**: `src/db.py` enables WAL (`PRAGMA journal_mode=WAL`) and opens connections with `check_same_thread=False` so Flask's multi-threaded server can share a single connection. CLI commands call `init_db()` at entry and do not need explicit close for read-only operations. The `.db-wal` and `.db-shm` files are normal — do not delete them while the server is running.
12. **Migration idempotency**: `inkcal migrate` refuses to run if `data/inkcal.db` already exists. Use `--force` only if you intend to wipe and re-migrate from JSON backups. After migration, original JSON files are moved to `data/migrated-json-backup/`.
13. **Project rename — intake → inkcal**: If you encounter old references to `intake` in external scripts or configs, update them. The `.env` env vars are `INKCAL_*`; the CLI command is `inkcal`; the database is `data/inkcal.db`.

## Related Project: food-classifier

Standalone SigLIP2 fine-tuning project at `~/Coding/food-classifier/`. Produces models to `~/Coding/inkcal/data/finetuned-model/`, which `src/food_detector.py` auto-loads. See that project's CLAUDE.md for details.
