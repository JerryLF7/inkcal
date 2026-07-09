---
name: inkcal
slug: inkcal
version: 1.6.0
description: Log meals, analyze food photos, track calories and macros, and label results.
category: productivity
---

## When to Use

Use this skill for Jerry's inkcal food tracker:

- Meal logging: "记一下吃了", "午饭/晚饭吃了", "今天吃了", "昨晚吃了"
- Calorie or macro queries: "热量", "卡路里", "蛋白", "碳水", "脂肪", "吃了多少"
- Photo pipeline: Immich → SigLIP2 → Gemini → daily records
- Web UI viewing, labeling, image replacement, or mobile UI tweaks
- Web server start/stop/restart operations
- Classifier accuracy tracking via labeling
- API endpoint changes (base URL, key, model) and JSON truncation fixes
- Cron debugging, false-positive food classification, and repeated Gemini calls

## Data Storage

- Project path: `~/Coding/inkcal/`
- Records: `~/Coding/inkcal/data/inkcal.db` (SQLite)
- Fine-tuned model (optional): `~/Coding/inkcal/data/finetuned-model/`

## External Endpoints

| Service | Use | Privacy note |
|---------|-----|--------------|
| Immich | Photo listing and thumbnails on local network | Private photos stay in LAN during filtering |
| Gemini-compatible vision API | Calorie/macro analysis for detected food photos | Only photos passing local food filter are sent |

## Core Rules

1. Use `inkcal` CLI for all records, labels, and replacements; avoid direct JSON edits.
2. Parse natural language into meal, calories, macros, date, and time. Prefer Chinese meal descriptions.
3. Manual entries require `--meal` and `--calories`; macros via `--protein`, `--carbs`, `--fat`.
4. Default date is today in Asia/Hong_Kong. Use `--date YYYY-MM-DD` and `--time HH:MM` when implied.
5. Default confidence is `medium`; use `high` for exact numbers, `low` for rough estimates.
6. After mutations, verify with `inkcal view`, `inkcal label --status`, or the web UI.
7. For code changes, inspect files first, preserve existing user changes, verify, then commit.
8. **API JSON truncation fix**: When a Gemini-compatible endpoint returns truncated JSON (missing closing `}`), apply the fix in `src/calorie_analyzer.py` `_parse_response()`. See `references/api-truncation-fix.md`.
9. **Cron false-positive cache pitfall**: The default crontab (`*/20 * * * * inkcal run`) runs the full pipeline every 20 minutes. The local food classifier's false positives would otherwise be re-downloaded, re-classified, and re-sent to Gemini on every tick. **Do not** persist the classifier's negative decision to `ignored_assets`, because that table is also used to hide photos from the web album picker. Use a separate `classified_non_food` table for the automatic negative cache; `ignored_assets` is reserved for explicit user ignores. If Jerry reports "Gemini is called every 20 minutes", check that the classifier has a persistent negative cache separate from user-ignored assets and consider lowering the cron frequency. See the Cron False-Positive Cache Pitfall section below.
10. **Web server lifecycle**: Before starting, always check if already running on port 5800. If user says "开一下" and it's already running, just report status. See `references/pipeline-web.md` for full workflow.

## Quick Reference

| Task | Load |
|------|------|
| CLI commands, meal logging, queries, estimation | `references/cli-workflows.md` |
| Photo pipeline, env vars, web UI, labeling, server lifecycle | `references/pipeline-web.md` |
| API truncation fixes and provider quirks | `references/api-truncation-fix.md` |
| Cron false positives and repeated Gemini calls | Cron False-Positive Cache Pitfall section below |
| User-facing docs and architecture | `README.md`, `usage.md` |

## Cron False-Positive Cache Pitfall

### Symptom

Jerry notices that the Gemini-compatible vision API is being called roughly every 20 minutes, even though his Immich album does not contain that many food photos. The SQLite `records` table does not show duplicate entries, but the API usage dashboard shows far more requests than expected.

### Root Cause

`setup.sh` installs a crontab entry that runs the full pipeline every 20 minutes:

```cron
*/20 * * * * /home/jerry/.local/bin/inkcal run
```

Each run fetches the day's photos from Immich, downloads each one, and runs the local SigLIP2 food classifier. If the classifier mislabels a non-food image as food (a false positive), that image is sent to Gemini. The original code path only persisted **Gemini's** rejection (`not real food` / `unknown`) to `ignored_assets`; it did **not** persist the local classifier's **negative** decision. Therefore, every false-positive image was re-evaluated on every cron tick, producing repeated Gemini calls for the same non-food photo.

### Fix

Persist the classifier's negative decision to a dedicated table so subsequent cron runs skip the asset, while keeping the photo visible in the web album picker for manual correction.

1. Add a `classified_non_food` table in `src/db.py`:

```sql
CREATE TABLE IF NOT EXISTS classified_non_food (
    asset_id TEXT PRIMARY KEY,
    classified_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

2. In `main.py` (the cron pipeline), add false-negative photos to this table and skip them on future runs:

```python
# main.py, inside _run_source()
if not detector.is_food(thumb):
    logger.info("  ❌ 不是食物，跳过")
    db.add_classified_non_food(aid)
    continue
```

Also combine `ignored_assets` and `classified_non_food` when deciding what to skip:

```python
def load_ignored() -> set[str]:
    return db.get_ignored_assets() | db.get_classified_non_food()
```

3. In `web/server.py`, the album picker (`/api/album-photos`) should only filter `ignored_assets`, not `classified_non_food`, so misclassified non-food photos remain visible. Return a `classified_non_food` flag per photo so the UI can optionally mark them.

4. When a user manually analyzes an album photo via `analyze-album-photo`, remove the asset from `classified_non_food` so the pipeline state stays consistent.

### Why Not `ignored_assets`?

`ignored_assets` is the source of truth for **user-level** ignores (e.g., clicking "Ignore" in the web UI). Hiding auto-classified non-food photos there would remove them from the album picker, preventing users from manually correcting a classifier mistake. Keep the two caches separate.

### Secondary Recommendation

Even with the cache, a 20-minute cadence is usually unnecessary for a personal photo album. Consider reducing cron frequency. Common choices:

- Every 2 hours: `0 */2 * * * /home/jerry/.local/bin/inkcal run`
- Every 6 hours: `0 */6 * * * /home/jerry/.local/bin/inkcal run`
- On-demand: remove the cron entry and run `inkcal run` manually after meals.

Change it with `crontab -e`.

### Diagnosis

If the symptom recurs, check these in order:

1. **Crontab frequency**: `crontab -l | grep inkcal`
2. **Count of cached non-food assets**: query `classified_non_food` table in `data/inkcal.db`.
3. **Records vs. Gemini calls**: records count per day should be far lower than cron-tick count.
4. **Classifier accuracy**: review `inkcal label --status` for false positives and consider improving the fine-tuned model or raising a confidence threshold.
