# inkcal CLI Workflows

## Command Reference

```bash
# Manual entry
inkcal add --meal "红烧牛肉面" --calories 550 --protein 25 --carbs 70 --fat 15
inkcal add --meal "夜宵鸡蛋灌饼" --calories 620 --date 2026-04-30 --time 23:40 --confidence low

# View records
inkcal view
inkcal view --date 2026-04-28
inkcal view --week
inkcal view --month 2026-04

# Run photo pipeline
inkcal run
inkcal run --date 2026-04-28

# Label records
inkcal label --list
inkcal label --list --date 2026-04-28
inkcal label --id <asset-prefix> --label correct --date 2026-04-28
inkcal label --id <asset-prefix> --label wrong --date 2026-04-28
inkcal label --status

# Replace image via Immich pHash matching
inkcal replace --id <asset-prefix> --image /path/to/photo.jpg --date 2026-04-28

```

## Natural-Language Meal Logging

### One meal

1. Extract meal, calories, macros, date, and time.
2. Estimate calories when the food description is concrete.
3. Run `inkcal add ...`.
4. Verify with `inkcal view [--date YYYY-MM-DD]`.
5. Reply with a compact confirmation.

Example:

```bash
inkcal add --meal "红烧牛肉面" --calories 550 --confidence medium
```

Reply:

`✅ 已记录：红烧牛肉面 ~550 kcal（今日）`

### Multiple meals

Run one `inkcal add` command per meal. Preserve user-provided times.

```bash
inkcal add --meal "鸡蛋三明治" --calories 420 --time 09:10
inkcal add --meal "鸡胸肉沙拉" --calories 480 --protein 35 --time 13:20
```

### Query totals

Use CLI output as source of truth.

```bash
inkcal view
inkcal view --date 2026-04-28
inkcal view --week
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
