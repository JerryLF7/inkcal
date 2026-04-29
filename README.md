# foodlens 🍽️

自动食物热量追踪流水线。

**手机拍照 → Immich → moondream 本地过滤 → Gemini 分析热量 → 记日志**

## 架构

```
        ┌──────────┐     ┌──────────────┐     ┌─────────┐
 拍照 → │  Immich  │ ──→ │ moondream    │ ──→ │ Gemini  │
        │ (照片库)  │     │ (本地过滤食物) │     │ (热量分析)│
        └──────────┘     └──────────────┘     └─────────┘
                               │                    │
                          不是食物→跳过           ↓
                                           data/YYYY-MM-DD.json
```

三步走：
1. **Immich** — 拉当天照片列表
2. **moondream**（Ollama 本地跑） — 判断图片里有没有食物，不是食物的直接跳过，**不出内网**
3. **Gemini**（OpenAI 兼容格式） — 分析食物热量、蛋白质、碳水、脂肪，记入每日日志

## 前置

| 组件 | 要求 |
|------|------|
| [Immich](https://immich.app) | 运行中的实例，获取 API key |
| [Ollama](https://ollama.com) + moondream | `ollama pull moondream` |
| Gemini API key | 或者任何 OpenAI 兼容的视觉模型 endpoint |

## 设置

```bash
# 1. 装 Ollama + moondream
curl -fsSL https://ollama.com/install.sh | sh
ollama pull moondream

# 2. 配环境变量
cd ~/Coding/foodlens
cp .env.example .env
# 编辑 .env 填入 Immich key 和 Gemini key

# 3. 装依赖
pip install -r requirements.txt
```

## 用法

```bash
python main.py
```

跑一次就会：
1. 从 Immich 拉你今天所有照片
2. 每张用 moondream 看是不是食物
3. 是食物的发给 Gemini 分析热量
4. 写入 `data/YYYY-MM-DD.json`

## 数据格式

```json
[
  {
    "asset_id": "xxxx-xxxx",
    "photo_time": "2026-04-28T12:30:00.000Z",
    "thumbnail_url": "http://immich:2283/api/asset/xxx/thumbnail",
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

moondream 在 NUC 本地跑，食物过滤阶段**图片不离开机器**。只有确认是食物的图片才发往 Gemini 云端分析。Immich 内网可达，不暴露公网。

## 设计原则

- **隐私优先**：本地过滤后才走云 API
- **幂等**：已处理的 asset_id 不会重复分析
- **精简**：零外部依赖的纯 Python，单文件编排

---

Made with 🐙 by Oddy
