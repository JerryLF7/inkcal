# intake 🍽️

自动食物热量追踪流水线。

**手机拍照 → Immich → SigLIP2 本地过滤 → Gemini 分析热量 → 记日志**

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
# 1. 克隆并配环境变量
cd ~/Coding/intake
cp .env.example .env
# 编辑 .env 填入 Immich key 和 Gemini key

# 2. 装依赖
pip install -r requirements.txt
```

## 用法

```bash
# 分析今天的照片
python main.py

# 分析指定日期
python main.py --date 2026-04-28
```

跑一次就会：
1. 从 Immich 拉指定日期所有照片
2. 每张用 SigLIP2 判断是不是食物（本地 CPU，~0.3s/张）
3. 是食物的发给 Gemini 分析热量（含截图/海报/菜单等误识别拦截）
4. 写入 `data/YYYY-MM-DD.json`

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
    "analyzed_at": "2026-04-28T15:41:23+08:00"
  }
]
```

## 隐私

SigLIP2 在本地 CPU 推理，食物过滤阶段**图片不离开机器**。只有确认是食物的图片才发往 Gemini 云端分析。Immich 内网可达，不暴露公网。

## 设计原则

- **隐私优先**：本地分类器过滤后才走云 API
- **幂等**：已处理的 asset_id 不会重复分析
- **Gemini prompt 防误识别**：自动拦截截图、海报、菜单、屏幕等假食物图片
