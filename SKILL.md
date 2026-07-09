---
name: inkcal
slug: inkcal
version: 1.7.0
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
- API endpoint changes (base URL, key, model) and JSON parsing fixes
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
8. **API JSON parsing**: Gemini-compatible endpoints may return truncated JSON (missing `}`) or JSON with extra trailing `}`. Both are handled in `src/calorie_analyzer.py` `_parse_response()`. See `references/api-truncation-fix.md`.
9. **Cron false-positive cache pitfall**: The crontab runs `inkcal run` every 10 minutes (or whatever was last set). There are two paths that must be cached to avoid repeated Gemini calls:
   - **Local classifier false positive**: persist the negative decision to `classified_non_food`; never to `ignored_assets`.
   - **Gemini rejects as non-food**: persist the `asset_id` to `ignored_assets` when Gemini returns `meal` of `not real food` or `unknown`.
   If Jerry reports "Gemini is called constantly", check both caches and the cron frequency. See the Cron False-Positive Cache Pitfall section below.
10. **Web server lifecycle**: Before starting, always check if already running on port 5800. If user says "开一下" and it's already running, just report status. See `references/pipeline-web.md` for full workflow.

## Quick Reference

| Task | Load |
|------|------|
| CLI commands, meal logging, queries, estimation | `references/cli-workflows.md` |
| Photo pipeline, env vars, web UI, labeling, server lifecycle | `references/pipeline-web.md` |
| API truncation / extra-brace fixes and provider quirks | `references/api-truncation-fix.md` |
| Cron false positives and repeated Gemini calls | Cron False-Positive Cache Pitfall section below |
| User-facing docs and architecture | `README.md`, `usage.md` |

## Cron False-Positive Cache Pitfall

### Symptom

Jerry notices that the Gemini-compatible vision API is being called far more often than expected, even though his Immich album does not contain that many food photos. The SQLite `records` table does not show duplicate entries, but the API usage dashboard shows repeated calls.

### Two Root Causes

The cron job (e.g. `*/10 * * * * /home/jerry/.local/bin/inkcal run`) fetches the day's photos, runs the local SigLIP2 food classifier, and sends positives to Gemini. Two categories of photos can be re-sent on every tick if they are not cached:

1. **Local classifier false positives** — the classifier says "food" but the image is not food. The original code did not persist the classifier's negative decision at all, so every false positive was re-evaluated every tick. **Fix**: persist these to `classified_non_food` and keep them visible in the web album picker for manual correction.

2. **Gemini rejects the image as non-food** — the local classifier says "food", but Gemini returns `"meal": "not real food"` or `"unknown"`. The current code path must add these `asset_id`s to `ignored_assets`; otherwise the same image will be sent to Gemini again on the next cron tick.

### Fix

#### 1. Local classifier false positives

Add a `classified_non_food` table in `src/db.py`:

```sql
CREATE TABLE IF NOT EXISTS classified_non_food (
    asset_id TEXT PRIMARY KEY,
    classified_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

In `main.py` inside `_run_source()`:

```python
if not detector.is_food(thumb):
    logger.info("  ❌ 不是食物，跳过")
    db.add_classified_non_food(aid)
    continue
```

Combine `ignored_assets` and `classified_non_food` when deciding what to skip:

```python
def load_ignored() -> set[str]:
    return db.get_ignored_assets() | db.get_classified_non_food()
```

In `web/server.py`, the album picker (`/api/album-photos`) should only filter `ignored_assets`, not `classified_non_food`, so misclassified non-food photos remain visible. Return a `classified_non_food` flag per photo so the UI can optionally mark them.

When a user manually analyzes an album photo via `analyze-album-photo`, remove the asset from `classified_non_food` so the pipeline state stays consistent.

#### 2. Gemini rejects as non-food

In `main.py` inside `_run_source()`, after calling `analyzer.analyze(original)`:

```python
if result.get("meal") in ("not real food", "unknown"):
    logger.info("  ❌ Gemini 判定非真实食物，跳过")
    db.add_ignored_asset(aid)
    continue
```

This prevents the same rejected photo from being sent to Gemini on every cron tick. Because `ignored_assets` is also used to hide photos from the web album picker, a Gemini rejection is treated as a strong, automatic non-food decision that the user is unlikely to want to correct. If Jerry later asks to keep rejected photos visible for manual correction, move them to `classified_non_food` instead.

### Why Separate Caches?

- `ignored_assets` = user-level or strong automatic ignores. Photos here are hidden from the album picker.
- `classified_non_food` = local classifier's uncertain negative decision. Photos here remain visible in the album picker so the user can manually correct a classifier mistake.

### Secondary Recommendation

Even with both caches, a 10-minute cadence is usually unnecessary for a personal photo album. Consider reducing cron frequency:

- Every 2 hours: `0 */2 * * * /home/jerry/.local/bin/inkcal run`
- Every 6 hours: `0 */6 * * * /home/jerry/.local/bin/inkcal run`
- On-demand: remove the cron entry and run `inkcal run` manually after meals.

Change it with `crontab -e`.

### Diagnosis

If the symptom recurs, check these in order:

1. **Crontab frequency**: `crontab -l | grep inkcal`
2. **Counts**: `classified_non_food` and `ignored_assets` should grow as non-food photos are encountered.
3. **Run output**: `inkcal run` should print "未处理: 0 张 (忽略 N 张)" when all non-food photos are cached.
4. **Records vs. Gemini calls**: records count per day should be far lower than cron-tick count.
5. **Classifier accuracy**: review `inkcal label --status` for false positives and consider improving the fine-tuned model or raising a confidence threshold.
