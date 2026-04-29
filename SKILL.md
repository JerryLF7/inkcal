---
name: intake
slug: intake
version: 1.0.0
description: Record, view, and query food/calorie intake via the intake CLI.
category: productivity
---

## When to Use

Trigger when user input matches ANY of:

- **Explicit trigger**: "记录一下", "记一下吃了", "记餐", "记饮食"
- **Food mention**: "吃了...", "午饭...", "晚饭...", "午餐...", "晚餐...", "今天吃了"
- **Query trigger**: "看看今天吃了", "看记录", "热量", "卡路里", "吃了多少", "今天吃了啥", "看看饮食"
- **Calorie details**: mentions specific macros or calories

## CLI

Available at `~/.local/bin/intake`, which wraps `~/Coding/intake/main.py`.

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

## Core Rules

1. **Use the `intake` CLI only.** Never read or edit `data/*.json` files directly.
2. **Parse natural language**: Extract meal description, calories, and macros from user's text. Use common sense for portion sizes.
3. **Always include `--meal` and `--calories`**. Macros (protein/carbs/fat) are optional but encouraged.
4. **Default date is today** unless user specifies otherwise.
5. **Default confidence**: `medium` for manual entries (user told us), `high` only if they seem very sure.
6. **Chinese descriptions preferred** for the meal field.

## Workflows

### 1. 记录一餐
```
user: 午饭吃了红烧牛肉面，大概550卡
→ intake add --meal "红烧牛肉面" --calories 550
→ reply: ✅ 已记录 红烧牛肉面 ~550kcal (今日)
```

### 2. 带宏量的记录
```
user: 中午吃了鸡胸肉沙拉，400卡，蛋白35g
→ intake add --meal "鸡胸肉沙拉" --calories 400 --protein 35
→ reply: ✅ 已记录 鸡胸肉沙拉 ~400kcal (蛋白35g)
```

### 3. 查记录
```
user: 今天吃了多少
→ intake view
→ reply with table + daily summary
```

### 4. 查某天
```
user: 看看周一吃了什么
→ intake view --date 2026-04-27
→ reply with table
```

## Data Storage

- Records: `~/Coding/intake/data/YYYY-MM-DD.json`
- Each entry: asset_id, photo_time, meal, calories, macros, confidence
- Manual entries have `asset_id: "manual-{timestamp}"`
- Immich-auto-detected entries have real asset UUIDs

## Boundary Conditions

| Situation | Action |
|-----------|--------|
| User says vague "吃了点东西" without calories | Ask "大概多少卡？" or estimate reasonably |
| Meal has no protein/carbs/fat info | Skip macros, only record meal + calories |
| User mentions yesterday/last night | Pass `--date` accordingly |
| Multiple meals in one message | Record separately, call `intake add` for each |
| Query returns empty | Reply "该时段暂无记录" |
