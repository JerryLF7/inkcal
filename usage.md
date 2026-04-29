# intake — Usage Reference

## CLI

`~/.local/bin/intake` → `~/Coding/intake/main.py`

```bash
# Manual entry
intake add --meal "红烧牛肉面" --calories 550 --protein 25 --carbs 70 --fat 15

# View
intake view                          # today
intake view --date 2026-04-28        # specific day
intake view --week                   # this week
intake view --month 2026-04          # monthly

# Run pipeline (Immich → SigLIP2 → Gemini)
intake run                           # today
intake run --date 2026-04-28         # specific date
```

## Workflows

### 记录一餐
```
user: 午饭吃了红烧牛肉面，大概550卡
→ intake add --meal "红烧牛肉面" --calories 550
→ reply: ✅ 已记录 红烧牛肉面 ~550kcal (今日)
```

### 带宏量的记录
```
user: 中午吃了鸡胸肉沙拉，400卡，蛋白35g
→ intake add --meal "鸡胸肉沙拉" --calories 400 --protein 35
```

### 查记录
```
user: 今天吃了多少
→ intake view
→ reply with table + daily summary
```

### 查某天
```
user: 看看周一吃了什么
→ intake view --date 2026-04-27
→ reply with table
```

## Data Storage

- Records: `~/Coding/intake/data/YYYY-MM-DD.json`
- Each entry: asset_id, photo_time, meal, calories, macros, confidence
- Manual entries: `asset_id: "manual-{timestamp}"`
- Auto-detected: real Immich asset UUIDs
