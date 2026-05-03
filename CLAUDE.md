# intake — Automated Food Calorie Tracker

## Project Overview

Photo → Immich → SigLIP2 (local CPU, food detection) → Gemini (cloud, calorie analysis) → `data/YYYY-MM-DD.json`.

Privacy-first: only photos passing the local food filter are sent to the cloud API. Pipeline is idempotent by `asset_id`.

## Project Layout

```
intake/
├── main.py                    # CLI entry point (argparse, 5 subcommands)
├── src/
│   ├── immich_client.py       # Immich REST API client (httpx, pHash matching, EXIF extraction)
│   ├── food_detector.py       # SigLIP2 lazy-load wrapper (auto-loads finetuned-model if present)
│   └── calorie_analyzer.py    # Gemini-compatible vision API (OpenAI format, JSON structured output, retry)
├── web/
│   ├── server.py              # Flask app (auth, image proxy, records API)
│   └── static/index.html      # SPA (vanilla JS, dark theme, calendar, lightbox, image replacement)
├── references/
│   ├── cli-workflows.md       # CLI commands, natural-language meal logging, estimation rules
│   └── pipeline-web.md        # Photo pipeline steps, env vars, web UI workflow, labeling, reverse proxy
├── setup.sh                   # Creates ~/.local/bin/intake bash wrapper + cron (every 20 min)
├── scripts/intake             # Bash wrapper: calls venv/bin/python main.py "$@"
├── data/                      # gitignored — YYYY-MM-DD.json records, finetuned-model/, images/
├── SKILL.md                   # Claude skill definition (when to use, core rules, quick reference)
├── DEVELOPMENT.md             # Project timeline, architecture decisions, lessons learned
└── README.md                  # User-facing docs
```

## Key Conventions

- **Timezone**: All dates are Asia/Hong_Kong (UTC+8). Date boundaries follow HKT.
- **Idempotency**: `already_processed()` extracts existing `asset_id` from daily JSON; pipeline skips processed photos.
- **Manual records**: Generated `manual-<timestamp>` as asset_id, same JSON format as Immich records.
- **Data format**: `data/YYYY-MM-DD.json` — list of `{asset_id, photo_time, thumbnail_url, meal, calories, protein_g, carbs_g, fat_g, confidence, analyzed_at, user_label, replacement_image}`.
- **CLI only**: Never edit JSON files directly. Use `intake add/view/label/replace`.
- **Commit style**: Short imperative messages, `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- **Commit scope**: Commit specific files by name, never `git add -A` or `git add .`. Never commit `.env`.

## Environment Variables

All in `.env` at project root. See `references/pipeline-web.md` for the full table.

Critical ones: `IMMICH_URL`, `IMMICH_API_KEY`, `GEMINI_API_KEY`, `INTAKE_SECRET` (fixed value for session persistence), `INTAKE_USER`/`INTAKE_PASS` (must be set together or both empty).

## Web Server (`web/server.py`)

- **Port**: 5800 (default, overridable via `INTAKE_PORT`)
- **Auth**: Optional. `INTAKE_USER` + `INTAKE_PASS` both set → login required. Both empty → no auth. Mismatch → crashes at startup.
- **Session**: HTTP-only, SameSite=Lax, Secure if `INTAKE_HTTPS=1`, permanent (30 days). `INTAKE_SECRET` fixes session key across restarts.
- **Rate limiting**: In-memory, 5 attempts / 300s per IP. Cleared on successful login.
- **Trusted proxies**: `X-Forwarded-For` / `X-Real-IP` only read when `request.remote_addr` is `127.0.0.1` or `::1`. IPs validated with `ipaddress.ip_address()`.
- **Image proxy**: `/api/image?url=` validates URL starts with `IMMICH_URL`, adds API key header, streams response. `/api/local-image` has path traversal guard via `Path.is_relative_to()`.
- **Start with**: `INTAKE_PORT=5800 python3 web/server.py` from project root. Use `fuser -k 5801/tcp` to stop (not pkill which may leave port bound).
- **Login page**: Hardcoded inline HTML in server.py (not served from static/).

## CLI (`main.py`)

5 subcommands: `run`, `view`, `add`, `label`, `replace`. The `intake` command in PATH is a bash wrapper at `~/.local/bin/intake` that calls `~/Coding/intake/venv/bin/python ~/Coding/intake/main.py "$@"`. Cron uses this wrapper.

Always verify mutations with `intake view [--date]` or `intake label --status`.

## Natural Language Meal Logging

See `references/cli-workflows.md` for full workflow. Key points:
- Extract meal description, calories, macros, date, time from user messages.
- Default date is today HKT. Use `--date` and `--time` when implied.
- Confidence: `high` (exact numbers), `medium` (default), `low` (estimates).
- Multiple meals → one `intake add` per meal.
- Verify with `intake view` after logging.

## Known Gotchas

1. **Cron**: Must use venv Python. The `scripts/intake` bash wrapper handles this.
2. **Session loss on restart**: If `INTAKE_SECRET` is not set in `.env`, Flask generates a random key on each restart, invalidating all sessions.
3. **Login behind FRP**: Without `X-Forwarded-For` handling, all users share the same IP (the reverse proxy's). The trusted proxy logic in `_client_ip()` fixes this.
4. **Port already in use after kill**: `pkill -f web/server.py` sometimes leaves the port bound. Use `fuser -k <port>/tcp` instead.
5. **Gemini rejection**: Gemini may return `meal: "not real food"` for screenshots/menus/packaging. The pipeline now checks this and skips those records.

## Related Project: food-classifier

Standalone SigLIP2 fine-tuning project at `~/Coding/food-classifier/`. Produces models to `~/Coding/intake/data/finetuned-model/`, which `src/food_detector.py` auto-loads. See that project's CLAUDE.md for details.
