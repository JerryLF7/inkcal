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
| `IMMICH_URL` | Immich server URL; code fallback `http://192.168.5.7:2283` |
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

## Labeling and Fine-Tuning

- `correct`: classifier/Gemini result is valid food recognition.
- `wrong`: a non-food image or wrong detection slipped through.
- Check progress with `intake label --status`.
- Export before training: `intake finetune --export`.
- Inspect `data/training/food/` and `data/training/not-food/`.
- Train with `intake finetune`; model saves to `data/finetuned-model/` and auto-loads on later runs.
- Training needs at least 4 labeled samples; useful training needs both `correct` and `wrong` examples.
