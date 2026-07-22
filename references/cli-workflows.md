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
inkcal view --from 2026-07-01 --to 2026-07-14

# Stats (aggregate — code computes, not agent)
inkcal stats --last 7d
inkcal stats --last 1m
inkcal stats --from 2026-07-01 --to 2026-07-14 --group-by day

# Edit a record (old values preserved in reanalysis_history)
inkcal edit --ref 42 --calories 300 --note "两人份，减半"
inkcal edit --meal 红烧肉 --date 2026-07-21 --protein 30
inkcal edit --last --confidence low

# Search meal descriptions (FTS5)
inkcal search 咖喱
inkcal search 鸡胸 --from 2026-07-01 --to 2026-07-22 --json

# Delete (auto-adds Immich asset to ignore list)
inkcal delete --ref 42
inkcal delete --last

# Run photo pipeline
inkcal run
inkcal run --date 2026-04-28

# Label records
inkcal label --list
inkcal label --list --date 2026-04-28
inkcal label --ref 42 --label correct
inkcal label --meal 咖喱 --date 2026-07-21 --label wrong
inkcal label --status

# Replace image via Immich pHash matching
inkcal replace --ref 42 --image /path/to/photo.jpg --date 2026-04-28

# Explain photo pipeline decision
inkcal explain --id <asset-prefix>    # single photo: which state + decided_by + hint
inkcal explain --date 2026-07-21      # full day reconciliation against Immich

# Force-analyze a classifier-missed photo (skip food detection)
inkcal analyze --id <asset-id> --source immich

# Re-analyze with additional context
inkcal reanalyze --ref 42 --notes "少算了一份米饭"
inkcal reanalyze --last --notes "实际是三人份，每份约400kcal"

# Pipeline events (agent proactive reporting)
inkcal events                         # pull + consume
inkcal events --peek                  # view without consuming
inkcal events --consumed --limit 20   # historical

# Migrate JSON → SQLite
inkcal migrate
```

All read commands support `--json` for structured machine-readable output.

## Natural-Language Meal Logging

### One meal

1. Extract meal, calories, macros, date, and time.
2. Estimate calories when the food description is concrete.
3. Run `inkcal add ...`. With `--json`, the output contains the inserted record — no need for a second verify step.
4. Reply with a compact confirmation.

Example:

```bash
inkcal add --meal "红烧牛肉面" --calories 550 --confidence medium --json
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

Never compute totals manually from per-meal records. Use `stats` for aggregation.

```bash
inkcal stats --last 7d                           # weekly totals
inkcal stats --from 2026-07-01 --to 2026-07-14   # custom range
inkcal view --date 2026-04-28                    # single day
```

If CLI prints `🍽️  暂无记录`, reply `该时段暂无记录。`

### Editing and correcting

Use resolver locators to avoid two-step "search → pick ID → edit" workflows:

```bash
# Directly target by keyword + date
inkcal edit --meal 红烧肉 --date 2026-07-21 --calories 300 --note "两人份减半"

# If ambiguous, the CLI returns candidates — show them to the user
# Then re-execute with the exact --ref from the chosen candidate
inkcal edit --ref 42 --calories 300
```

### Tracing missing photos

When the user asks why a photo wasn't recorded, use `explain` instead of guessing:

```bash
inkcal explain --id <prefix>     # definitive answer: five states + decided_by
inkcal explain --date 2026-07-21 # full-day reconciliation
```

### Classifier misses

When SigLIP2 missed a food photo, force-analyze it:

```bash
inkcal analyze --id <asset-id> --source immich
```

## Estimation Rules

| Situation | Action |
|-----------|--------|
| Concrete food, no calories | Estimate a midpoint or range; use `--confidence low` |
| Very vague: "吃了点东西" | Ask for rough food/calorie details |
| User provides exact calories | Use that number; use `--confidence high` |
| User provides partial macros | Include provided macros; omit unknown macros |
| Late-night phrases: "昨晚", "半夜" | Use Asia/Hong_Kong calendar date |
| Multiple meals in one message | Add each separately |
| "两人份"/"减半"/"少算了X" | Use `inkcal edit` with --note for traceability |
| Missing ingredients/portions | Use `inkcal reanalyze --notes` for Gemini re-estimation |
| Aggregate queries ("上周平均") | Use `inkcal stats` — never compute manually |
