# intake

自动食物热量追踪流水线。

**拍照 → Immich → SigLIP2 本地过滤 → Gemini 分析热量 → 记日志**

## 架构

```
        ┌──────────┐     ┌──────────────┐     ┌─────────┐
 拍照 → │  Immich  │ ──→ │   SigLIP2    │ ──→ │ Gemini  │
        │ (照片库)  │     │ (本地过滤食物) │     │ (热量分析)│
        └──────────┘     └──────────────┘     └─────────┘
                               │                    │
                          不是食物→跳过           ↓
                                           data/YYYY-MM-DD.json
```

三步走：
1. **Immich** — 拉指定日期的照片列表
2. **SigLIP2**（本地 CPU 推理 ~0.3s/张） — 判断图片里有没有食物，不是食物的直接跳过，**不出内网**
3. **Gemini**（OpenAI 兼容格式） — 分析食物热量、蛋白质、碳水、脂肪，记入每日日志

## 前置

| 组件 | 要求 |
|------|------|
| [Immich](https://immich.app) | 运行中的实例，获取 API key |
| Gemini API key | 或任何 OpenAI 兼容的视觉模型 endpoint |
| Python 3.11+ | |

## 设置

```bash
cd ~/Coding/intake
cp .env.example .env
# 编辑 .env 填入 Immich key 和 Gemini key

pip install -r requirements.txt
```

## 用法

```bash
# 分析今天的照片
python main.py run

# 分析指定日期
python main.py run --date 2026-04-28

# 手动记录
python main.py add --meal "红烧肉" --calories 600 --protein 25 --carbs 30 --fat 20

# 查看记录
python main.py view --date 2026-04-28
python main.py view --week
```

## Web 查看器

```bash
python web/server.py    # http://localhost:5800
```

功能：
- 日历日期选择器，有记录的日期显示绿点
- 卡片缩略图 + 点击查看大图
- **人工标注**：每张图片可标记「正确/有误」，数据写回 JSON
- **替换图片**：上传新图自动用 pHash 匹配 Immich 中的原图，替换误识别记录
- 训练进度面板
- 可选的用户名密码认证（`.env` 中配 `INTAKE_USER`/`INTAKE_PASS`）

## 微调分类器

Web 端标注积累后可微调 SigLIP2：

```bash
# 导出标注数据到 data/training/ 供检查
python main.py finetune --export

# 确认无误后训练
python main.py finetune

# 训练完成后自动加载 data/finetuned-model/ 下的新模型
```

标注正误的含义：
- **正确**（correct）→ 分类器判断正确，是食物
- **有误**（wrong）→ 分类器误判，实际不是食物

## 数据格式

```json
[
  {
    "asset_id": "xxxx-xxxx",
    "photo_time": "2026-04-28T12:30:00.000Z",
    "thumbnail_url": "http://immich:2283/api/assets/xxx/thumbnail",
    "meal": "一碗牛肉面",
    "calories": 550,
    "protein_g": 25,
    "carbs_g": 60,
    "fat_g": 18,
    "confidence": "high",
    "analyzed_at": "2026-04-28T15:41:23+08:00",
    "user_label": "correct",
    "replacement_image": null
  }
]
```

## 隐私

SigLIP2 在本地 CPU 推理，食物过滤阶段**图片不离开机器**。只有确认是食物的图片才发往 Gemini 云端分析。Immich 内网可达，不暴露公网。

## 设计原则

- **隐私优先**：本地分类器过滤后才走云 API
- **幂等**：已处理的 asset_id 不会重复分析
- **持续改进**：人工标注 → 微调 → 分类更准
- **Gemini prompt 防误识别**：自动拦截截图、海报、菜单、屏幕等假食物图片
