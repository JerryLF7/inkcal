---
name: intake
slug: intake
version: 1.1.0
description: Record, view, and query food/calorie intake via the intake CLI.
category: productivity
---

## When to Use

Trigger on any of: "记一下吃了", "记录一下", "午饭/晚饭/午餐/晚餐吃了", "今天吃了", "热量", "卡路里", "吃了多少", or explicit macros mention.

## Core Rules

1. **Use `intake` CLI only.** Never read/write `data/*.json` directly.
2. **Parse natural language**: Extract meal description, calories, macros. Estimate reasonably if user is vague.
3. **Always include `--meal` and `--calories`**. Macros (protein/carbs/fat) are optional.
4. **Default date is today** unless user specifies yesterday/last night etc.
5. **Default confidence**: `medium` for manual entries.
6. **Chinese preferred** for meal description.

## Boundary Conditions

| Situation | Action |
|-----------|--------|
| Vague "吃了点东西" with no calories | Ask "大概多少卡？" or estimate reasonably |
| No macro info | Skip macros, record meal + calories only |
| Yesterday/last night | Pass `--date` accordingly |
| Multiple meals in one message | Call `intake add` for each separately |
| Query returns empty | Reply "该时段暂无记录" |

## Quick Reference

| Topic | File |
|-------|------|
| CLI commands, workflows, data format | `usage.md` |
