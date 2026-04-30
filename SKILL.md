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
| CLI commands, workflows, web viewer, data format | `usage.md` |

## Web Viewer Workflow

Use the web viewer when Jerry asks to view intake records in a browser or tweak the mobile UI.

1. Inspect `~/Coding/intake/web/server.py` and `~/Coding/intake/web/static/index.html` before editing.
2. Start preview from the project root with `INTAKE_PORT=5800 python3 web/server.py` using `terminal(background=true)`.
3. Verify with `curl -sS http://127.0.0.1:5800/api/today` and `ss -ltnp | grep ':5800'`.
4. Open `http://127.0.0.1:5800/` with the browser tool and test interactions directly.
5. For date UI, prefer local-date formatting (`getFullYear()`, `getMonth()+1`, `getDate()`) over `toISOString().slice(0,10)` to avoid timezone day shifts.
6. When adding date selection, keep picker value, visible date label, active shortcut chips, and fetched `/api/records?date=YYYY-MM-DD` data synchronized.
