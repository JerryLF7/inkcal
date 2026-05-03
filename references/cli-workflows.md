# intake CLI Workflows

## Command Reference

```bash
# Manual entry
intake add --meal "红烧牛肉面" --calories 550 --protein 25 --carbs 70 --fat 15
intake add --meal "夜宵鸡蛋灌饼" --calories 620 --date 2026-04-30 --time 23:40 --confidence low

# View records
intake view
intake view --date 2026-04-28
intake view --week
intake view --month 2026-04

# Run photo pipeline
intake run
intake run --date 2026-04-28

# Label records
intake label --list
intake label --list --date 2026-04-28
intake label --id <asset-prefix> --label correct --date 2026-04-28
intake label --id <asset-prefix> --label wrong --date 2026-04-28
intake label --status

# Replace image via Immich pHash matching
intake replace --id <asset-prefix> --image /path/to/photo.jpg --date 2026-04-28

```

## Natural-Language Meal Logging

### One meal

1. Extract meal, calories, macros, date, and time.
2. Estimate calories when the food description is concrete.
3. Run `intake add ...`.
4. Verify with `intake view [--date YYYY-MM-DD]`.
5. Reply with a compact confirmation.

Example:

```bash
intake add --meal "红烧牛肉面" --calories 550 --confidence medium
```

Reply:

`✅ 已记录：红烧牛肉面 ~550 kcal（今日）`

### Multiple meals

Run one `intake add` command per meal. Preserve user-provided times.

```bash
intake add --meal "鸡蛋三明治" --calories 420 --time 09:10
intake add --meal "鸡胸肉沙拉" --calories 480 --protein 35 --time 13:20
```

### Query totals

Use CLI output as source of truth.

```bash
intake view
intake view --date 2026-04-28
intake view --week
```

If CLI prints `🍽️  暂无记录`, reply `该时段暂无记录。`

## Estimation Rules

| Situation | Action |
|-----------|--------|
| Concrete food, no calories | Estimate a midpoint or range; use `--confidence low` |
| Very vague: "吃了点东西" | Ask for rough food/calorie details |
| User provides exact calories | Use that number; use `--confidence high` |
| User provides partial macros | Include provided macros; omit unknown macros |
| Late-night phrases: "昨晚", "半夜" | Use Asia/Hong_Kong calendar date |
| Multiple meals in one message | Add each separately |
