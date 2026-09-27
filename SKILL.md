---
name: inkcal
slug: inkcal
version: 2.0.0
description: Log meals, analyze food photos, track calories and macros, and label results.
category: productivity
---

## When to Use

Use this skill for Jerry's inkcal food tracker — any request involving meal logging, calorie/macro queries, photo pipeline, labeling, or server operations.

Trigger phrases: "记一下吃了", "午饭吃了", "热量", "卡路里", "蛋白", "碳水", "脂肪", "吃了多少", "标注", "改一下", "删掉", "怎么没记上".

## Data Storage

- Project: `~/Coding/inkcal/`
- Database: `data/inkcal.db` (SQLite, WAL mode)

## Command Cheat Sheet

All read commands support `--json` for structured output. All write commands (edit/label/replace/delete/reanalyze) support the unified locator (see below).

```
数据写入
  inkcal add --meal M --calories N [--protein/carbs/fat/date/time/confidence] [--json]
  inkcal edit <locator> [--new-meal/--calories/--protein/--carbs/--fat/--date/--time/--note] [--json]
  inkcal delete <locator> [--json]
  inkcal analyze --id ASSET_ID [--source immich|photoprism] [--json]
  inkcal reanalyze <locator> --notes "补充说明" [--json]

数据读取
  inkcal view [--date D | --week | --month YYYY-MM | --from F --to T] [--json]
  inkcal stats [--from F --to T | --last 7d|2w|1m] [--group-by day] [--json]
  inkcal search KEYWORD [--from F --to T] [--limit N] [--json]

标注与维护
  inkcal label <locator> --label correct|wrong [--json]
  inkcal label --list [--date D] [--json] / --status [--json]
  inkcal replace <locator> --image PATH

可观测性
  inkcal explain (--id PREFIX | --date D) [--json]  照片去向五态追溯
  inkcal events [--json]                             拉取未消费的 pipeline 事件
  inkcal events --peek                                查看但不消费
  inkcal events --consumed --limit N                  历史事件
  inkcal run [--date D]                              完整流水线
```

## Record Locator (all write commands)

Four modes, resolved in priority order. Ambiguous matches return `error=ambiguous` + candidates for the agent to show the user.

| Flag | Example | When to use |
|---|---|---|
| `--ref N` | `--ref 42` | Shortest — from `--json` output's `id` field |
| `--id PREFIX` | `--id e3f47028` | Asset ID prefix (≥1 char, longer = more specific) |
| `--last` | `--last` | Most recent record, no thinking needed |
| `--meal K [--date D]` | `--meal 红烧肉 --date 2026-07-21` | Natural language keyword + optional date |

## Error Codes (--json mode)

| code | exit | meaning | agent action |
|---|---|---|---|
| `not_found` | 2 | 记录/asset 不存在 | 换指代或告知用户 |
| `ambiguous` | 3 | 指代命中多条 | 展示 candidates 追问用户 |
| `invalid_args` | 64 | 参数错误 | 自己修正 |
| `external_error` | 69 | Immich/Gemini 不可达 | 告知用户服务状态 |
| `not_food` | 4 | Gemini 判定非食物 | 询问是否强制记录 |

## Estimation Rules

Calorie/macro estimation requires common-sense judgement — this is the **agent's responsibility**, not the system's. Guidelines:

- **Exact numbers given by user** → use directly, `confidence=high`
- **Well-known dish (宫保鸡丁, 咖喱饭, 牛肉面)** → use mid-range estimate from training knowledge, `confidence=medium`
- **Vague description ("一些菜", "随便吃的")** → rough estimate, `confidence=low`; ask for clarification if possible
- **User says "两人份"/"一半"/"少算了X"** → use `inkcal edit` or `inkcal reanalyze` with notes; system preserves old values in `reanalysis_history`
- **Aggregation ("上周平均", "这个月总热量")** → use `inkcal stats`, **never** compute manually — the code is deterministic, the agent is not

## Key Rules

1. Use `inkcal` CLI for all data operations. Never edit the database directly.
2. Dates are Asia/Hong_Kong (UTC+8). Agent converts "昨天"/"上周三" to `YYYY-MM-DD`; the CLI only accepts `YYYY-MM-DD`.
3. After mutations, the `--json` output already contains the updated record — no need to `inkcal view` for verification.
4. Photo pipeline decisions are fully traceable via `inkcal explain`. If a user asks "why wasn't this recorded", use `explain` to get a definitive answer.
5. Server lifecycle operations → see `references/pipeline-web.md`.
6. JSON parsing quirks → see `src/calorie_analyzer.py:_parse_response()`.
7. Cron false-positive caching → handled in code (`classified_non_food.decided_by`, `inkcal explain`, `inkcal analyze`).
