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

# Run pipeline (Immich/PhotoPrism → SigLIP2 → Gemini)
inkcal run                           # today
inkcal run --date 2026-04-28         # specific date

# Label records (correct/wrong) for classifier training
inkcal label --list                  # list unlabeled records
inkcal label --id xxxxx --label correct
inkcal label --status                # global labeling progress

# Replace a record's image via pHash matching
inkcal replace --id xxxxx --image ~/path/to/image.jpg

# Migrate legacy JSON files to SQLite
inkcal migrate
```

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

- Records: `~/Coding/inkcal/data/inkcal.db` (SQLite)
- Fine-tuned model (optional): `data/finetuned-model/`
- Replacement images: `data/images/` (only for unmatched uploads)
- Migrated JSON backups: `data/migrated-json-backup/`
