---
name: inkcal
slug: inkcal
version: 1.4.0
description: Log meals, analyze food photos, track calories and macros, and label results.
category: productivity
---

## When to Use

Use this skill for Jerry's food inkcal tracker:

- Meal logging: "记一下吃了", "午饭/晚饭吃了", "今天吃了", "昨晚吃了"
- Calorie or macro queries: "热量", "卡路里", "蛋白", "碳水", "脂肪", "吃了多少"
- Photo pipeline: Immich → SigLIP2 → Gemini → daily records
- Web UI viewing, labeling, image replacement, or mobile UI tweaks
- Classifier accuracy tracking via labeling

## Data Storage

- Project path: `~/Coding/inkcal/`
- Records: `~/Coding/inkcal/data/YYYY-MM-DD.json`
- Fine-tuned model (optional): `~/Coding/inkcal/data/finetuned-model/`

## External Endpoints

| Service | Use | Privacy note |
|---------|-----|--------------|
| Immich | Photo listing and thumbnails on local network | Private photos stay in LAN during filtering |
| Gemini-compatible vision API | Calorie/macro analysis for detected food photos | Only photos passing local food filter are sent |

## Core Rules

1. Use `inkcal` CLI for all records, labels, and replacements; avoid direct JSON edits.
2. Parse natural language into meal, calories, macros, date, and time. Prefer Chinese meal descriptions.
3. Manual entries require `--meal` and `--calories`; macros via `--protein`, `--carbs`, `--fat`.
4. Default date is today in Asia/Hong_Kong. Use `--date YYYY-MM-DD` and `--time HH:MM` when implied.
5. Default confidence is `medium`; use `high` for exact numbers, `low` for rough estimates.
6. After mutations, verify with `inkcal view`, `inkcal label --status`, or the web UI.
7. For code changes, inspect files first, preserve existing user changes, verify, then commit.

## Quick Reference

| Task | Load |
|------|------|
| CLI commands, meal logging, queries, estimation | `references/cli-workflows.md` |
| Photo pipeline, env vars, web UI, labeling | `references/pipeline-web.md` |
| User-facing docs and architecture | `README.md`, `usage.md` |
