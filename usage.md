# inkcal — Usage Reference

## CLI

`~/.local/bin/inkcal` → `~/Coding/inkcal/main.py`

```bash
# Manual entry
inkcal add --meal "红烧牛肉面" --calories 550 --protein 25 --carbs 70 --fat 15

# View
inkcal view                          # today
inkcal view --date 2026-04-28        # specific day
inkcal view --week                   # this week
inkcal view --month 2026-04          # monthly
inkcal view --from 2026-07-01 --to 2026-07-14  # date range

# Stats (aggregate over date range)
inkcal stats --last 7d               # last week
inkcal stats --last 1m               # last month
inkcal stats --from 2026-07-01 --to 2026-07-14 --group-by day

# Edit a record directly (old values preserved in history)
inkcal edit --ref 42 --calories 300 --note "两人份，减半"
inkcal edit --meal 红烧肉 --date 2026-07-21 --protein 30

# Search meal descriptions (FTS5 full-text)
inkcal search 咖喱
inkcal search 鸡胸 --from 2026-07-01 --to 2026-07-22

# Delete a record (auto-adds to ignore list)
inkcal delete --ref 42
inkcal delete --last

# Run pipeline (Immich/PhotoPrism → SigLIP2 → Gemini)
inkcal run                           # today
inkcal run --date 2026-04-28         # specific date

# Label records (correct/wrong) for classifier training
inkcal label --list                  # list unlabeled records
inkcal label --ref 42 --label correct
inkcal label --meal 咖喱 --date 2026-07-21 --label wrong
inkcal label --status                # global labeling progress

# Replace a record's image via pHash matching
inkcal replace --ref 42 --image ~/path/to/image.jpg

# Explain where a photo ended up in the pipeline
inkcal explain --id <asset-prefix>   # single photo's decision trail
inkcal explain --date 2026-07-21     # full day reconciliation

# Analyze a classifier-missed photo with Gemini (skip food detection)
inkcal analyze --id <asset-id> --source immich

# Re-analyze a record with additional context
inkcal reanalyze --ref 42 --notes "少算了一份米饭，实际是两人份"

# Pull unconsumed pipeline events (for agent proactive reporting)
inkcal events
inkcal events --peek                 # view without marking consumed
inkcal events --consumed --limit 20  # historical events

# Migrate legacy JSON files to SQLite
inkcal migrate
```

All read commands support `--json` for structured output.

## Record Locator

Four ways to locate a record (usable with edit/label/replace/delete/reanalyze):

| Flag | Example | Description |
|---|---|---|
| `--ref N` | `--ref 42` | Record's integer ID (from `--json` output) |
| `--id PREFIX` | `--id e3f47028` | Asset ID prefix match |
| `--last` | `--last` | Most recent record |
| `--meal K --date D` | `--meal 红烧肉 --date 2026-07-21` | Keyword search + date |

## Web Viewer

```bash
cd ~/Coding/inkcal
venv/bin/python web/server.py        # http://localhost:5800
# or: inkcal run --command serve
```

### Auth

Set `INKCAL_USER` and `INKCAL_PASS` in `.env` to enable login. Leave empty to skip.

### Labeling flow

1. Tap a meal card → lightbox with full image
2. Tap "正确" or "有误" to label
3. "换图" to upload a replacement (auto-matched to Immich via pHash)

### Reanalysis flow

1. Tap "描述细节" in lightbox
2. Add details (portion size, missed ingredients, etc.)
3. Ctrl+Enter to submit → Gemini re-analyzes with context
4. History is preserved; latest result becomes current

## Workflows

### 记录一餐
```
user: 午饭吃了红烧牛肉面，大概550卡
→ inkcal add --meal "红烧牛肉面" --calories 550
→ reply: ✅ 已记录 红烧牛肉面 ~550kcal (今日)
```

### 带宏量的记录
```
user: 中午吃了鸡胸肉沙拉，400卡，蛋白35g
→ inkcal add --meal "鸡胸肉沙拉" --calories 400 --protein 35
```

### 查记录
```
user: 今天吃了多少
→ inkcal view
→ reply with table + daily summary
```

### 查某天
```
user: 看看周一吃了什么
→ inkcal view --date 2026-04-27
→ reply with table
```

## Data Storage

- Records: `~/Coding/inkcal/data/inkcal.db` (SQLite, WAL mode)
- Tables: `records`, `reanalysis_history`, `ignored_assets`, `classified_non_food`, `pipeline_events`, `records_fts`
- Replacement images: `data/images/` (only for unmatched uploads)
- Migrated JSON backups: `data/migrated-json-backup/`
