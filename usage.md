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

# Fine-tune classifier on labeled data
intake finetune                      # train (needs ≥4 labeled samples)
intake finetune --export             # export images for review only
```

## Web Viewer

```bash
cd ~/Coding/intake
python3 web/server.py                # http://localhost:5800
```

### Auth

Set `INTAKE_USER` and `INTAKE_PASS` in `.env` to enable login. Leave empty to skip.

### Labeling flow

1. Tap a meal card → lightbox with full image
2. Tap "正确" or "有误" to label
3. "换图" to upload a replacement (auto-matched to Immich via pHash)
4. Check progress via "训练进度" button

### Fine-tuning flow

1. Label records in Web UI (correct/wrong)
2. Run `intake finetune --export` to inspect training data
3. Run `intake finetune` to train
4. Model saved to `data/finetuned-model/`, auto-loaded on next run

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
- Training exports: `data/training/food/`, `data/training/not-food/`
- Fine-tuned model: `data/finetuned-model/`
- Replacement images: `data/images/` (only for unmatched uploads)
